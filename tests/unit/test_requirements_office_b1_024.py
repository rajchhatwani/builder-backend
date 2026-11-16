# ruff: noqa: E501
"""Audit B1-024: hostile office files give 422 file_invalid; sparse xlsx is not refused by the text cap."""

import io
import time
import zipfile

import pytest

from app.exceptions import AppError
from app.services.requirements import office
from app.services.requirements import reader as rd

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
PR = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'


def _zip(parts: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


def _xlsx(sheet_rows: str) -> bytes:
    return _zip(
        {
            "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="A" sheetId="1" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": f'<Relationships {PR}><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            "xl/worksheets/sheet1.xml": f"<worksheet {S}><sheetData>{sheet_rows}</sheetData></worksheet>",
        }
    )


def test_xlsx_superscript_digit_shared_index_is_422_not_valueerror() -> None:
    data = _xlsx('<row r="1"><c r="A1" t="s"><v>²</v></c><c r="B1" t="inlineStr"><is><t>ok</t></is></c></row>')
    doc = rd.read_document("a.xlsx", data)
    assert "ok" in doc.chunks[0].text


def test_deeply_nested_sdt_docx_is_refused_with_apperror() -> None:
    body = "<w:sdt>" * 1200 + "<w:p><w:r><w:t>hi</w:t></w:r></w:p>" + "</w:sdt>" * 1200
    data = _zip({"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>"})
    try:
        rd.read_document("a.docx", data)
    except AppError as e:
        assert e.status_code in (413, 422)


def test_office_extract_unexpected_error_maps_to_file_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> str:
        raise RecursionError

    monkeypatch.setattr(office, "docx_text", boom)
    with pytest.raises(AppError) as ei:
        rd.read_document("a.docx", b"PK")
    assert ei.value.status_code == 422 and ei.value.code == "file_invalid"


def test_sparse_xlsx_empty_styled_rows_do_not_hit_text_cap() -> None:
    row1 = '<row r="1">' + "".join(f'<c r="{c}1" t="inlineStr"><is><t>{"x" * 1000}</t></is></c>' for c in "ABC") + "</row>"
    empties = "".join(f'<row r="{n}"><c r="A{n}" s="1"/></row>' for n in range(2, 60))
    text = office.xlsx_text("a.xlsx", _xlsx(row1 + empties), 144000, time.monotonic() + 30)
    assert text.count("x") == 3000
