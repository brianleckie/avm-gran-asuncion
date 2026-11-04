"""Reporte del piloto (F3.3): números sobre datos sintéticos, patrones y privacidad.

Todo el contenido de los avisos es INVENTADO (nombres, calles y teléfonos de mentira). Los valores
esperados están calculados a mano a partir de cada caso, no de correr el script.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pilot_report as report
import pytest

from avm.contract import RawListing

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
SENTINEL = "ZXQJNOMBRE"  # una palabra que no existe: si aparece en el reporte, se filtró texto
PAGE = "https://clasipar.paraguay.com/inmuebles/casas/aviso-"


def listing(source_id: str, **fields: Any) -> RawListing:
    return RawListing(
        source="clasipar",
        source_id=source_id,
        url=f"{PAGE}{source_id}",
        scraped_at=NOW,
        content_hash="a" * 64,
        **fields,
    )


def manifest_for(
    items: list[tuple[str, str, str, tuple[int, ...]]], *, population: int = 1000
) -> dict[str, Any]:
    """Manifest con un target por (tipo, ciudad) y los avisos (id, tipo, ciudad, páginas)."""
    targets: dict[tuple[str, str], dict[str, Any]] = {}
    for source_id, ptype, city, pages in items:
        target = targets.setdefault(
            (ptype, city),
            {
                "property_type": ptype,
                "city": city,
                "url": "u",
                "total_results": population,
                "last_page": 40,
                "random_page": 7,
                "pool_size": 50,
                "excluded_duplicates": 0,
                "short": False,
                "errors": [],
                "attempted": 0,
                "valid": 0,
                "sampled": [],
            },
        )
        target["sampled"].append(
            {"source_id": source_id, "pages": list(pages), "patrocinado": False}
        )
    return {
        "source": "clasipar",
        "snapshot_date": "2026-10-06",
        "started_at": "2026-10-06T14:09:24+00:00",
        "finished_at": "2026-10-06T14:39:24+00:00",
        "seed": 42,
        "budget": 260,
        "per_target": 19,
        "stopped": None,
        "stop_reason": None,
        "requests": {"used": 5, "remaining": 255, "counts": {}},
        "details": {
            "planned": len(items),
            "attempted": len(items),
            "not_attempted": 0,
            "valid": len(items),
            "rejected": 0,
            "rejected_by_error": {},
            "fetch_errors": {},
        },
        "targets": list(targets.values()),
        "contract_version": "0.1.1",
    }


def request_log() -> list[dict[str, Any]]:
    def entry(url: str, status: int | None, result: str, duration: float | None) -> dict[str, Any]:
        return {
            "url": url,
            "status": status,
            "ts": "2026-10-06T14:09:24+00:00",
            "bytes": 1,
            "result": result,
            "duration_s": duration,
        }

    base = "https://clasipar.paraguay.com"
    return [
        entry(f"{base}/robots.txt", 200, "ok", 0.5),
        entry(f"{base}/inmuebles/casas/intencion:vendo-t_s/localidad:asuncion-3", 200, "ok", 1.0),
        entry(f"{base}/inmuebles/casas/aviso-1", 200, "ok", 0.25),
        entry(f"{base}/inmuebles/casas/aviso-2", 404, "error", 0.75),
        entry(f"{base}/inmuebles/casas/aviso-1", None, "cache", None),
    ]


# ------------------------------------------------------------------------- superficie


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Casa de 120 m2 construidos", [("120", "construida")]),
        ("120 m² construidos sobre terreno de 360 m²", [("120", "construida"), ("360", "terreno")]),
        # Limitación conocida de parse_area (F4.3): con las etiquetas en la misma línea, la del
        # SIGUIENTE número queda más cerca por detrás del primero y gana ("Construcción" para 180).
        ("Terreno: 180 m² Construcción: 90 m²", [("180", "construida"), ("90", "construida")]),
        # ... y la ventana tampoco se corta en el salto de línea.
        ("Terreno: 180 m²\nConstrucción: 90 m²", [("180", "construida"), ("90", "construida")]),
        ("Lote de 12x30 mts", [("360", "terreno")]),
        ("Departamento de 68 m2", [("68", None)]),
        ("Dos plantas, 85 mts2 y 1.200 m2", [("85", None), ("1200", None)]),
        ("Entre 120 - 150 m2", []),
        ("0 m2 no es una superficie", []),
        ("Sin superficie, 3 dormitorios", []),
        ("", []),
    ],
)
def test_find_areas_returns_every_surface_with_its_kind(
    text: str, expected: list[tuple[str, str | None]]
) -> None:
    found = report.find_areas(text, "descripcion")
    assert [(str(item.area.m2), item.area.kind) for item in found] == expected


@pytest.mark.parametrize(
    ("text", "pattern"),
    [
        ("Departamento de 68 m2", "departamento de N m2"),
        ("90 mts2 de terreno", "N mts2 de terreno"),
        ("superficie 1.200 m²", "superficie N m²"),
        ("12 x 30 mts", "N x N mts"),
        # Nombres, calles y barrios (inventados) se reemplazan por W: el patrón no los lleva.
        (f"Vendo casa de {SENTINEL} Gómez de 90 mts2 en Villa Elisa", "W de N mts2 en W"),
    ],
)
def test_the_format_pattern_replaces_numbers_and_unknown_words(text: str, pattern: str) -> None:
    (found,) = report.find_areas(text, "titulo")
    assert found.pattern == pattern


def test_a_pattern_never_contains_a_word_outside_the_vocabulary() -> None:
    texts = [
        f"{SENTINEL} Rojas 45 m2 Calle Mariscal López {SENTINEL} 12x30 Sra. Pérez",
        f"Contactar con el Arq. {SENTINEL} 120 mts2 cubiertos Luque Centro",
    ]
    allowed = report.VOCABULARY | {"W"}
    for text in texts:
        for found in report.find_areas(text, "descripcion"):
            expression = re.sub(r"N|\s", "", found.pattern)  # lo que no es una palabra de contexto
            context = [
                word
                for word in re.findall(r"[^\W\d_]+", found.pattern)
                if word not in {"m", "mt", "mts", "x"} and word in allowed or word == "W"
            ]
            assert SENTINEL.casefold() not in found.pattern.casefold()
            assert all(word in allowed for word in context), found.pattern
            assert expression  # el patrón conserva la unidad de la expresión


def test_the_fragmenting_agrees_with_parse_area_on_the_first_surface() -> None:
    rows = report.build_rows(
        [
            listing("1", title_raw="Casa 120 m2 construidos", description_raw="terreno 360 m2"),
            listing("2", title_raw="Departamento 68 m2", description_raw=None),
            listing(
                "3", title_raw="Sin datos", description_raw="Entre 120 - 150 m2 y 80 m2 cubiertos"
            ),
        ],
        manifest_for(
            [
                ("1", "casa", "luque", (1,)),
                ("2", "departamento", "luque", (1,)),
                ("3", "casa", "luque", (1,)),
            ]
        ),
    )
    checked, mismatched, extra = report.consistency(rows)
    # Textos con contenido: 1 (título y descripción), 2 (título) y 3 (título y descripción) = 5.
    # En el 3, parse_area sobre el texto completo da None (rechaza el rango y no sigue) pero el
    # fragmento "80 m2 cubiertos" sí da una superficie: es el único caso "extra".
    assert (checked, mismatched, extra) == (5, 0, 1)


def test_structured_tags_add_built_area_only_as_a_measure() -> None:
    manifest = manifest_for(
        [
            ("1", "departamento", "luque", (1,)),
            ("2", "departamento", "luque", (1,)),
            ("3", "casa", "luque", (1,)),
        ]
    )
    items = [
        # solo el tag estructurado trae los m² construidos
        listing("1", price_raw="US$. 100.000", attributes_raw={"Superficie construida": "68"}),
        # el texto y el tag los traen y NO coinciden (70 contra 68)
        listing(
            "2",
            price_raw="US$. 100.000",
            title_raw="70 m2 construidos",
            attributes_raw={"Superficie construida": "68", "Superficie de terreno m2": "200"},
        ),
        # un tag con un valor que no es un número no cuenta
        listing(
            "3", price_raw="US$. 100.000", attributes_raw={"Superficie construida": "sin dato"}
        ),
    ]
    rows = report.build_rows(items, manifest)
    assert [r.tag_built for r in rows] == [Decimal(68), Decimal(68), None]
    assert rows[1].tag_land == Decimal(200) and rows[0].tag_land is None
    # El target "oficial" sigue siendo solo texto; el tag es una medida aparte.
    assert [r.available() for r in rows] == [False, True, False]
    assert [r.available(with_tag=True) for r in rows] == [True, True, False]
    text = report.render(manifest, items, request_log(), None, None)
    both = "| departamento (n=2) | 2/2 (100,0 %) | 1/2 (50,0 %) | 2/2 (100,0 %) | 2/2 (100,0 %) |"
    assert both in text  # con el tag; solo texto; texto o tag; ídem con la regla de deptos
    assert (
        "Avisos con el tag y con m² construidos en el texto: 1; en 1 los valores no coinciden."
        in text
    )
    assert "| departamento (n=2) | 2/2 (100,0 %) | 1/2 (50,0 %) | 2/2 (100,0 %) |" in text
    assert "| casa (n=1) | 0/1 (0,0 %) | 0/1 (0,0 %) | 0/1 (0,0 %) |" in text


def test_the_line_by_line_measure_shows_when_the_next_label_wins() -> None:
    manifest = manifest_for([("1", "casa", "luque", (1,))])
    item = listing("1", description_raw="Terreno: 180 m²\nConstrucción: 90 m²")
    (row,) = report.build_rows([item], manifest)
    assert [(str(f.area.m2), f.area.kind) for f in row.areas] == [
        ("180", "construida"),
        ("90", "construida"),
    ]
    assert [(str(f.area.m2), f.area.kind) for f in row.line_areas] == [
        ("180", "terreno"),
        ("90", "construida"),
    ]
    text = report.render(manifest, [item], request_log(), None, None)
    assert "| casa (n=1) | 1/1 (100,0 %) | 1/1 (100,0 %) | 1 |" in text


# ------------------------------------------------------------------------- formato


def test_percentage_and_percentile_helpers() -> None:
    assert report.pct(1, 3) == "33,3 %" and report.pct(0, 0) == "n/d"
    assert report.frac(2, 8) == "2/8 (25,0 %)"
    values = [float(n) for n in range(1, 21)]
    assert report.percentile(values, 0.5) == 10.0 and report.percentile(values, 0.95) == 19.0
    assert report.percentile([4.0], 0.95) == 4.0
    assert report.seconds(0.5) == "0,50 s" and report.minutes(90) == "1,5 min"
    assert report.table(["a", "b"], [[1, 2]])[:3] == ["| a | b |", "|---|---|", "| 1 | 2 |"]


# ------------------------------------------------------------------------- el reporte


def sample() -> tuple[dict[str, Any], list[RawListing]]:
    listings = [
        # casa en Asunción, página 1: USD y construida identificada -> disponible
        listing(
            "1",
            title_raw="Casa en venta",
            price_raw="US$. 150.000,00",
            city_raw="Asunción",
            description_raw=(
                f"120 m2 construidos. Terreno de 360 m2. Consultar con Sr. Lopez {SENTINEL} "
                "[TELEFONO] [URL]"
            ),
            neighborhood_raw="Villa Morra",
            latitude_raw="-25.30",
            longitude_raw="-57.60",
        ),
        # casa en Asunción, de la aleatoria: "Consultar" y una superficie sin tipo
        listing(
            "2",
            title_raw="Casa 200 m2",
            price_raw="Consultar precio.",
            city_raw="Asunción",
            neighborhood_raw="Asunción",
            attributes_raw={"patrocinado": "si"},
            latitude_raw="-25.30",
            longitude_raw="-57.60",
        ),
        # departamento en Luque, de ambas páginas: PYG y superficie sin tipo
        listing(
            "3",
            title_raw="Departamento de 68 m2",
            price_raw="Gs. 500.000.000",
            city_raw="Luque",
            neighborhood_raw="Luque",
        ),
        # departamento en Luque: sin precio parseable ni superficie
        listing("4", title_raw="Departamento", price_raw="A convenir", city_raw="Luque"),
        # dúplex en San Lorenzo: precio "desde" y superficie construida
        listing(
            "5",
            title_raw="Duplex",
            price_raw="Desde US$. 90.000",
            city_raw="San Lorenzo",
            description_raw="Hablar con la Sra. Gómez. 85 m2 cubiertos",
            neighborhood_raw="Centro",
            latitude_raw="-25.40",
            longitude_raw=None,
        ),
    ]
    items = [
        ("1", "casa", "asuncion", (1,)),
        ("2", "casa", "asuncion", (7,)),
        ("3", "departamento", "luque", (1, 7)),
        ("4", "departamento", "luque", (7,)),
        ("5", "duplex", "san_lorenzo", (1,)),
    ]
    return manifest_for(items, population=500), listings


def render(html_dir: Path | None = None, conclusion: str | None = None) -> str:
    manifest, listings = sample()
    return report.render(manifest, listings, request_log(), html_dir, conclusion)


def test_the_report_never_reproduces_text_from_the_listings() -> None:
    text = render()
    for forbidden in (SENTINEL, "Lopez", "Gómez", "Villa Morra", "Casa en venta"):
        assert forbidden not in text
    assert "Hablar con la" not in text
    # Tampoco las frases que CLAUDE.md prohíbe en cualquier documento.
    assert "valor de mercado" not in text.casefold() and "precio real" not in text.casefold()
    assert "precios de oferta" in text


def test_the_report_has_the_eleven_sections_in_order() -> None:
    headings = re.findall(r"^## (\d+)\. ", render(), re.M)
    assert headings == [str(n) for n in range(1, 12)]


def test_execution_section_numbers() -> None:
    text = render()
    assert "Duración total: 30,0 min" in text
    # El log tiene 5 líneas pero solo 4 se enviaron: la quinta es una respuesta de caché.
    assert "(robots.txt y reintentos incluidos): 4 de un presupuesto de 260;" in text
    assert "además 1 respuestas de caché y 0 pedidos prohibidos por robots.txt" in text
    assert "Por resultado: cache 1, error 1, ok 3." in text
    assert "Por status HTTP: 200 3, 404 1." in text
    # latencias de los requests enviados: listados 1,0; detalles 0,25 y 0,75; robots 0,5
    assert "| listados | 1 | 1,00 s | 1,00 s | 1,00 s | 1,00 s |" in text
    assert "| detalles | 2 | 0,50 s | 0,25 s | 0,75 s | 0,75 s |" in text
    assert "| todas | 4 | 0,62 s | 0,50 s | 1,00 s | 1,00 s |" in text
    assert "**Válidos: 5/5 (100,0 %)**" in text


def test_a_cut_run_is_reported_as_such() -> None:
    manifest, listings = sample()
    manifest.update(stopped="blocked", stop_reason="HTTP 429 en una URL", finished_at=None)
    manifest["details"].update(
        rejected=2,
        rejected_by_error={"ValidationError:x@title_raw": 2},
        fetch_errors={"http_404": 1},
    )
    text = report.render(manifest, listings, request_log(), None, None)
    assert "**La corrida se cortó** (`blocked`): HTTP 429 en una URL." in text
    assert "`ValidationError:x@title_raw` 2" in text and "`http_404` 1" in text


def test_sample_section_counts_origins_and_sponsored() -> None:
    text = render()
    assert "- Total de avisos válidos: 5. De la página 1: 2; de la página aleatoria: 2; " in text
    assert "presentes en ambas: 1; sin plan: 0." in text
    assert "- Patrocinados (D5): 1/5 (20,0 %)." in text
    assert "| casa | Asunción | 500 | 40 | 7 | 50 | 2 | 1 | 1 | 0 | 1 |" in text


def test_a_manifest_of_the_pilot_still_reads_random_page_and_says_one_page() -> None:
    text = render()  # el manifest del piloto no trae `pages_per_target` ni `random_pages`
    assert "`--source clasipar --budget 260 --per-target 19 --seed 42`" in text
    assert "la página 1 más UNA página aleatoria en [2, última]" in text
    assert "cerca de la mitad del pool" in text


def test_a_manifest_with_several_random_pages_per_search_is_reported() -> None:
    manifest, listings = sample()
    manifest["pages_per_target"] = 30
    for target in manifest["targets"]:
        del target["random_page"]
        target["random_pages"] = [3, 7, 9]
    text = report.render(manifest, listings, request_log(), None, None)
    assert "--budget 260 --pages-per-target 30 --per-target 19" in text
    assert "la página 1 más hasta 29 páginas aleatorias, sin reposición, en [2, última]" in text
    assert "| casa | Asunción | 500 | 40 | 3 págs. | 50 | 2 | 1 | 1 | 0 | 1 |" in text
    assert "cerca de la mitad" not in text  # esa fracción solo se midió con el diseño del piloto


def test_two_pages_per_search_in_the_new_manifest_reads_as_the_pilot_design() -> None:
    manifest, listings = sample()
    manifest["pages_per_target"] = 2
    for target in manifest["targets"]:
        target["random_pages"] = [target.pop("random_page")]
    text = report.render(manifest, listings, request_log(), None, None)
    assert "--budget 260 --pages-per-target 2 --per-target 19" in text
    assert "la página 1 más UNA página aleatoria en [2, última]" in text
    assert "| casa | Asunción | 500 | 40 | 7 | 50 | 2 | 1 | 1 | 0 | 1 |" in text


def test_price_section_classifies_every_listing() -> None:
    text = render()
    # 5 avisos: parseables el 1, 3 y 5 (USD, PYG y USD "desde"); "Consultar" el 2; el 4 no parsea
    assert "| Total (n=5) | 3/5 (60,0 %) | 2 | 1 | 0 | 1 | 1 | 0 | 1 |" in text


def test_a_zero_price_is_its_own_class() -> None:
    manifest = manifest_for([("1", "casa", "luque", (1,)), ("2", "casa", "luque", (1,))])
    items = [listing("1", price_raw="Gs. 0"), listing("2", price_raw="Gs. 10")]
    rows = report.build_rows(items, manifest)
    assert [report._price_class(r) for r in rows] == ["monto cero", "parseable"]
    text = report.render(manifest, items, request_log(), None, None)
    assert "| casa (n=2) | 1/2 (50,0 %) | 0 | 1 | 0 | 0 | 0 | 1 | 0 |" in text


def test_area_section_by_type() -> None:
    text = render()
    # casas (1 y 2): con superficie 2; construida 1; terreno 1; ambas 1; solo None 1 (el 2)
    casas = (
        "| casa (n=2) | 2/2 (100,0 %) | 1/2 (50,0 %) | 1/2 (50,0 %) | 1/2 (50,0 %) | 1/2 (50,0 %)"
    )
    assert casas in text
    # departamentos (3 y 4): solo el 3 tiene superficie, sin tipo
    deptos = "| departamento (n=2) | 1/2 (50,0 %) | 0/2 (0,0 %) | 0/2 (0,0 %) | 0/2 (0,0 %) | 1/2"
    assert deptos in text
    # patrones de los kind=None (el 2: "Casa 200 m2" -> "casa N m2"; el 3: "departamento de N m2")
    assert "| 1 | `casa N m2` | 1 |" in text and "| 2 | `departamento de N m2` | 1 |" in text
    # y solo la expresión, sin contexto: las dos son "N m2"
    assert "| 1 | `N m2` | 2 |" in text
    # dos superficies distintas: solo el 1 (construida + terreno)
    assert "**Avisos con dos o más superficies distintas:** 1/5 (20,0 %)" in text
    assert "| construida + terreno | 1 |" in text


def test_target_section_strict_and_alternative_rule() -> None:
    text = render()
    # disponibles (precio con moneda + construida): el 1 y el 5. El 3 solo con la regla alternativa.
    assert "| casa (n=2) | 1/2 (50,0 %) | 1/2 (50,0 %) | 1/2 (50,0 %) | — |" in text
    assert (
        "| departamento (n=2) | 1/2 (50,0 %) | 0/2 (0,0 %) | 0/2 (0,0 %) | 1/2 (50,0 %) |" in text
    )
    assert "| dúplex (n=1) | 1/1 (100,0 %) | 1/1 (100,0 %) | 1/1 (100,0 %) | — |" in text
    total = "| Total (n=5) | 3/5 (60,0 %) | 2/5 (40,0 %) | 2/5 (40,0 %) | 3/5 (60,0 %) (regla solo"
    assert total in text
    assert 'De los 2 con target disponible, 1 tienen precio "desde" o rango' in text
    assert "| Luque (n=2) | 1/2 (50,0 %) | 0/2 (0,0 %) | 0/2 (0,0 %) | 1/2 (50,0 %) |" in text


def test_target_section_by_origin_and_projection() -> None:
    text = render()
    assert "| página 1 | 2 | 2/2 (100,0 %) |" in text  # avisos 1 y 5, ambos disponibles
    assert "| aleatoria | 2 | 0/2 (0,0 %) |" in text  # avisos 2 y 4
    # Proyección por búsqueda (población 500): casa-Asunción 1 de 2 -> 250; dúplex 1 de 1 -> 500;
    # departamento-Luque 0 de 2 -> 0. Σ = 750 sobre 1500 declarados.
    assert "| casa | Asunción | 500 | 2 | 1 | 50,0 % | 250 |" in text
    assert "| dúplex | San Lorenzo | 500 | 1 | 1 | 100,0 % | 500 |" in text
    assert "Σ resultados declarados por el portal: 1500." in text
    assert "**750**" in text


def test_projection_numbers_and_the_stratified_deviation() -> None:
    items = [(str(n), "casa", "luque", (1,)) for n in range(10)]
    manifest = manifest_for(items, population=1000)
    listings = [
        listing(
            str(n),
            price_raw="US$. 100.000,00",
            title_raw="120 m2 construidos" if n < 5 else "Casa",
        )
        for n in range(10)
    ]
    rows = report.build_rows(listings, manifest)
    data, total, estimate, deviation, skipped = report.projection(manifest, rows)
    assert (total, estimate, skipped) == (1000.0, 500.0, 0)
    # varianza estratificada: N² p (1 - p) / n = 1000² · 0,25 / 10 = 25.000
    assert deviation == pytest.approx(25_000**0.5)
    assert data[0][-1] == "500"


def test_a_target_without_valid_listings_is_skipped_in_the_projection() -> None:
    manifest = manifest_for([("1", "casa", "luque", (1,))])
    manifest["targets"].append(
        {**manifest["targets"][0], "city": "asuncion", "sampled": [], "total_results": None}
    )
    manifest["targets"].append(
        {**manifest["targets"][0], "city": "san_lorenzo", "sampled": [], "total_results": 300}
    )
    rows = report.build_rows(
        [listing("1", price_raw="US$. 1", title_raw="10 m2 construidos")], manifest
    )
    data, total, estimate, _, skipped = report.projection(manifest, rows)
    assert skipped == 2 and total == 1000.0 and estimate == 1000.0
    assert data[-1][-1] == "n/d" and data[-2][-1] == "n/d"


def test_neighborhood_section_counts_the_city_as_neighborhood() -> None:
    text = render()
    # con "Zona": 1, 2, 3 y 5; igual a la ciudad: 2 (Asunción) y 3 (Luque)
    assert "| Total (n=5) | 4/5 (80,0 %) | 2/4 (50,0 %) |" in text


def test_coordinates_section_counts_shared_pairs() -> None:
    text = render()
    assert "| Total (n=5) | 2/5 (40,0 %) | 1 |" in text  # el 1 y el 2; el 5 solo trae la latitud
    assert "1 pares, que cubren 2 avisos de 2 con coordenadas." in text


def test_privacy_section_only_counts() -> None:
    text = render()
    assert "**2/5 (40,0 %)**" in text  # descripciones del 1 y del 5
    assert "| Sr. | 1 |" in text and "| Sra. | 1 |" in text
    assert "| consultar con | 1 |" in text and "| hablar con | 1 |" in text
    assert "| Lic. | 0 |" in text and "| Arq. | 0 |" in text


def test_completeness_by_type() -> None:
    text = render()
    assert "| Campo | casa (n=2) | departamento (n=2) | dúplex (n=1) | Total (n=5) |" in text
    assert "| `price_raw` | 100,0 % | 100,0 % | 100,0 % | 100,0 % |" in text
    assert "| `description_raw` | 50,0 % | 0,0 % | 100,0 % | 40,0 % |" in text
    assert "| `attributes_raw` | 50,0 % | 0,0 % | 0,0 % | 20,0 % |" in text


# ------------------------------------------------------------------------- punto 7 (X3)


def write_page(directory: Path, url: str, body: str) -> None:
    name = hashlib.sha256(url.encode("utf-8")).hexdigest()
    (directory / f"{name}.html").write_text(f"<html><body>{body}</body></html>", encoding="utf-8")


def test_structured_area_labels_are_found_by_location_without_values(tmp_path: Path) -> None:
    manifest, listings = sample()
    write_page(
        tmp_path, f"{PAGE}1", '<span class="ads_tag">Superficie: <strong>999</strong></span>'
    )
    write_page(
        tmp_path,
        f"{PAGE}2",
        '<div class="anuncio-detalles"><div class="grid__item"><span>Terreno:</span>'
        "<h6>888</h6></div></div>",
    )
    write_page(
        tmp_path,
        f"{PAGE}3",
        '<script type="application/ld+json">{"@type": "House", "floorSize": "777"}</script>',
    )
    write_page(tmp_path, f"{PAGE}4", '<span class="ads_tag">Quincho: <strong>SI</strong></span>')
    text = report.render(manifest, listings, request_log(), tmp_path, None)
    assert "Se revisó la caché sanitizada de 4 detalles" in text
    assert "| tags (`span.ads_tag`) | 1/4 (25,0 %) |" in text
    assert "| ficha (`.anuncio-detalles`) | 1/4 (25,0 %) |" in text
    assert "| JSON-LD | 1/4 (25,0 %) |" in text
    assert "| tags (`span.ads_tag`): Superficie | 1 |" in text
    assert "999" not in text and "888" not in text and "777" not in text  # nunca los valores


def test_no_structured_area_is_reported_as_none(tmp_path: Path) -> None:
    manifest, listings = sample()
    write_page(tmp_path, f"{PAGE}1", '<span class="ads_tag">Quincho: <strong>SI</strong></span>')
    text = report.render(manifest, listings, request_log(), tmp_path, None)
    assert "**Ningún detalle trae la superficie como campo estructurado**" in text


def test_missing_html_cache_is_said_not_assumed() -> None:
    assert "la caché de HTML sanitizada no está disponible" in render(html_dir=None)


# ------------------------------------------------------------------------- archivos y CLI


def populate(root: Path, date: str = "2026-10-06") -> None:
    manifest, listings = sample()
    interim = root / "data" / "interim" / date / "clasipar"
    raw = root / "data" / "raw" / date / "clasipar"
    interim.mkdir(parents=True)
    raw.mkdir(parents=True)
    (interim / "crawl_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (interim / "raw_listings.jsonl").write_text(
        "\n".join(item.model_dump_json() for item in listings) + "\n", encoding="utf-8"
    )
    (raw / "requests.jsonl").write_text(
        "\n".join(json.dumps(entry) for entry in request_log()) + "\n", encoding="utf-8"
    )


def test_main_writes_docs_pilot_for_the_latest_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    populate(tmp_path, "2026-10-05")
    populate(tmp_path, "2026-10-06")
    assert report.main(["--root", str(tmp_path)]) == 0
    output = tmp_path / "docs" / "pilot" / "2026-10-06.md"
    assert output.is_file() and not (tmp_path / "docs" / "pilot" / "2026-10-05.md").exists()
    assert "2026-10-06.md" in capsys.readouterr().out
    assert output.read_text("utf-8").startswith("# Piloto de Clasipar (F3.3)")


def test_main_with_an_explicit_date(tmp_path: Path) -> None:
    populate(tmp_path, "2026-10-05")
    populate(tmp_path, "2026-10-06")
    report.main(["--root", str(tmp_path), "--date", "2026-10-05"])
    assert (tmp_path / "docs" / "pilot" / "2026-10-05.md").is_file()


def test_main_without_any_snapshot_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="correr el crawler"):
        report.main(["--root", str(tmp_path)])


def test_the_conclusion_written_by_hand_survives_regeneration(tmp_path: Path) -> None:
    populate(tmp_path)
    output = tmp_path / "docs" / "pilot" / "2026-10-06.md"
    report.build(tmp_path, "2026-10-06")
    assert report.CONCLUSION_PLACEHOLDER.strip() in output.read_text("utf-8")  # primera vez
    handwritten = f"{report.CONCLUSION_HEADING}\n\nEscrita a mano con los números reales.\n"
    output.write_text(
        output.read_text("utf-8").replace(report.CONCLUSION_PLACEHOLDER, handwritten),
        encoding="utf-8",
    )
    report.build(tmp_path, "2026-10-06")
    final = output.read_text("utf-8")
    assert final.endswith(handwritten) and report.CONCLUSION_PLACEHOLDER.strip() not in final
    assert final.count(report.CONCLUSION_HEADING) == 1


def test_an_existing_report_without_conclusion_gets_the_placeholder(tmp_path: Path) -> None:
    populate(tmp_path)
    output = tmp_path / "docs" / "pilot" / "2026-10-06.md"
    output.parent.mkdir(parents=True)
    output.write_text("# viejo sin conclusión\n", encoding="utf-8")
    report.build(tmp_path, "2026-10-06")
    assert report.CONCLUSION_PLACEHOLDER.strip() in output.read_text("utf-8")
