"""Esquemas de split del AVM (F8.2): K-fold por cluster, holdout temporal y leave-group-out.

Todas las funciones devuelven solo índices (`Split`: arrays de posiciones de fila) y no tocan los
datos: reciben únicamente los ids de cluster, de grupo o las fechas de snapshot. Así sirven igual
para un DataFrame, un array o cualquier estructura indexable por posición.

Regla de cero leakage (principio 4 del ROADMAP): ningún cluster (o grupo) debe aparecer a la vez
en train y en test. Un mismo inmueble publicado en varios portales forma un cluster (F5.3); si sus
copias quedaran repartidas entre train y test, el modelo "vería" en entrenamiento el aviso que
después se evalúa y las métricas saldrían infladas.

Qué garantiza cada función (y qué no):
- `grouped_kfold`: ningún cluster en train y test a la vez, por construcción.
- `leave_group_out`: lo garantiza para los GRUPOS que recibe, no para clusters. Si las copias de un
  inmueble quedan en grupos distintos (por ejemplo, barrios normalizados distinto, F4.4), una
  puede quedar en train mientras otra es test.
- `temporal_holdout`: solo si se le pasan los `cluster_ids`.
Todas dependen de que el dedup (F5) haya agrupado bien las copias: la garantía es "clusters no
vistos según el dedup", no "inmuebles nunca vistos".

Los splits son reproducibles: no hay azar sin semilla explícita, y el resultado no depende del
orden de las filas. Con la misma versión de numpy (la fija uv.lock) y los mismos datos, el reparto
es idéntico; la asignación cluster → fold de `grouped_kfold` depende del conjunto completo de
clusters, así que puede cambiar si cambian los datos (conviene guardarla en el manifest del
modelo, principio 6 del ROADMAP, si se la usa para ajustar hiperparámetros).

Los índices de cada array salen ordenados de menor a mayor y son posiciones en el array que se
pasó. Si se llama con un subconjunto (por ejemplo `cluster_ids[train]`), hay que mapearlos de
vuelta a las posiciones del dataset original.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any, NamedTuple

import numpy as np
from numpy.typing import ArrayLike, NDArray

IndexArray = NDArray[np.intp]


class Split(NamedTuple):
    """Par de índices de fila (train, test). Se puede desempaquetar como una tupla."""

    train: IndexArray
    test: IndexArray


# --------------------------------------------------------------------------------------------
# Validación de entradas
# --------------------------------------------------------------------------------------------


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float | np.floating) and bool(np.isnan(value)))


def _has_timezone(value: object) -> bool:
    return getattr(value, "tzinfo", None) is not None


def _as_labels(values: ArrayLike, name: str) -> NDArray[Any]:
    """Array 1-D, no vacío y sin valores faltantes (None, NaN)."""
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{name}: debe ser 1-D, tiene {array.ndim} dimensiones")
    if array.size == 0:
        raise ValueError(f"{name}: no puede estar vacío")
    if array.dtype.kind == "f" and np.isnan(array).any():
        raise ValueError(f"{name}: contiene NaN")
    if array.dtype.kind == "O" and any(_is_missing(value) for value in array):
        raise ValueError(f"{name}: contiene None o NaN")
    return array


def _factorize(labels: NDArray[Any], name: str) -> tuple[NDArray[Any], IndexArray]:
    """Valores únicos (ordenados) y, para cada fila, la posición de su valor entre los únicos."""
    try:
        uniques, codes = np.unique(labels, return_inverse=True)
    except TypeError as exc:
        raise ValueError(f"{name}: los valores no son comparables entre sí ({exc})") from exc
    return uniques, codes.reshape(-1).astype(np.intp)


def _without_timezone[T](convert: Callable[[], T], name: str) -> T:
    """Ejecuta `convert()` y falla si numpy tuvo que interpretar una zona horaria.

    numpy no rechaza las zonas horarias: convierte a UTC (12:00-03:00 pasa a 15:00) y solo emite un
    UserWarning. Eso cubre también los strings ISO con "Z" u offset, que no tienen `tzinfo`.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = convert()
    if any("timezone" in str(warning.message) for warning in caught):
        raise ValueError(f"{name}: no se admiten fechas con zona horaria")
    return result


