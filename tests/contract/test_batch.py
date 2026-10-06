"""Validación por lotes (F1.7)."""

from datetime import UTC, datetime

from avm.contract import PredictionRequest, RawListing
from avm.contract.batch import validate_records


def test_batch_separates_valid_and_invalid_records() -> None:
    records = [
        {"city": "asuncion", "property_type": "casa", "built_area_m2": 120},
        {"city": "lambare", "property_type": "casa", "built_area_m2": 120},
        {"city": "luque", "property_type": "departamento", "built_area_m2": -5},
    ]
    result = validate_records(PredictionRequest, records)
    assert [r.city for r in result.valid] == ["asuncion"]
    assert [e.index for e in result.errors] == [1, 2]
    assert result.errors[0].messages[0].startswith("city:")


def test_batch_errors_do_not_echo_personal_data() -> None:
    record = {
        "source": "sintetico",
        "source_id": "1",
        "url": "https://ejemplo.invalid/1",
        "scraped_at": datetime(2026, 10, 6, tzinfo=UTC),
        "content_hash": "c" * 64,
        "description_raw": "Llamar al 0981 555 777",
    }
    result = validate_records(RawListing, [record])
    assert result.valid == []
    text = " ".join(result.errors[0].messages)
    assert "datos personales" in text and "555" not in text
    assert text.startswith("<modelo>:")
