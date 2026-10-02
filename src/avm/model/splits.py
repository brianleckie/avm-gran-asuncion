"""Esquemas de split del AVM (F8.2): K-fold por cluster y leave-group-out.

Todas las funciones devuelven solo índices (`Split`: arrays de posiciones de fila) y no tocan los
datos: reciben únicamente los ids de cluster o de grupo. Así sirven igual para un DataFrame, un
array o cualquier estructura indexable por posición.

Regla de cero leakage (principio 4 del ROADMAP): ningún cluster (o grupo) aparece a la vez en
train y en test. Un mismo inmueble publicado en varios portales forma un cluster (F5.3); si sus
copias quedaran repartidas entre train y test, el modelo "vería" en entrenamiento el aviso que
después se evalúa y las métricas saldrían infladas.

Los splits son reproducibles: no hay azar sin semilla explícita. Los índices de cada array salen
ordenados de menor a mayor.
"""

from __future__ import annotations

import math
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
    return value is None or (isinstance(value, float) and math.isnan(value))


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
# Leave-group-out
# --------------------------------------------------------------------------------------------


def leave_group_out(groups: ArrayLike) -> dict[Any, Split]:
    """Un split por grupo, dejándolo entero afuera del train (esquema (c) de F8.2).

    Pensado para leave-barrio-out: mide cuánto generaliza el modelo a un barrio que no vio. Para
    cada grupo, el test son sus filas y el train son todas las demás. Devuelve un diccionario
    ordenado por grupo ascendente (las claves son valores de Python, no escalares de numpy).

    Con barrios de pocas observaciones la métrica de cada split es ruidosa (F7.2): conviene
    mirar la distribución entre grupos y no solo el promedio.

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
