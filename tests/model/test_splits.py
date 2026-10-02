"""Tests de los esquemas de split (F8.2): grouped_kfold, leave_group_out y temporal_holdout.

Las funciones devuelven solo índices y no tocan los datos. Lo central que se verifica es la regla de
cero leakage: ningún cluster (o grupo) aparece a la vez en train y en test.
"""

import collections
import datetime

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from avm.model.splits import Split, grouped_kfold, leave_group_out, temporal_holdout

# --------------------------------------------------------------------------------------------
# grouped_kfold
#
# Ejemplo calculado a mano: ids = [A, A, B, C, C, C, D] (filas 0..6), n_splits = 2.
#   Tamaños de cluster: A = 2 (filas 0, 1), B = 1 (fila 2), C = 3 (filas 3, 4, 5), D = 1 (fila 6).
#   Reparto goloso, de mayor a menor tamaño, cada cluster al fold con menos filas (empate: el de
#   menor índice):
#     C (3) → fold 0            tamaños [3, 0]
#     A (2) → fold 1            tamaños [3, 2]
#     un cluster de 1 → fold 1  tamaños [3, 3]
#     el otro de 1 → fold 0     tamaños [4, 3]
#   Cuál de B y D entra primero depende de la semilla, pero el resultado cumple siempre:
#     test del fold 0 = {3, 4, 5} más una fila de {2, 6}  (4 filas)
#     test del fold 1 = {0, 1} más la otra fila de {2, 6}  (3 filas)
# --------------------------------------------------------------------------------------------
IDS = ["A", "A", "B", "C", "C", "C", "D"]


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 42])
def test_grouped_kfold_hand_computed(seed):
    fold0, fold1 = grouped_kfold(IDS, n_splits=2, seed=seed)
    assert {3, 4, 5} <= set(fold0.test)
    assert {0, 1} <= set(fold1.test)
    assert (len(fold0.test), len(fold1.test)) == (4, 3)
    assert set(fold0.test) | set(fold1.test) == set(range(7))
    assert set(fold0.train) == set(fold1.test)
    assert set(fold1.train) == set(fold0.test)


def test_split_is_a_named_tuple_of_sorted_intp_arrays():
    splits = grouped_kfold(IDS, n_splits=2, seed=0)
    assert all(isinstance(split, Split) for split in splits)
    train, test = splits[0]
    assert train is splits[0].train and test is splits[0].test
    for array in (train, test):
        assert array.dtype == np.intp
        assert np.all(np.diff(array) > 0)


def test_grouped_kfold_is_reproducible_and_the_seed_matters():
    ids = np.repeat(
        np.arange(12), 3
    )  # 12 clusters del mismo tamaño: el reparto depende de la semilla

    def folds(seed):
        return [tuple(split.test) for split in grouped_kfold(ids, n_splits=4, seed=seed)]

    assert folds(7) == folds(7)
    assert len({tuple(folds(seed)) for seed in range(8)}) > 1


def test_grouped_kfold_does_not_modify_its_input():
    ids = np.array(IDS)
    before = ids.copy()
    grouped_kfold(ids, n_splits=2, seed=0)
    assert np.array_equal(ids, before)


@pytest.mark.parametrize(
    "ids",
    [
        pytest.param([3, 3, 1, 1, 2, 2], id="enteros"),
        pytest.param(["x", "x", "y", "y", "z", "z"], id="strings"),
        pytest.param(np.array(["x", "x", "y", "y", "z", "z"], dtype=object), id="object"),
        pytest.param((1.5, 1.5, 2.5, 2.5, 4.0, 4.0), id="floats en tupla"),
    ],
)
def test_grouped_kfold_accepts_any_comparable_labels(ids):
    for train, test in grouped_kfold(ids, n_splits=3, seed=0):
        assert len(test) == 2 and len(train) == 4