def _as_dates(values: ArrayLike, name: str) -> NDArray[np.datetime64]:
    """Array 1-D de fechas (datetime64), no vacío y sin NaT."""
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{name}: debe ser 1-D, tiene {array.ndim} dimensiones")
    if array.size == 0:
        raise ValueError(f"{name}: no puede estar vacío")
    if array.dtype.kind in "biuf":  # un número se interpretaría en silencio como época
        raise ValueError(f"{name}: debe contener fechas, no números")
    if array.dtype.kind == "O" and any(_has_timezone(value) for value in array):
        raise ValueError(f"{name}: no se admiten fechas con zona horaria")
    try:
        dates = _without_timezone(lambda: array.astype("datetime64[us]"), name)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: no se puede interpretar como fechas ({exc})") from exc
    if np.isnat(dates).any():
        raise ValueError(f"{name}: contiene fechas faltantes (NaT)")
    return dates


def _as_cutoff(cutoff: object) -> np.datetime64:
    if isinstance(cutoff, bool | int | float | np.number):
        raise ValueError(f"cutoff: debe ser una fecha, no un número (recibido {cutoff!r})")
    if _has_timezone(cutoff):
        raise ValueError("cutoff: no se admiten fechas con zona horaria")
    try:
        value = _without_timezone(lambda: np.datetime64(cutoff, "us"), "cutoff")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cutoff: no se puede interpretar como fecha ({exc})") from exc
    if np.isnat(value):
        raise ValueError("cutoff: es una fecha faltante (NaT)")
    return value


def _validate_n_splits(n_splits: int, n_clusters: int) -> None:
    if isinstance(n_splits, bool) or not isinstance(n_splits, int | np.integer):
        raise ValueError(f"n_splits: debe ser un entero (recibido {n_splits!r})")
    if n_splits < 2:
        raise ValueError(f"n_splits: debe ser >= 2 (recibido {n_splits})")
    if n_splits > n_clusters:
        raise ValueError(
            f"n_splits ({n_splits}) no puede superar la cantidad de clusters ({n_clusters})"
        )


def _validate_seed(seed: int) -> None:
    if seed is None:
        raise ValueError("seed: es obligatoria (sin semilla el split no es reproducible)")
    if isinstance(seed, bool) or not isinstance(seed, int | np.integer):
        raise ValueError(f"seed: debe ser un entero (recibido {seed!r})")
    if seed < 0:
        raise ValueError(f"seed: debe ser un entero >= 0 (recibido {seed})")


# --------------------------------------------------------------------------------------------
# K-fold agrupado por cluster
# --------------------------------------------------------------------------------------------


def grouped_kfold(cluster_ids: ArrayLike, n_splits: int, seed: int) -> list[Split]:
    """K-fold en el que cada cluster queda entero en un único fold (esquema (a) de F8.2).

    Cada uno de los `n_splits` folds es el test de un `Split`, y su train son las filas de los
    demás folds. Los tests de todos los folds particionan las filas: cada fila es test
    exactamente una vez, y ningún cluster aparece a la vez en train y en test.

    Reparto: los clusters se mezclan con `numpy.random.default_rng(seed)` y se asignan de mayor a
    menor tamaño, cada uno al fold que lleva menos filas hasta ese momento (el azar solo desempata
    clusters del mismo tamaño). Eso mantiene los folds parejos: la diferencia entre el fold más
    grande y el más chico no supera el tamaño del cluster más grande.

    Limitación: un cluster enorme (por ejemplo, un inmueble republicado muchas veces) desbalancea
    los folds, y no se puede arreglar sin romper la agrupación.

    Errores (ValueError): ids vacíos, no 1-D, con None o NaN o no comparables; `n_splits` que no
    sea un entero >= 2 o que supere la cantidad de clusters; `seed` ausente, no entera o negativa.
    """
    labels = _as_labels(cluster_ids, "cluster_ids")
    clusters, cluster_of_row = _factorize(labels, "cluster_ids")
    _validate_n_splits(n_splits, clusters.size)
    _validate_seed(seed)

    sizes = np.bincount(cluster_of_row, minlength=clusters.size)
    shuffled = np.random.default_rng(seed).permutation(clusters.size)
    # Orden estable: entre clusters del mismo tamaño queda el orden aleatorio.
    order = shuffled[np.argsort(-sizes[shuffled], kind="stable")]

    fold_rows = np.zeros(n_splits, dtype=np.intp)
    fold_of_cluster = np.empty(clusters.size, dtype=np.intp)
    for cluster in order:
        fold = int(np.argmin(fold_rows))  # ante empate, el fold de menor índice
        fold_of_cluster[cluster] = fold
        fold_rows[fold] += sizes[cluster]

    fold_of_row = fold_of_cluster[cluster_of_row]
    splits = []
    for fold in range(n_splits):
        in_test = fold_of_row == fold
        splits.append(Split(np.flatnonzero(~in_test), np.flatnonzero(in_test)))
    return splits


