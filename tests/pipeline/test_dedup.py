"""Deduplicación exacta y casi-duplicados (F5.1, F5.3). Avisos sintéticos."""

from datetime import UTC, date, datetime

from avm.contract import City
from avm.pipeline.dedup import assign_clusters, collapse_exact, listing_key
from avm.pipeline.neighborhood import Gazetteer, _CityIndex
from tests.pipeline.helpers import make_raw, make_row

EARLY = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
LATE = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def cluster_of(clusters: dict[str, str], source_id: str) -> str:
    return clusters[listing_key("clasipar", source_id)]


# ------------------------------------------------------------------------------------ exactos


def test_the_same_source_id_in_two_snapshots_keeps_the_most_recent_scrape() -> None:
    old = (date(2026, 10, 6), make_raw("1", price="US$. 100.000", scraped_at=EARLY))
    new = (date(2026, 11, 4), make_raw("1", price="US$. 90.000", scraped_at=LATE))
    kept, collapsed = collapse_exact([new, old])  # el orden de entrada no importa
    assert collapsed == 1
    assert [(snapshot, raw.price_raw) for snapshot, raw in kept] == [
        (date(2026, 11, 4), "US$. 90.000")
    ]


def test_a_tie_in_scraped_at_keeps_the_later_snapshot() -> None:
    first = (date(2026, 10, 6), make_raw("1", price="US$. 100.000", scraped_at=LATE))
    second = (date(2026, 11, 4), make_raw("1", price="US$. 90.000", scraped_at=LATE))
    kept, _ = collapse_exact([second, first])
    assert kept[0][0] == date(2026, 11, 4)


def test_different_source_ids_are_not_collapsed() -> None:
    items = [(date(2026, 11, 4), make_raw(str(n))) for n in range(3)]
    kept, collapsed = collapse_exact(items)
    assert (len(kept), collapsed) == (3, 0)


def test_the_same_id_repeated_inside_one_snapshot_counts_as_collapsed() -> None:
    item = (date(2026, 11, 4), make_raw("7"))
    kept, collapsed = collapse_exact([item, item, item])
    assert (len(kept), collapsed) == (1, 2)


# ------------------------------------------------------------------------------------ clusters


def test_prices_within_1_percent_in_the_same_block_share_a_cluster() -> None:
    rows = [
        make_row("1", price="US$. 100.000", built_tag="120"),
        make_row("2", price="US$. 100.900", built_tag="120.4"),  # 0,9 % y redondea a 120
    ]
    clusters = assign_clusters(rows)
    assert cluster_of(clusters, "1") == cluster_of(clusters, "2")


def test_the_1_percent_limit_is_inclusive_and_beyond_it_they_split() -> None:
    at_limit = assign_clusters(
        [
            make_row("1", price="US$. 100.000", built_tag="120"),
            make_row("2", price="US$. 101.000", built_tag="120"),
        ]
    )
    assert cluster_of(at_limit, "1") == cluster_of(at_limit, "2")
    beyond = assign_clusters(
        [
            make_row("1", price="US$. 100.000", built_tag="120"),
            make_row("2", price="US$. 101.001", built_tag="120"),
        ]
    )
    assert cluster_of(beyond, "1") != cluster_of(beyond, "2")


def test_a_chain_of_neighbours_within_1_percent_is_one_cluster() -> None:
    rows = [
        make_row("1", price="US$. 100.000", built_tag="120"),
        make_row("2", price="US$. 100.900", built_tag="120"),
        make_row("3", price="US$. 101.800", built_tag="120"),  # 1,8 % del primero
    ]
    clusters = assign_clusters(rows)
    assert len({cluster_of(clusters, n) for n in "123"}) == 1


def test_a_different_type_city_or_rounded_area_is_another_cluster() -> None:
    base = {"price": "US$. 100.000", "built_tag": "120"}
    rows = [
        make_row("1", **base),
        make_row("2", property_type="departamentos", **base),
        make_row("3", city="San Lorenzo", **base),
        make_row("4", price="US$. 100.000", built_tag="121"),
    ]
    clusters = assign_clusters(rows)
    assert len({cluster_of(clusters, n) for n in "1234"}) == 4


def test_the_area_is_rounded_half_up_to_an_integer() -> None:
    rows = [
        make_row("1", price="US$. 100.000", built_tag="120.4"),  # -> 120
        make_row("2", price="US$. 100.000", built_tag="120.5"),  # -> 121
        make_row("3", price="US$. 100.000", built_tag="120.6"),  # -> 121
    ]
    clusters = assign_clusters(rows)
    assert cluster_of(clusters, "1") != cluster_of(clusters, "2")
    assert cluster_of(clusters, "2") == cluster_of(clusters, "3")


def test_two_matched_barrios_do_not_share_a_cluster_but_without_a_gazetteer_they_do() -> None:
    index = _CityIndex(canonical={"uno": "Uno", "dos": "Dos"})
    gazetteer = Gazetteer({City.LUQUE: index})
    base = {"price": "US$. 100.000", "built_tag": "120"}
    with_barrios = assign_clusters(
        [
            make_row("1", gazetteer=gazetteer, zone="Uno", **base),
            make_row("2", gazetteer=gazetteer, zone="Dos", **base),
        ]
    )
    assert cluster_of(with_barrios, "1") != cluster_of(with_barrios, "2")
    without = assign_clusters(
        [make_row("1", zone="Uno", **base), make_row("2", zone="Dos", **base)]
    )
    assert cluster_of(without, "1") == cluster_of(without, "2")  # agrupa de más: lado seguro


def test_the_cluster_id_is_deterministic_and_comes_from_the_smallest_key() -> None:
    rows = [
        make_row("30", price="US$. 100.500", built_tag="120"),
        make_row("2", price="US$. 100.000", built_tag="120"),
    ]
    forward = assign_clusters(rows)
    backward = assign_clusters(list(reversed(rows)))
    assert forward == backward
    assert cluster_of(forward, "2") == "c-clasipar-2"  # "clasipar:2" < "clasipar:30" como texto


def test_every_row_gets_a_cluster_and_singletons_are_their_own() -> None:
    rows = [make_row(str(n), price=f"US$. {100 + n * 50}.000", built_tag="120") for n in range(4)]
    clusters = assign_clusters(rows)
    assert len(clusters) == 4 and len(set(clusters.values())) == 4
    assert assign_clusters([]) == {}