# (ids, n_splits, seed, patrón del mensaje)
INVALID_KFOLD = [
    pytest.param(IDS, 1, 0, "n_splits.*>= 2", id="n_splits 1"),
    pytest.param(IDS, 0, 0, "n_splits.*>= 2", id="n_splits 0"),
    pytest.param(IDS, 5, 0, "n_splits.*cantidad de clusters", id="más folds que clusters"),
    pytest.param(["A", "A"], 2, 0, "n_splits.*cantidad de clusters", id="un solo cluster"),
    pytest.param(IDS, 2.0, 0, "n_splits.*entero", id="n_splits float"),
    pytest.param(IDS, "2", 0, "n_splits.*entero", id="n_splits texto"),
    pytest.param(IDS, True, 0, "n_splits.*entero", id="n_splits bool"),
    pytest.param(IDS, 2, None, "seed.*obligatoria", id="sin semilla"),
    pytest.param(IDS, 2, "0", "seed.*entero", id="semilla texto"),
    pytest.param(IDS, 2, -1, "seed", id="semilla negativa"),
    pytest.param([], 2, 0, "cluster_ids.*vacío", id="ids vacíos"),
    pytest.param([["A"], ["B"]], 2, 0, "cluster_ids.*1-D", id="ids 2-D"),
    pytest.param([1.0, np.nan, 2.0], 2, 0, "cluster_ids.*NaN", id="NaN en ids"),
    pytest.param(np.array(["A", None, "B"], dtype=object), 2, 0, "cluster_ids.*None", id="None"),
    pytest.param(np.array(["A", 1, "B"], dtype=object), 2, 0, "comparables", id="tipos mezclados"),
]


@pytest.mark.parametrize(("ids", "n_splits", "seed", "message"), INVALID_KFOLD)
def test_grouped_kfold_rejects_invalid_arguments(ids, n_splits, seed, message):
    with pytest.raises(ValueError, match=message):
        grouped_kfold(ids, n_splits=n_splits, seed=seed)


# --------------------------------------------------------------------------------------------
# leave_group_out
#
# Ejemplo calculado a mano: groups = [x, y, x, z, y] (filas 0..4). Grupos en orden ascendente:
#   x → test = filas {0, 2}, train = {1, 3, 4}
#   y → test = filas {1, 4}, train = {0, 2, 3}
#   z → test = fila  {3},    train = {0, 1, 2, 4}
# --------------------------------------------------------------------------------------------
GROUPS = ["x", "y", "x", "z", "y"]


def test_leave_group_out_hand_computed():
    splits = leave_group_out(GROUPS)
    assert list(splits) == ["x", "y", "z"]
    expected = {
        "x": ([1, 3, 4], [0, 2]),
        "y": ([0, 2, 3], [1, 4]),
        "z": ([0, 1, 2, 4], [3]),
    }
    for group, (train, test) in expected.items():
        assert splits[group].train.tolist() == train
        assert splits[group].test.tolist() == test


def test_leave_group_out_keys_are_plain_python_values_in_ascending_order():
    splits = leave_group_out(np.array([30, 10, 20, 10]))
    assert list(splits) == [10, 20, 30]
    assert all(type(key) is int for key in splits)


def test_leave_group_out_works_with_object_labels():
    splits = leave_group_out(np.array(["San Lorenzo", "Luque", "Luque"], dtype=object))
    assert list(splits) == ["Luque", "San Lorenzo"]
    assert splits["Luque"].test.tolist() == [1, 2]


INVALID_GROUPS = [
    pytest.param(["x", "x", "x"], "al menos 2 grupos", id="un solo grupo"),
    pytest.param([], "groups.*vacío", id="vacío"),
    pytest.param([["x"], ["y"]], "groups.*1-D", id="2-D"),
    pytest.param([1.0, np.nan], "groups.*NaN", id="NaN"),
    pytest.param(np.array(["x", None], dtype=object), "groups.*None", id="None"),
    pytest.param(np.array(["x", 1], dtype=object), "comparables", id="tipos mezclados"),
]


@pytest.mark.parametrize(("groups", "message"), INVALID_GROUPS)
def test_leave_group_out_rejects_invalid_groups(groups, message):
    with pytest.raises(ValueError, match=message):
        leave_group_out(groups)


# --------------------------------------------------------------------------------------------
# Property tests (hypothesis): cero leakage por grupo
# --------------------------------------------------------------------------------------------


@st.composite
def clustered_rows(draw):
    """Ids de cluster (enteros chicos, con repetidos) con al menos 2 clusters distintos."""
    ids = draw(st.lists(st.integers(min_value=0, max_value=9), min_size=2, max_size=60))
    assume(len(set(ids)) >= 2)
    return np.array(ids)


