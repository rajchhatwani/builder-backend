"""SENTINEL M3: the platform export keeps plain numbers numeric and still defuses formulas."""

from app.services.import_service import _safe


def test_numbers_untouched_text_neutralised() -> None:
    assert _safe("-12.50") == "-12.50"
    assert _safe("3") == "3"
    assert _safe("=1+1") != "=1+1"
    assert _safe("-1+1") != "-1+1"
    assert _safe("@SUM(A1)") != "@SUM(A1)"
