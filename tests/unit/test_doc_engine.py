"""The PDF engine: placeholders, escaping, money, totals, limits, determinism, and the library."""

import base64
import io
import json
import zlib
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.core import doc_engine as eng
from app.core import doc_library as lib


def text_of(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def one(*blocks: dict) -> dict:  # noqa: ANN401
    return {"blocks": list(blocks)}


def paragraph(text: str) -> dict:
    return {"type": "paragraph", "text": text}


# -- resolver ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "data", "expected"),
    [
        ("{{a}}", {"a": "x"}, "x"),
        ("{{ a.b.c }}", {"a": {"b": {"c": 5}}}, "5"),
        ("{{items.1.n}}", {"items": [{"n": "a"}, {"n": "b"}]}, "b"),
        ("{{missing}}", {}, ""),
        ("{{items.9}}", {"items": []}, ""),
        ("{{a | upper}}-{{a | lower}}", {"a": "Ab"}, "AB-ab"),
        ("{{a | default:none}}", {}, "none"),
        ("{{a | default:none}}", {"a": ""}, "none"),
        ("{{n | number}}", {"n": "1234.5"}, "1,234.50"),
        ("{{d | date}}", {"d": "2026-10-24"}, "2026-10-24"),
        ("{{d | date:%d %B %Y}}", {"d": "2026-10-24T10:00:00Z"}, "24 October 2026"),
        ("{{m | money:EUR}}", {"m": "1234.567"}, "1,234.57 EUR"),
        ("{{m | money:@cur}}", {"m": 5, "cur": "usd"}, "5.00 USD"),
        ("{{m | money:JPY}}", {"m": "1234.5"}, "1,235 JPY"),
        ("{{m | money:KWD}}", {"m": "1.2345"}, "1.235 KWD"),
        ("{{ not a placeholder }}", {}, "{{ not a placeholder }}"),
    ],
)
def test_resolver(text: str, data: dict, expected: str) -> None:
    assert eng.resolve(text, data) == expected


def test_a_placeholder_cannot_reach_attributes_or_call_anything() -> None:
    class Secret:
        hidden = "boom"

    data = {"obj": Secret(), "text": "abc"}
    for hostile in ("{{obj.hidden}}", "{{text.upper}}", "{{text.__class__}}", "{{__import__}}"):
        assert eng.resolve(hostile, data) == ""
    # only plain dict / list lookups exist; there is no way to evaluate an expression
    assert eng.resolve("{{1+1}}", {}) == "{{1+1}}"
    with pytest.raises(eng.DocumentError):
        eng.resolve("{{a | system:ls}}", {"a": 1})  # only the listed formatters exist


def test_unknown_formatters_and_bad_values_are_errors_not_crashes() -> None:
    with pytest.raises(eng.DocumentError):
        eng.resolve("{{a | shout}}", {"a": 1})
    with pytest.raises(eng.DocumentError):
        eng.resolve("{{a | money:EUR}}", {"a": "lots"})
    with pytest.raises(eng.DocumentError):
        eng.resolve("{{a | money:EUR}}", {"a": True})
    with pytest.raises(eng.DocumentError):
        eng.resolve("{{d | date:%Q}}", {"d": "2026-01-01"})
    with pytest.raises(eng.DocumentError):
        eng.resolve("{{d | date}}", {"d": "yesterday"})
    with pytest.raises(eng.DocumentError):
        eng.resolve("x" * (eng.MAX_TEXT + 1), {})


def test_money_rounds_half_up_to_the_minor_unit() -> None:
    assert eng.format_money("0.005", "EUR") == "0.01 EUR"
    assert eng.format_money("2.675", "EUR") == "2.68 EUR"  # a float would give 2.67
    assert eng.format_money(Decimal("-1.005"), "EUR") == "-1.01 EUR"
    assert eng.format_money(3, None) == "3.00"
    for bad in (float("nan"), float("inf"), "NaN", "1e999999"):
        with pytest.raises(eng.DocumentError):
            eng.format_money(bad, "EUR")


# -- totals -----------------------------------------------------------------------------------