@st.composite
def kfold_cases(draw):
    ids = draw(clustered_rows())
    n_splits = draw(st.integers(min_value=2, max_value=len(set(ids.tolist()))))
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    return ids, n_splits, seed


@settings(max_examples=200)
@given(case=kfold_cases())
def test_grouped_kfold_never_shares_a_cluster_between_train_and_test(case):
    ids, n_splits, seed = case
    splits = grouped_kfold(ids, n_splits=n_splits, seed=seed)
    assert len(splits) == n_splits
    everything = np.arange(len(ids))
    for train, test in splits:
        assert len(train) > 0
        assert len(test) > 0
        assert set(ids[train].tolist()).isdisjoint(ids[test].tolist())
        assert np.array_equal(np.sort(np.concatenate([train, test])), everything)


@settings(max_examples=200)
@given(case=kfold_cases())
def test_grouped_kfold_tests_partition_all_rows_and_keep_folds_balanced(case):
    ids, n_splits, seed = case
    splits = grouped_kfold(ids, n_splits=n_splits, seed=seed)
    all_test = np.concatenate([split.test for split in splits])
    assert np.array_equal(np.sort(all_test), np.arange(len(ids)))  # cada fila es test una vez
    sizes = [len(split.test) for split in splits]
    largest_cluster = max(collections.Counter(ids.tolist()).values())
    assert max(sizes) - min(sizes) <= largest_cluster


@given(case=kfold_cases())
def test_grouped_kfold_is_deterministic_for_a_given_seed(case):
    ids, n_splits, seed = case
    first = grouped_kfold(ids, n_splits=n_splits, seed=seed)
    second = grouped_kfold(ids, n_splits=n_splits, seed=seed)
    assert all(
        np.array_equal(a.train, b.train) and np.array_equal(a.test, b.test)
        for a, b in zip(first, second, strict=True)
    )


@given(groups=clustered_rows())
def test_leave_group_out_holds_each_group_out_exactly_once(groups):
    splits = leave_group_out(groups)
    assert set(splits) == set(groups.tolist())
    everything = np.arange(len(groups))
    seen_in_test = []
    for group, (train, test) in splits.items():
        assert set(groups[test].tolist()) == {group}
        assert group not in set(groups[train].tolist())
        assert np.array_equal(np.sort(np.concatenate([train, test])), everything)
        seen_in_test.extend(test.tolist())
    assert sorted(seen_in_test) == everything.tolist()


# --------------------------------------------------------------------------------------------
# temporal_holdout
#
# Ejemplo calculado a mano (filas 0..4, un snapshot por día), corte = 2026-01-03:
#   fechas  = [01-01, 01-02, 01-03, 01-04, 01-05]
#   train   = fechas estrictamente anteriores al corte = filas {0, 1}
#   test    = fechas >= corte (el snapshot del corte es test) = filas {2, 3, 4}
#
# Con cluster_ids = [a, b, a, c, d]:
#   clusters en train = {a (fila 0), b (fila 1)}
#   candidatas a test = {2 (a), 3 (c), 4 (d)}; la fila 2 es del cluster a, que ya está en train
#   → se EXCLUYE DEL TEST la fila 2. El train no se toca.
#   train = {0, 1} (igual que sin cluster_ids),  test = {3, 4},  excluidas = 3 − 2 = 1 (fila 2)
# --------------------------------------------------------------------------------------------
DATES = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
CUTOFF = "2026-01-03"
CLUSTERS = ["a", "b", "a", "c", "d"]


def test_temporal_holdout_hand_computed_without_cluster_ids():
    train, test = temporal_holdout(DATES, CUTOFF)
    assert train.tolist() == [0, 1]
    assert test.tolist() == [2, 3, 4]


def test_temporal_holdout_hand_computed_excludes_seen_clusters_from_test_only():
    split = temporal_holdout(DATES, CUTOFF, cluster_ids=CLUSTERS)
    assert isinstance(split, Split)
    assert split.train.tolist() == [0, 1]  # el train no pierde nada
    assert split.test.tolist() == [3, 4]  # la fila 2 (cluster "a", ya visto) sale del test
    excluded = {2, 3, 4} - set(split.test.tolist())
    assert excluded == {2}
    assert excluded.isdisjoint(split.train.tolist())  # queda fuera de ambos conjuntos