# --------------------------------------------------------------------------------------------
# Holdout temporal
# --------------------------------------------------------------------------------------------


def temporal_holdout(
    snapshot_dates: ArrayLike,
    cutoff: object,
    *,
    cluster_ids: ArrayLike | None = None,
) -> Split:
    """Holdout temporal: entrena con el pasado y evalúa desde el corte (esquema (b) de F8.2).

    - train = filas con `snapshot_dates < cutoff`, estrictamente anteriores al corte.
    - test  = filas con `snapshot_dates >= cutoff`; el snapshot del corte es parte del test.

    `snapshot_dates` acepta `datetime64`, `datetime.date`, `datetime.datetime` o strings ISO, y
    `cutoff` cualquiera de esos tipos. Las filas no tienen que venir ordenadas. Toda fecha de
    train es anterior a toda fecha de test.

    Exclusión de clusters ya vistos (`cluster_ids`, opcional). Un mismo inmueble publicado en un
    snapshot viejo y otra vez en uno nuevo queda a ambos lados del corte: es leakage por
    duplicados a lo largo del tiempo (cero leakage, F5.3). Con `cluster_ids`, se EXCLUYEN DEL
    TEST las filas cuyo cluster aparece en el train; el train no se toca. Tras la exclusión,
    ningún cluster está a la vez en train y en test.

    Por qué se excluye del test y no del train: el train tiene que reflejar el historial
    completo que el modelo tendría en producción, y el test tiene que medir el desempeño sobre
    inmuebles que el modelo no vio. Sacar filas del train le quitaría al modelo historial que sí
    tendría al usarse.

    Costos y límites de esa elección (no es una exclusión neutral):
    - El test pierde los inmuebles republicados: mide el desempeño sobre inmuebles nuevos y no
      sobre republicaciones. Si la persistencia de un aviso está asociada con su precio
      publicado, el test deja de ser una muestra neutral: conviene comparar las covariables de
      las filas excluidas y las retenidas (ciudad, tipo, precio publicado) antes de leer las
      métricas.
    - Las filas excluidas quedan fuera de ambos conjuntos. Quien llama debe reportar cuántas son
      y puede obtenerlas con `np.setdiff1d(np.flatnonzero(snapshot_dates >= cutoff), test)`.
    - Un cluster nuevo que aparece en varios snapshots posteriores al corte conserva todas sus
      filas en test: los inmuebles más persistentes pesan más en las métricas y esas filas no son
      independientes (puede volver menos precisa la cobertura estimada de los intervalos, F9.2 y
      F9.3). Reducir a una fila por cluster, con una regla que dependa solo de la fecha y nunca
      del precio, queda para F5.3.
    - La garantía es "clusters no vistos según el dedup". Si F5.2 separa en clusters distintos
      dos publicaciones del mismo inmueble (por ejemplo, por un cambio de precio mayor que su
      umbral de similitud), ese inmueble queda a ambos lados del corte sin que esta función lo
      detecte. Medir ese recall es parte de F5.4.

    Sin `cluster_ids` no se excluye nada: train y test particionan todas las filas, y el
    leakage por duplicados a través del tiempo queda a cargo de quien llama.

    El corte se compara como instante contra las fechas (un día se toma a las 00:00): un corte
    con hora posterior a medianoche deja el snapshot de ese día en train. Para que el día del
    corte sea test, hay que pasar el corte sin hora. No se admiten fechas ni cortes con zona
    horaria (ValueError), sean objetos con `tzinfo` o strings ISO con "Z" u offset: numpy los
    convertiría a UTC con solo un aviso, y el borde del corte se movería sin que se note.

    Errores (ValueError): fechas vacías, no 1-D, numéricas, con zona horaria, no interpretables o
    con NaT; corte numérico, con zona horaria, no interpretable o NaT; `cluster_ids` de otro largo
    o con None o NaN; train vacío (ninguna fecha anterior al corte) o test vacío (ninguna fecha
    desde el corte, o todas las candidatas excluidas por clusters ya vistos). Un holdout
    degenerado no debe pasar en silencio.
    """
    dates = _as_dates(snapshot_dates, "snapshot_dates")
    cut = _as_cutoff(cutoff)
    is_train = dates < cut
    is_test = ~is_train

    if cluster_ids is not None:
        clusters = _as_labels(cluster_ids, "cluster_ids")
        if clusters.shape != dates.shape:
            raise ValueError(
                "cluster_ids debe tener el mismo largo que snapshot_dates "
                f"(recibidos {clusters.size} y {dates.size})"
            )
        is_test &= ~np.isin(clusters, clusters[is_train])

    train = np.flatnonzero(is_train)
    test = np.flatnonzero(is_test)
    if train.size == 0:
        raise ValueError("train vacío: ninguna fecha es anterior al corte")
    if test.size == 0:
        reason = (
            "todas las filas desde el corte tienen clusters ya vistos en train"
            if cluster_ids is not None and (~is_train).any()
            else "ninguna fecha es igual o posterior al corte"
        )
        raise ValueError(f"test vacío: {reason}")
    return Split(train, test)


