"""El diccionario de datos commiteado tiene que coincidir con los schemas (F1.6)."""

from gen_data_dictionary import OUTPUT, render


def test_data_dictionary_is_up_to_date() -> None:
    assert OUTPUT.read_text(encoding="utf-8") == render(), (
        "docs/data_dictionary.md está desactualizado: correr "
        "`uv run python scripts/gen_data_dictionary.py`"
    )


def test_dictionary_documents_every_field_and_the_fixed_label() -> None:
    text = render()
    for field in ("source_id", "price_currency", "geo_precision", "p_low", "label"):
        assert f"`{field}`" in text
    assert "fijo: `precio de oferta estimado`" in text
    assert "`ciudad`" in text  # nivel nuevo de GeoPrecision