def test_totals_are_computed_per_rate_with_exact_decimals() -> None:
    data = {
        "currency": "EUR",
        "items": [
            {"quantity": 3, "unit_price": "9.99", "tax_rate": 20},
            {"quantity": 1, "unit_price": "100", "tax_rate": 20, "discount": "10"},
            {"quantity": 2, "unit_price": "5.50", "tax_rate": 5},
        ],
    }
    result = eng.compute_totals(data)["totals"]
    assert result["subtotal"] == "130.97"  # 29.97 + 90.00 + 11.00
    # 20% of 119.97 = 23.994 -> 23.99, plus 5% of 11.00 = 0.55
    assert result["tax_total"] == "24.54"
    assert result["total"] == str(Decimal(result["subtotal"]) + Decimal(result["tax_total"]))
    assert [b["rate"] for b in result["tax_breakdown"]] == ["5", "20"]


def test_totals_ignore_what_the_caller_sent_and_never_change_the_input() -> None:
    data = {
        "currency": "EUR",
        "items": [{"quantity": 1, "unit_price": "10"}],
        "totals": {"total": "1"},
    }
    before = json.dumps(data)
    assert eng.compute_totals(data)["totals"]["total"] == "10.00"
    assert json.dumps(data) == before


@pytest.mark.parametrize(
    "item",
    [
        {"quantity": -1, "unit_price": 1},
        {"quantity": 1, "unit_price": -1},
        {"quantity": 1, "unit_price": 1, "discount": -1},
        {"quantity": 1, "unit_price": 1, "tax_rate": 101},
        {"quantity": "many", "unit_price": 1},
        "not an object",
    ],
)
def test_bad_line_items_are_refused(item: object) -> None:
    with pytest.raises(eng.DocumentError):
        eng.compute_totals({"items": [item]})


def test_zero_decimal_currencies_round_to_whole_units() -> None:
    data = {"currency": "JPY", "items": [{"quantity": 3, "unit_price": "333.5", "tax_rate": 10}]}
    totals = eng.compute_totals(data)["totals"]
    assert (
        totals["subtotal"] == "1001" and totals["tax_total"] == "100" and totals["total"] == "1101"
    )


# -- template validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "fragment"),
    [
        ({}, "blocks"),
        ({"blocks": []}, "blocks"),
        ({"blocks": [{"type": "script"}]}, "type"),
        ({"blocks": [paragraph("x")], "page": {"size": "A0"}}, "page.size"),
        ({"blocks": [paragraph("x")], "page": {"margin_mm": 1}}, "margin"),
        ({"blocks": [paragraph("x")], "page": {"orientation": "sideways"}}, "orientation"),
        ({"blocks": [{"type": "heading", "text": "x", "level": 9}]}, "level"),
        ({"blocks": [paragraph("{{a | nope}}")]}, "formatter"),
        ({"blocks": [paragraph("x" * (eng.MAX_TEXT + 1))]}, "longer"),
        (
            {
                "blocks": [
                    {"type": "table", "source": "a b", "columns": [{"header": "h", "value": "v"}]}
                ]
            },
            "source",
        ),
        ({"blocks": [{"type": "table", "source": "items", "columns": []}]}, "columns"),
        ({"blocks": [{"type": "kv", "rows": []}]}, "rows"),
        ({"blocks": [{"type": "spacer", "height_mm": 500}]}, "height"),
        ({"blocks": [{"type": "image", "data_base64": "!!!"}]}, "base64"),
        (
            {
                "blocks": [
                    {"type": "image", "data_base64": base64.b64encode(b"GIF89a....").decode()}
                ]
            },
            "PNG or JPEG",
        ),
        ({"blocks": [paragraph("x")] * (eng.MAX_BLOCKS + 1)}, "at most"),
    ],
)
def test_validation_names_the_problem(template: dict, fragment: str) -> None:
    problems = eng.validate_template(template)
    assert problems and any(fragment in p for p in problems), problems
    with pytest.raises(eng.DocumentError):
        eng.render_pdf(template, {})