def test_a_date_equal_to_the_cutoff_belongs_to_test():
    train, test = temporal_holdout(["2026-01-02", "2026-01-03"], "2026-01-03")
    assert train.tolist() == [0]
    assert test.tolist() == [1]


def test_rows_do_not_need_to_be_sorted_by_date():
    # fechas = [03, 01, 05, 02], corte 03 → train: filas 1 (01) y 3 (02); test: 0 (03) y 2 (05)
    dates = ["2026-01-03", "2026-01-01", "2026-01-05", "2026-01-02"]
    train, test = temporal_holdout(dates, "2026-01-03")
    assert train.tolist() == [1, 3]
    assert test.tolist() == [0, 2]


def test_a_cluster_seen_only_in_the_future_is_not_excluded():
    # El cluster "c" aparece dos veces, ambas en el test: no hay historial que lo haya "visto".
    dates = ["2026-01-01", "2026-01-04", "2026-01-05"]
    split = temporal_holdout(dates, "2026-01-03", cluster_ids=["a", "c", "c"])
    assert split.train.tolist() == [0]
    assert split.test.tolist() == [1, 2]


def test_temporal_holdout_accepts_dates_in_several_formats():
    expected = ([0, 1], [2, 3, 4])
    as_datetime64 = np.array(DATES, dtype="datetime64[D]")
    as_python_dates = [datetime.date.fromisoformat(value) for value in DATES]
    as_datetimes = [datetime.datetime.fromisoformat(value + "T08:30:00") for value in DATES]
    for dates in (DATES, as_datetime64, as_python_dates, as_datetimes, np.array(DATES)):
        for cutoff in (
            CUTOFF,
            datetime.date(2026, 1, 3),
            datetime.datetime(2026, 1, 3, 0, 0),
            np.datetime64("2026-01-03"),
            np.datetime64("2026-01-03T00:00:00"),
        ):
            train, test = temporal_holdout(dates, cutoff)
            assert (train.tolist(), test.tolist()) == expected


def test_temporal_holdout_does_not_modify_its_input():
    dates = np.array(DATES, dtype="datetime64[D]")
    clusters = np.array(CLUSTERS)
    dates_before, clusters_before = dates.copy(), clusters.copy()
    temporal_holdout(dates, CUTOFF, cluster_ids=clusters)
    assert np.array_equal(dates, dates_before)
    assert np.array_equal(clusters, clusters_before)


def test_without_cluster_ids_train_and_test_partition_all_rows():
    train, test = temporal_holdout(DATES, CUTOFF)
    assert sorted(train.tolist() + test.tolist()) == list(range(len(DATES)))


# (fechas, corte, cluster_ids, patrón del mensaje)
INVALID_TEMPORAL = [
    pytest.param(DATES, "2026-01-01", None, "train vacío", id="ninguna fecha anterior al corte"),
    pytest.param(DATES, "2026-01-06", None, "test vacío", id="ninguna fecha desde el corte"),
    pytest.param(
        ["2026-01-01", "2026-01-02", "2026-01-03"],
        "2026-01-03",
        ["a", "b", "a"],
        "test vacío.*clusters",
        id="todo el test ya fue visto en train",
    ),
    pytest.param(DATES, CUTOFF, ["a", "b"], "cluster_ids.*mismo largo", id="ids de otro largo"),
    pytest.param(DATES, CUTOFF, ["a", None, "b", "c", "d"], "cluster_ids.*None", id="None en ids"),
    pytest.param(
        DATES, CUTOFF, np.array([1.0, np.nan, 2, 3, 4]), "cluster_ids.*NaN", id="NaN en ids"
    ),
    pytest.param([], CUTOFF, None, "snapshot_dates.*vacío", id="sin fechas"),
    pytest.param([DATES], CUTOFF, None, "snapshot_dates.*1-D", id="fechas 2-D"),
    pytest.param(["2026-01-01", "NaT", "2026-01-05"], CUTOFF, None, "NaT", id="NaT en fechas"),
    pytest.param([1, 2, 3], CUTOFF, None, "fechas, no números", id="fechas numéricas"),
    pytest.param([1.5, 2.5], CUTOFF, None, "fechas, no números", id="fechas float"),
    pytest.param(["hoy", "ayer"], CUTOFF, None, "snapshot_dates.*fechas", id="texto no fecha"),
    pytest.param(DATES, "no-es-fecha", None, "cutoff.*fecha", id="corte inválido"),
    pytest.param(DATES, 20260103, None, "cutoff.*número", id="corte numérico"),
    pytest.param(DATES, "NaT", None, "cutoff.*NaT", id="corte NaT"),
]