# --------------------------------------------------------------------------------------------
# Leave-group-out
# --------------------------------------------------------------------------------------------


def leave_group_out(groups: ArrayLike) -> dict[Any, Split]:
    """Un split por grupo, dejándolo entero afuera del train (esquema (c) de F8.2).

    Pensado para leave-barrio-out: mide cuánto generaliza el modelo a un barrio que no vio. Para
    cada grupo, el test son sus filas y el train son todas las demás. Devuelve un diccionario
    ordenado por grupo ascendente (las claves son valores de Python, no escalares de numpy).

    Con barrios de pocas observaciones la métrica de cada split es ruidosa (F7.2): conviene
    mirar la distribución entre grupos y no solo el promedio.

    Es leave-GROUP-out, no leave-cluster-out: no recibe `cluster_ids`. Si las copias de un mismo
    inmueble quedan etiquetadas con barrios distintos (F4.4), están en grupos distintos y una
    puede quedar en train mientras otra es test. Según el diseño previsto en F5.2, el blocking por
    barrio haría improbable que un cluster cruce barrios, pero esta función no lo verifica.

    Errores (ValueError): grupos vacíos, no 1-D, con None o NaN, no comparables, o menos de 2
    grupos distintos (sin al menos dos no queda train).
    """
    labels = _as_labels(groups, "groups")
    uniques, group_of_row = _factorize(labels, "groups")
    if uniques.size < 2:
        raise ValueError(f"groups: se necesitan al menos 2 grupos distintos (hay {uniques.size})")

    splits: dict[Any, Split] = {}
    for position, label in enumerate(uniques):
        in_test = group_of_row == position
        key = label.item() if isinstance(label, np.generic) else label
        splits[key] = Split(np.flatnonzero(~in_test), np.flatnonzero(in_test))
    return splits