def test_every_library_template_is_valid_and_renders() -> None:
    assert len(lib.LIBRARY) == 10
    for key in lib.LIBRARY:
        entry = lib.get(key)
        assert eng.validate_template(entry["template"]) == [], key
        pdf = eng.render_pdf(entry["template"], entry["sample"], compute=entry["compute"])
        assert pdf.startswith(b"%PDF") and len(PdfReader(io.BytesIO(pdf)).pages) >= 1


# -- rendering --------------------------------------------------------------------------------


def test_data_is_printed_as_text_never_interpreted() -> None:
    hostile = "<b>bold</b> <a href='http://evil/'>x</a> &amp; <para>"
    pdf = eng.render_pdf(one(paragraph("{{v}}")), {"v": hostile})
    shown = text_of(pdf)
    assert "<b>bold</b>" in shown and "&amp;" in shown  # literally, not rendered as bold or decoded


def test_static_template_text_is_escaped_too() -> None:
    pdf = eng.render_pdf(one(paragraph("1 < 2 & 3 > 2")), {})
    assert "1 < 2 & 3 > 2" in text_of(pdf)


def test_output_is_deterministic_and_carries_no_clock() -> None:
    entry = lib.get("invoice")
    first = eng.render_pdf(entry["template"], entry["sample"], compute="items")
    second = eng.render_pdf(entry["template"], entry["sample"], compute="items")
    assert first == second
    # a different value gives a different document
    changed = {**entry["sample"], "number": "OTHER"}
    assert eng.render_pdf(entry["template"], changed, compute="items") != first


def test_table_rows_and_data_size_are_limited() -> None:
    table = {"type": "table", "source": "rows", "columns": [{"header": "h", "value": "{{item.a}}"}]}
    big = {"rows": [{"a": 1}] * (eng.MAX_TABLE_ROWS + 1)}
    with pytest.raises(eng.DocumentError):
        eng.render_pdf(one(table), big)
    deep: dict = {}
    cursor = deep
    for _ in range(eng.MAX_DATA_DEPTH + 2):
        cursor["x"] = {}
        cursor = cursor["x"]
    with pytest.raises(eng.DocumentError):
        eng.render_pdf(one(paragraph("x")), deep)
    with pytest.raises(eng.DocumentError):
        eng.render_pdf(one(table), {"rows": "not a list"})


def test_a_runaway_document_is_stopped_at_the_page_limit() -> None:
    template = one(*([paragraph("x"), {"type": "page_break"}] * 60))
    with pytest.raises(eng.DocumentError, match="pages"):
        eng.render_pdf(template, {})


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")
        )

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    rows = b"".join(b"\x00" + b"\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_images_are_checked_by_content_and_size() -> None:
    small = base64.b64encode(_png(8, 8)).decode()
    pdf = eng.render_pdf(one({"type": "image", "data_base64": small, "width_mm": 20}), {})
    assert pdf.startswith(b"%PDF")
    giant_pixels = base64.b64encode(_png(eng.MAX_IMAGE_PIXELS + 1, 1)).decode()
    with pytest.raises(eng.DocumentError, match="pixels"):
        eng.render_pdf(one({"type": "image", "data_base64": giant_pixels}), {})
    too_big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (eng.MAX_IMAGE_BYTES + 10)).decode()
    assert any(
        "KB" in p for p in eng.validate_template(one({"type": "image", "data_base64": too_big}))
    )


def test_page_numbers_and_header_footer() -> None:
    template = {
        "header": "Acme",
        "footer": "page {{page}} of {{pages}}",
        "blocks": [paragraph("one"), {"type": "page_break"}, paragraph("two")],
    }
    text = text_of(eng.render_pdf(template, {}))
    assert "page 1 of 2" in text and "page 2 of 2" in text and "Acme" in text


def test_qr_and_signature_and_landscape_render() -> None:
    template = {
        "page": {"size": "LETTER", "orientation": "landscape", "margin_mm": 10},
        "blocks": [{"type": "qr", "value": "{{v}}"}, {"type": "signature", "text": "Signed"}],
    }
    pdf = eng.render_pdf(template, {"v": "https://example.com/x"})
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    assert float(page.mediabox.width) > float(page.mediabox.height)