@pytest.mark.parametrize(("dates", "cutoff", "clusters", "message"), INVALID_TEMPORAL)
def test_temporal_holdout_rejects_invalid_arguments(dates, cutoff, clusters, message):
    with pytest.raises(ValueError, match=message):
        temporal_holdout(dates, cutoff, cluster_ids=clusters)


# --------------------------------------------------------------------------------------------
# Property tests (hypothesis): el temporal respeta el tiempo y, con cluster_ids, no hay leakage
# --------------------------------------------------------------------------------------------

JANUARY = st.dates(min_value=datetime.date(2026, 1, 1), max_value=datetime.date(2026, 1, 31))


@st.composite
def dated_rows(draw):
    """Filas con fecha de snapshot y cluster, más un corte (todo dentro de enero de 2026)."""
    rows = draw(
        st.lists(st.tuples(JANUARY, st.integers(min_value=0, max_value=5)), min_size=1, max_size=40)
    )
    dates = np.array([row[0] for row in rows], dtype="datetime64[D]")
    clusters = np.array([row[1] for row in rows])
    cutoff = draw(JANUARY)
    return dates, clusters, np.datetime64(cutoff, "D")


@settings(max_examples=300)
@given(case=dated_rows())
def test_temporal_holdout_train_is_strictly_before_test(case):
    dates, _, cutoff = case
    before = np.flatnonzero(dates < cutoff)
    from_cutoff = np.flatnonzero(dates >= cutoff)
    if before.size == 0 or from_cutoff.size == 0:
        with pytest.raises(ValueError, match="vacío"):
            temporal_holdout(dates, cutoff)
        return
    train, test = temporal_holdout(dates, cutoff)
    assert np.array_equal(train, before)
    assert np.array_equal(test, from_cutoff)
    assert dates[train].max() < dates[test].min()  # toda fecha de train es anterior a toda de test
    assert np.array_equal(np.sort(np.concatenate([train, test])), np.arange(len(dates)))


@settings(max_examples=300)
@given(case=dated_rows())
def test_with_cluster_ids_no_cluster_is_in_both_sides_and_train_loses_nothing(case):
    dates, clusters, cutoff = case
    before = np.flatnonzero(dates < cutoff)
    seen_clusters = set(clusters[before].tolist())
    expected_test = [
        i for i in np.flatnonzero(dates >= cutoff).tolist() if clusters[i] not in seen_clusters
    ]
    if before.size == 0 or not expected_test:
        with pytest.raises(ValueError, match="vacío"):
            temporal_holdout(dates, cutoff, cluster_ids=clusters)
        return

    split = temporal_holdout(dates, cutoff, cluster_ids=clusters)

    # 1. La intersección de clusters entre train y test es vacía.
    assert set(clusters[split.train].tolist()).isdisjoint(clusters[split.test].tolist())
    # 2. El train no pierde registros: son exactamente las filas con fecha anterior al corte.
    assert np.array_equal(split.train, before)
    assert len(split.train) == int((dates < cutoff).sum())
    # 3. El test son las filas desde el corte cuyo cluster no está en train, y nada más.
    assert split.test.tolist() == expected_test
    # 4. El tiempo se respeta igual que sin cluster_ids.
    assert dates[split.train].max() < dates[split.test].min()
    # 5. Lo excluido sale solo del test y queda fuera de ambos conjuntos.
    excluded = set(np.flatnonzero(dates >= cutoff).tolist()) - set(split.test.tolist())
    assert all(clusters[i] in seen_clusters for i in excluded)
    assert excluded.isdisjoint(split.train.tolist())
