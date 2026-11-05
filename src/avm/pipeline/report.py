"""`quality_report.md` (F4.7): solo agregados, nunca texto de avisos.

Cada número sale de una corrida de `avm.pipeline.build`. Los únicos textos que no son números ni
nombres de reglas o columnas son los parámetros que el usuario pasó (la fuente de la cotización) y
las notas fijas de limitaciones de más abajo.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from avm.contract import City, NeighborhoodMatch, PropertyType, StreetSurface
from avm.pipeline.build import (
    EXACT_DUPLICATE,
    INVALID_RAW,
    NO_CITY,
    NO_TYPE,
    Pipeline,
    funnel_rules,
)
from avm.pipeline.clean import AREA_TOLERANCE
from avm.pipeline.dedup import PRICE_TOLERANCE
from avm.pipeline.neighborhood import FUZZY_THRESHOLD, Reason
from avm.pipeline.outliers import (
    MAX_BUILT_M2,
    MAX_USD_PER_M2,
    MIN_BUILT_M2,
    MIN_USD_PER_M2,
)

AMENITIES = ("has_pool", "has_quincho", "is_new", "in_gated_community", "has_elevator")
TYPES = (*(kind.value for kind in PropertyType), NO_TYPE)
CITIES = (*(city.value for city in City), NO_CITY)
MATCH_METHODS = (
    NeighborhoodMatch.EXACT,
    NeighborhoodMatch.ALIAS,
    NeighborhoodMatch.FUZZY,
    NeighborhoodMatch.UNMATCHED,
)
UNMATCHED_REASONS = (
    Reason.NO_ZONE,
    Reason.SAME_AS_CITY,
    Reason.NO_GAZETTEER,
    Reason.NO_MATCH,
    Reason.AMBIGUOUS,
)

LIMITATIONS = (
    "Precio de oferta publicado: no es un precio de transacción.",
    "Una sola cotización (casa de cambios) para todos los snapshots: los avisos en guaraníes del "
    "snapshot más viejo se convierten con la cotización de la fecha indicada arriba (ADR-004, "
    "sección «Desvío por plazo»). Los avisos en dólares no se ven afectados.",
    "Una superficie sin tipo (`kind=None`) NO se acepta como construida (decisión por plazo): "
    "los departamentos son los más afectados.",
    "Sin gazetteer (`--gazetteer none`) ningún aviso tiene barrio: `geo_precision=ciudad` para "
    "todos.",
    "`garages` queda vacío salvo que el snapshot traiga `garages_raw`: el parser no lo extrae.",
    "Las coordenadas no se usan (geo a nivel barrio, ADR-003).",
    "Los tags de superficie de los snapshots anteriores a F3.4 se leen de `attributes_raw`; su "
    "`content_hash` es el del parser viejo.",
    "Los rangos de outliers son supuestos a priori del equipo, no datos de mercado, y no se "
    "recalibraron mirando la distribución.",
    "Con `--gazetteer none` los clusters se arman sin barrio: pueden agrupar de más (lado seguro "
    "para leakage). El redondeo del m² a entero puede partir un par en el borde.",
)


def pct(part: int, whole: int) -> str:
    return "—" if whole == 0 else f"{100 * part / whole:.1f} %".replace(".", ",")


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return [*lines, ""]


def _funnel(result: Pipeline) -> list[str]:
    read = sum(result.read.values())
    remaining = read
    rows: list[list[object]] = [["líneas leídas", read, "", read]]
    steps = [
        (INVALID_RAW, result.invalid_raw),
        (EXACT_DUPLICATE, result.exact_collapsed),
        *((rule, result.discards.get(rule, 0)) for rule in funnel_rules()),
    ]
    for name, dropped in steps:
        rows.append([name, remaining, dropped, remaining - dropped])
        remaining -= dropped
    rows.append(["**filas en dataset.csv**", "", "", len(result.rows)])
    return _table(["regla (en orden)", "entran", "descartados", "salen"], rows)


def _target(result: Pipeline) -> list[str]:
    out_type = Counter(row.listing.property_type.value for row in result.rows)
    out_city = Counter(row.listing.city.value for row in result.rows)
    out_both = Counter(
        (row.listing.property_type.value, row.listing.city.value) for row in result.rows
    )
    in_type: Counter[str] = Counter()
    in_city: Counter[str] = Counter()
    for (kind, city), n in result.scope_in.items():
        in_type[kind] += n
        in_city[city] += n

    def rows(
        keys: Iterable[str], inside: Counter[str], outside: Counter[str]
    ) -> list[list[object]]:
        data = [[k, inside[k], outside[k], pct(outside[k], inside[k])] for k in keys if inside[k]]
        total_in, total_out = sum(inside.values()), sum(outside.values())
        return [*data, ["total", total_in, total_out, pct(total_out, total_in)]]

    head = ["", "avisos únicos de entrada", "en dataset", "% con target"]
    both = [
        [kind, city, n_in, out_both[(kind, city)], pct(out_both[(kind, city)], n_in)]
        for kind in TYPES
        for city in CITIES
        if (n_in := result.scope_in[(kind, city)])
    ]
    return [
        "Target disponible = el aviso llega a `dataset.csv` (precio válido y en dólares o "
        "guaraníes, m² construidos identificados, sin outliers). Denominador: avisos únicos "
        "(después de colapsar duplicados exactos).",
        "",
        *_table(["tipo", *head[1:]], rows(TYPES, in_type, out_type)),
        *_table(["ciudad", *head[1:]], rows(CITIES, in_city, out_city)),
        *_table(["tipo", "ciudad", *head[1:]], both),
    ]


def _neighborhood(result: Pipeline) -> list[str]:
    rows: list[list[object]] = []
    for city in (*(c.value for c in City), "total"):
        group = [r for r in result.rows if city == "total" or r.listing.city.value == city]
        if not group:
            continue
        methods = Counter(r.listing.neighborhood_match for r in group)
        reasons = Counter(r.neighborhood_reason for r in group)
        matched = sum(methods[m] for m in MATCH_METHODS[:3])
        rows.append(
            [
                city,
                len(group),
                *(methods[m] for m in MATCH_METHODS),
                pct(matched, len(group)),
                *(reasons[reason] for reason in UNMATCHED_REASONS),
            ]
        )
    header = [
        "ciudad",
        "filas",
        *(m.value for m in MATCH_METHODS),
        "% con barrio",
        *(f"sin_match: {reason.value}" for reason in UNMATCHED_REASONS),
    ]
    return _table(header, rows)


def _clusters(result: Pipeline) -> list[str]:
    sizes = Counter(result.clusters[k] for k in result.clusters)
    by_size = Counter(sizes.values())
    in_multi = sum(size * n for size, n in by_size.items() if size > 1)
    rows = [[size, by_size[size]] for size in sorted(by_size) if size <= 4]
    rows.append(["5 o más", sum(n for size, n in by_size.items() if size >= 5)])
    return [
        f"Filas: {len(result.rows)}. Clusters: {len(sizes)}. Tamaño máximo: "
        f"{max(sizes.values(), default=0)}. Filas en clusters de más de una fila: {in_multi} "
        f"({pct(in_multi, len(result.rows))}).",
        "",
        *_table(["tamaño del cluster", "clusters"], rows),
    ]


def _features(result: Pipeline) -> list[str]:
    rows = result.rows
    total = len(rows)
    lines: list[str] = []
    by_source = Counter(r.built_area_source for r in rows)
    multi = sum(1 for r in rows if r.text_built_values > 1)
    lines += _table(
        ["m² construidos", "filas", "%"],
        [[s, by_source[s], pct(by_source[s], total)] for s in ("tag", "texto")],
    )
    lines += [
        f"Filas cuyo texto trae más de un valor distinto de m² construidos (se toma el primero; "
        f"informativo): {multi}.",
        "",
    ]
    amenity_rows = []
    for name in AMENITIES:
        values = Counter(getattr(r.listing, name) for r in rows)
        origins = Counter(r.amenity_origins[name] for r in rows)
        amenity_rows.append(
            [name, values[True], values[False], values[None], origins["tag"], origins["regex"]]
        )
    lines += _table(
        ["amenity", "1", "0", "vacío (no mencionado)", "valor desde tag", "valor desde regex"],
        amenity_rows,
    )
    surfaces = Counter(r.listing.street_surface for r in rows)
    lines += _table(
        ["street_surface", "filas"],
        [[s.value, surfaces[s]] for s in StreetSurface] + [["vacío", surfaces[None]]],
    )
    counts = []
    for name in ("bedrooms", "bathrooms", "garages"):
        filled = sum(1 for r in rows if getattr(r.listing, name) is not None)
        counts.append([name, filled, total - filled, pct(total - filled, total)])
    lines += _table(["campo", "con dato", "vacío", "% vacío"], counts)
    empty_garages = sum(1 for r in rows if r.listing.garages is None)
    if rows and empty_garages == total:
        lines += [
            f"**`garages` queda vacío en el 100 % de las filas ({empty_garages} de {total})**: "
            "el parser no extrae cocheras, así que no sirve como feature.",
            "",
        ]
    return lines


def _contract_details(result: Pipeline) -> list[str]:
    if not result.contract_details:
        return []
    rows = [[detail, n] for detail, n in sorted(result.contract_details.items())]
    return [
        "Avisos rechazados por el contrato, por `campo:tipo` (un aviso cuenta en cada uno; nunca "
        "con el valor):",
        "",
        *_table(["campo:tipo", "avisos"], rows),
    ]


def render_report(result: Pipeline, *, contract_version: str) -> str:
    """El reporte completo, en Markdown. Solo números, nombres de reglas y parámetros."""
    params = result.params
    gazetteer = params.gazetteer.name if params.gazetteer else "none"
    max_built = ", ".join(f"{kind.value} {value}" for kind, value in MAX_BUILT_M2.items())
    lines = [
        "# Reporte de calidad del dataset",
        "",
        "Generado por `avm.pipeline.build`. **Solo agregados**: ningún texto de avisos. Los "
        "precios son precios de oferta publicados, no de transacción.",
        "",
        "## 0. Parámetros",
        "",
        f"- Contrato: v{contract_version}. Fuente: clasipar.",
        "- Snapshots: "
        + ", ".join(f"{d.isoformat()} ({result.read[d]} líneas)" for d in params.snapshots),
        f"- Cotización: {params.fx.rate_pyg_per_usd} PYG por USD, fecha "
        f"{params.fx.date.isoformat()}, fuente: {params.fx.source}",
        f"- Gazetteer: {gazetteer}. Umbral fuzzy: {FUZZY_THRESHOLD:g}.",
        f"- Tolerancia tag vs. texto en m² construidos: {AREA_TOLERANCE * 100:g} %. "
        f"Tolerancia de precio para casi-duplicados: {PRICE_TOLERANCE * 100:g} %.",
        f"- Outliers a priori: m² construidos entre {MIN_BUILT_M2} y (máx. por tipo: {max_built}); "
        f"USD/m² entre {MIN_USD_PER_M2} y {MAX_USD_PER_M2} (todos los tipos).",
        "",
        "## 1. Embudo de descartes",
        "",
        *_funnel(result),
        *_contract_details(result),
        "## 2. Target disponible por tipo y ciudad",
        "",
        *_target(result),
        "## 3. Barrio por ciudad (filas del dataset)",
        "",
        *_neighborhood(result),
        "## 4. Clusters (F5)",
        "",
        *_clusters(result),
        "## 5. Origen de los datos",
        "",
        *_features(result),
        "## 6. Limitaciones",
        "",
        *(f"- {note}" for note in LIMITATIONS),
        "",
    ]
    return "\n".join(lines)
