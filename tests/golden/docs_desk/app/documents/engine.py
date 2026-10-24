"""PDF document engine. One module, two homes.

This file is the single source of truth. The builder imports it (template validation, live preview, tests)
and the generator copies it **byte for byte** into every project that has documents
(`app/documents/engine.py`), so the preview in the dashboard is exactly what the generated API renders.

What keeps it safe (each has tests):
  * a template is **data**: a list of typed blocks. There is no HTML, no expression language and no code;
    ReportLab draws the page directly, so there is no URL fetching (no SSRF) and no local-file access;
  * placeholders `{{ path | filter:arg }}` are resolved by a tiny resolver: dotted lookup in plain dicts and
    lists (no attributes, no calls) and a fixed list of formatters (money, number, date, upper, lower,
    default). Whatever a placeholder resolves to is XML-escaped before ReportLab sees it, so data can never
    inject markup;
  * hard limits (blocks, rows, text length, image size, pages) bound the work one request can cause;
  * totals of money documents are **recomputed** here from the line items with Decimal; a total sent by the
    caller is ignored;
  * output is deterministic: the same template and data give the same bytes (`invariant` mode, fixed
    metadata), so a stored document can be re-rendered and compared by hash.

Fonts: the Bitstream Vera family that ships with ReportLab (Latin scripts). Scripts that need shaping
(Arabic, Indic) or CJK glyphs are not supported by this engine; see docs/DOCUMENTS.md.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from xml.sax.saxutils import escape

import reportlab
from PIL import Image as PILImage
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MAX_BLOCKS = 200
MAX_TABLE_ROWS = 500
MAX_TABLE_COLUMNS = 12
MAX_TEXT = 5000
MAX_IMAGE_BYTES = 200_000
MAX_IMAGE_PIXELS = 4000
MAX_PAGES = 50
MAX_DATA_DEPTH = 12

BLOCK_TYPES = (
    "heading",
    "paragraph",
    "kv",
    "table",
    "totals",
    "spacer",
    "rule",
    "page_break",
    "image",
    "signature",
    "qr",
)
PAGE_SIZES = ("A4", "LETTER")
FILTERS = ("money", "number", "date", "upper", "lower", "default")
ALIGNS = ("left", "right", "center")
ZERO_DECIMAL = frozenset({"JPY", "KRW", "VND", "CLP", "ISK", "UGX", "PYG", "XAF", "XOF"})
THREE_DECIMAL = frozenset({"BHD", "JOD", "KWD", "OMR", "TND"})
_DATE_CODES = frozenset("YmdbBeHMjy")

_PLACEHOLDER = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*(?:\|\s*([a-z]+)\s*(?::\s*([^{}|]*?))?\s*)?\}\}"
)
_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*")


class DocumentError(ValueError):
    """The template or the data is not acceptable. The message is safe to show to a user."""


# -- resolver -------------------------------------------------------------------------------------


def lookup(data: Any, path: str) -> Any:
    """Dotted lookup in dicts and lists. Missing anything gives None; nothing is ever called."""
    current = data
    for part in path.split("."):
        if isinstance(current, Mapping):
            current = current.get(part)
        elif (
            isinstance(current, Sequence)
            and not isinstance(current, str | bytes)
            and part.isdigit()
        ):
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise DocumentError("a yes/no value cannot be used as an amount")
    try:
        number = (
            Decimal(str(value).strip().replace(",", ""))
            if isinstance(value, str)
            else Decimal(str(value))
        )
    except (InvalidOperation, ValueError) as exc:
        raise DocumentError(f"{value!r} is not a number") from exc
    if not number.is_finite():
        raise DocumentError(f"{value!r} is not a number")
    return number


def decimals_for(currency: str | None) -> int:
    code = (currency or "").upper()
    return 0 if code in ZERO_DECIMAL else 3 if code in THREE_DECIMAL else 2


def format_money(value: Any, currency: str | None) -> str:
    places = decimals_for(currency)
    quantum = Decimal(1).scaleb(-places)
    amount = _decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)
    text = f"{amount:,.{places}f}"
    # The code, not a symbol: the bundled fonts have no glyph for many currency signs.
    return f"{text} {currency.upper()}" if currency else text


def format_date(value: Any, pattern: str | None) -> str:
    pattern = (pattern or "%Y-%m-%d").strip()
    if not all(
        pattern[i + 1] in _DATE_CODES for i, c in enumerate(pattern[:-1]) if c == "%"
    ) or pattern.endswith("%"):
        raise DocumentError(f"date format {pattern!r} uses an unsupported code")
    if isinstance(value, datetime):
        moment: date | datetime = value
    elif isinstance(value, date):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise DocumentError(f"{value!r} is not a date") from exc
    return moment.strftime(pattern)


def apply_filter(name: str, value: Any, arg: str | None, data: Mapping[str, Any]) -> str:
    if name == "default":
        return str(value) if value not in (None, "") else (arg or "")
    if value is None:
        return ""
    if name == "upper":
        return str(value).upper()
    if name == "lower":
        return str(value).lower()
    if name == "number":
        return f"{_decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
    if name == "date":
        return format_date(value, arg)
    if name == "money":
        currency = (arg or "").strip()
        if currency.startswith("@"):  # money:@currency  -> the currency stored in the data
            currency = str(lookup(data, currency[1:]) or "")
        return format_money(value, currency or None)
    raise DocumentError(f"unknown formatter {name!r} (use {', '.join(FILTERS)})")


def resolve(text: str, data: Mapping[str, Any]) -> str:
    """Replace every placeholder. The result is plain text (not yet escaped for ReportLab)."""
    if len(text) > MAX_TEXT:
        raise DocumentError(f"a text is longer than {MAX_TEXT} characters")

    def replace(match: re.Match[str]) -> str:
        path, name, arg = match.group(1), match.group(2), match.group(3)
        value = lookup(data, path)
        if name is None:
            return "" if value is None else str(value)
        return apply_filter(name, value, arg, data)

    return _PLACEHOLDER.sub(replace, text)


def placeholders(text: str) -> list[tuple[str, str | None]]:
    """(path, filter) of every placeholder in `text`: lets the builder check them against entity fields."""
    return [(m.group(1), m.group(2)) for m in _PLACEHOLDER.finditer(text)]


# -- totals ---------------------------------------------------------------------------------------


def compute_totals(data: Mapping[str, Any], items_path: str = "items") -> dict[str, Any]:
    """`data` with `totals` (re-)computed from the line items, ignoring any totals the caller sent.

    Each item: quantity (default 1), unit_price, tax_rate (percent, default 0), optional discount (an
    amount taken off the line). Tax is computed per rate on the summed net amount and rounded half up to
    the currency's minor unit; the total is net plus tax.
    """
    items = lookup(data, items_path)
    result = dict(data)
    if items is None:
        return result
    if not isinstance(items, list):
        raise DocumentError(f"{items_path} must be a list")
    if len(items) > MAX_TABLE_ROWS:
        raise DocumentError(f"at most {MAX_TABLE_ROWS} line items")
    places = decimals_for(str(data.get("currency") or ""))
    quantum = Decimal(1).scaleb(-places)
    net_by_rate: dict[Decimal, Decimal] = {}
    lines: list[Any] = []
    subtotal = Decimal(0)
    for raw in items:
        if not isinstance(raw, Mapping):
            raise DocumentError("every line item must be an object")
        quantity = _decimal(raw.get("quantity", 1))
        price = _decimal(raw.get("unit_price", 0))
        discount = _decimal(raw.get("discount", 0))
        rate = _decimal(raw.get("tax_rate", 0))
        if quantity < 0 or price < 0 or discount < 0 or not Decimal(0) <= rate <= Decimal(100):
            raise DocumentError(
                "quantities, prices and discounts cannot be negative; tax rate is 0 to 100"
            )
        net = (quantity * price - discount).quantize(quantum, rounding=ROUND_HALF_UP)
        subtotal += net
        net_by_rate[rate] = net_by_rate.get(rate, Decimal(0)) + net
        lines.append({**raw, "line_total": str(net)})
    breakdown = []
    tax_total = Decimal(0)
    for rate in sorted(net_by_rate):
        tax = (net_by_rate[rate] * rate / 100).quantize(quantum, rounding=ROUND_HALF_UP)
        tax_total += tax
        breakdown.append(
            {"rate": str(rate.normalize()), "net": str(net_by_rate[rate]), "tax": str(tax)}
        )
    result[items_path] = lines
    result["totals"] = {
        "subtotal": str(subtotal),
        "tax_total": str(tax_total),
        "total": str(subtotal + tax_total),
        "tax_breakdown": breakdown,
    }
    return result


# -- template validation --------------------------------------------------------------------------


def _check_text(value: Any, where: str, problems: list[str]) -> None:
    if not isinstance(value, str):
        problems.append(f"{where}: must be text")
    elif len(value) > MAX_TEXT:
        problems.append(f"{where}: longer than {MAX_TEXT} characters")
    else:
        for path, name in placeholders(value):
            if not _PATH.fullmatch(path):
                problems.append(f"{where}: bad placeholder {path!r}")
            if name is not None and name not in FILTERS:
                problems.append(f"{where}: unknown formatter {name!r}")


def _image_problem(b64: Any) -> str | None:
    if not isinstance(b64, str):
        return "must be base64 text"
    if len(b64) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        return f"larger than {MAX_IMAGE_BYTES // 1000} KB"
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return "is not valid base64"
    if not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
        return "must be a PNG or JPEG"
    return None


def validate_template(template: Mapping[str, Any]) -> list[str]:
    """Every problem with a template, as short messages (empty = acceptable)."""
    problems: list[str] = []
    page = template.get("page", {})
    if not isinstance(page, Mapping):
        return ["page: must be an object"]
    if str(page.get("size", "A4")).upper() not in PAGE_SIZES:
        problems.append(f"page.size: use one of {', '.join(PAGE_SIZES)}")
    if page.get("orientation", "portrait") not in ("portrait", "landscape"):
        problems.append("page.orientation: portrait or landscape")
    margin = page.get("margin_mm", 18)
    if isinstance(margin, bool) or not isinstance(margin, int | float) or not 5 <= margin <= 50:
        problems.append("page.margin_mm: between 5 and 50")
    for key in ("header", "footer"):
        if key in template:
            _check_text(template[key], key, problems)
    blocks = template.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return [*problems, "blocks: add at least one block"]
    if len(blocks) > MAX_BLOCKS:
        return [*problems, f"blocks: at most {MAX_BLOCKS}"]
    for i, block in enumerate(blocks):
        where = f"blocks[{i}]"
        if not isinstance(block, Mapping) or block.get("type") not in BLOCK_TYPES:
            problems.append(f"{where}: type must be one of {', '.join(BLOCK_TYPES)}")
            continue
        kind = block["type"]
        if kind in ("heading", "paragraph", "signature"):
            _check_text(block.get("text", block.get("label", "")), f"{where}.text", problems)
        if kind == "heading" and block.get("level", 1) not in (1, 2, 3):
            problems.append(f"{where}.level: 1, 2 or 3")
        if kind in ("kv", "totals"):
            rows = block.get("rows")
            if not isinstance(rows, list) or not rows or len(rows) > 60:
                problems.append(f"{where}.rows: 1 to 60 rows")
            else:
                for j, row in enumerate(rows):
                    if not isinstance(row, Mapping):
                        problems.append(f"{where}.rows[{j}]: must be {{label, value}}")
                        continue
                    _check_text(row.get("label", ""), f"{where}.rows[{j}].label", problems)
                    _check_text(row.get("value", ""), f"{where}.rows[{j}].value", problems)
        if kind == "table":
            source = block.get("source")
            if not isinstance(source, str) or not _PATH.fullmatch(source):
                problems.append(f"{where}.source: the name of the list in your data (items)")
            cols = block.get("columns")
            if not isinstance(cols, list) or not cols or len(cols) > MAX_TABLE_COLUMNS:
                problems.append(f"{where}.columns: 1 to {MAX_TABLE_COLUMNS} columns")
            else:
                for j, col in enumerate(cols):
                    if not isinstance(col, Mapping):
                        problems.append(f"{where}.columns[{j}]: must be an object")
                        continue
                    _check_text(col.get("header", ""), f"{where}.columns[{j}].header", problems)
                    _check_text(col.get("value", ""), f"{where}.columns[{j}].value", problems)
                    if col.get("align", "left") not in ALIGNS:
                        problems.append(f"{where}.columns[{j}].align: left, right or center")
        if kind == "spacer":
            height = block.get("height_mm", 6)
            if (
                isinstance(height, bool)
                or not isinstance(height, int | float)
                or not 1 <= height <= 100
            ):
                problems.append(f"{where}.height_mm: between 1 and 100")
        if kind == "image":
            problem = _image_problem(block.get("data_base64"))
            if problem:
                problems.append(f"{where}.data_base64: {problem}")
            width = block.get("width_mm", 40)
            if (
                isinstance(width, bool)
                or not isinstance(width, int | float)
                or not 5 <= width <= 180
            ):
                problems.append(f"{where}.width_mm: between 5 and 180")
        if kind == "qr":
            _check_text(block.get("value", ""), f"{where}.value", problems)
    return problems


def _check_data(value: Any, depth: int = 0) -> None:
    if depth > MAX_DATA_DEPTH:
        raise DocumentError("the data is nested too deeply")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise DocumentError("data keys must be text")
            _check_data(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_TABLE_ROWS:
            raise DocumentError(f"a list has more than {MAX_TABLE_ROWS} entries")
        for item in value:
            _check_data(item, depth + 1)


# -- rendering ------------------------------------------------------------------------------------


def render_pdf(
    template: Mapping[str, Any], data: Mapping[str, Any], *, compute: str | None = None
) -> bytes:
    """The PDF for `template` filled with `data`. `compute` names the list whose totals are recomputed
    (None leaves the data alone). Raises DocumentError for anything unacceptable."""
    problems = validate_template(template)
    if problems:
        raise DocumentError("; ".join(problems[:5]))
    _check_data(data)
    scope: Mapping[str, Any] = compute_totals(data, compute) if compute else data
    return _build(template, scope)


def _build(template: Mapping[str, Any], data: Mapping[str, Any]) -> bytes:
    fonts_dir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    for name, file in (("Doc", "Vera.ttf"), ("Doc-Bold", "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, os.path.join(fonts_dir, file)))

    page = template.get("page", {})
    size = A4 if str(page.get("size", "A4")).upper() == "A4" else LETTER
    if page.get("orientation") == "landscape":
        size = landscape(size)
    margin = float(page.get("margin_mm", 18)) * mm
    width = size[0] - 2 * margin
    align_map = {"left": TA_LEFT, "right": TA_RIGHT, "center": TA_CENTER}
    base = ParagraphStyle("base", fontName="Doc", fontSize=9.5, leading=13)
    heads = {
        1: ParagraphStyle(
            "h1", parent=base, fontName="Doc-Bold", fontSize=20, leading=24, spaceAfter=8
        ),
        2: ParagraphStyle(
            "h2", parent=base, fontName="Doc-Bold", fontSize=14, leading=18, spaceAfter=6
        ),
        3: ParagraphStyle(
            "h3", parent=base, fontName="Doc-Bold", fontSize=11, leading=14, spaceAfter=4
        ),
    }

    def text(value: str) -> str:
        return escape(resolve(value, data)).replace("\n", "<br/>")

    def para(value: str, style: ParagraphStyle) -> Paragraph:
        return Paragraph(text(value), style)

    flow: list[Any] = []
    for block in template["blocks"]:
        kind = block["type"]
        if kind == "heading":
            flow.append(para(block.get("text", ""), heads[int(block.get("level", 1))]))
        elif kind == "paragraph":
            flow.append(para(block.get("text", ""), base))
            flow.append(Spacer(1, 3 * mm))
        elif kind in ("kv", "totals"):
            right = kind == "totals"
            style = ParagraphStyle("kv", parent=base, alignment=TA_RIGHT if right else TA_LEFT)
            bold = ParagraphStyle("kvb", parent=style, fontName="Doc-Bold")
            rows = [
                [para(r.get("label", ""), bold), para(r.get("value", ""), style)]
                for r in block["rows"]
            ]
            table = Table(
                rows,
                colWidths=[width * 0.35, width * 0.65] if not right else [width * 0.7, width * 0.3],
                hAlign="RIGHT" if right else "LEFT",
            )
            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            flow += [table, Spacer(1, 4 * mm)]
        elif kind == "table":
            rows_data = lookup(data, block["source"]) or []
            if not isinstance(rows_data, list):
                raise DocumentError(f"{block['source']} must be a list")
            if len(rows_data) > MAX_TABLE_ROWS:
                raise DocumentError(f"at most {MAX_TABLE_ROWS} rows in a table")
            cols = block["columns"]
            head_style = ParagraphStyle(
                "th", parent=base, fontName="Doc-Bold", textColor=colors.white
            )
            head_row = [
                Paragraph(
                    escape(resolve(c.get("header", ""), data)),
                    ParagraphStyle(
                        "thc", parent=head_style, alignment=align_map[c.get("align", "left")]
                    ),
                )
                for c in cols
            ]
            body = []
            for index, item in enumerate(rows_data, start=1):
                scope = {**data, "item": item, "index": index}
                body.append(
                    [
                        Paragraph(
                            escape(resolve(c.get("value", ""), scope)).replace("\n", "<br/>"),
                            ParagraphStyle(
                                "td", parent=base, alignment=align_map[c.get("align", "left")]
                            ),
                        )
                        for c in cols
                    ]
                )
            weights = [float(c.get("width", 1)) for c in cols]
            total_w = sum(weights) or 1
            table = Table(
                [head_row, *body], colWidths=[width * w / total_w for w in weights], repeatRows=1
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            flow += [table, Spacer(1, 4 * mm)]
        elif kind == "spacer":
            flow.append(Spacer(1, float(block.get("height_mm", 6)) * mm))
        elif kind == "rule":
            flow.append(
                HRFlowable(
                    width="100%",
                    thickness=0.5,
                    color=colors.HexColor("#9ca3af"),
                    spaceBefore=2,
                    spaceAfter=6,
                )
            )
        elif kind == "page_break":
            flow.append(PageBreak())
        elif kind == "image":
            raw = base64.b64decode(block["data_base64"])
            with PILImage.open(io.BytesIO(raw)) as probe:
                px_w, px_h = probe.size
            if max(px_w, px_h) > MAX_IMAGE_PIXELS:
                raise DocumentError(f"an image is larger than {MAX_IMAGE_PIXELS} pixels")
            target = float(block.get("width_mm", 40)) * mm
            image = Image(io.BytesIO(raw), width=target, height=target * px_h / px_w)
            image.hAlign = {"left": "LEFT", "right": "RIGHT", "center": "CENTER"}[
                block.get("align", "left")
            ]
            flow += [image, Spacer(1, 3 * mm)]
        elif kind == "signature":
            line = Table(
                [[""], [para(block.get("text", block.get("label", "Signature")), base)]],
                colWidths=[width * 0.4],
                hAlign="LEFT",
            )
            line.setStyle(
                TableStyle(
                    [
                        ("LINEABOVE", (0, 1), (0, 1), 0.5, colors.black),
                        ("TOPPADDING", (0, 0), (0, 0), 18),
                    ]
                )
            )
            flow += [line, Spacer(1, 4 * mm)]
        elif kind == "qr":
            widget = QrCodeWidget(resolve(block.get("value", ""), data)[:600])
            x0, y0, x1, y1 = widget.getBounds()
            side = float(block.get("size_mm", 28)) * mm
            drawing = Drawing(
                side, side, transform=[side / (x1 - x0), 0, 0, side / (y1 - y0), 0, 0]
            )
            drawing.add(widget)
            flow += [drawing, Spacer(1, 3 * mm)]

    header = resolve(str(template.get("header", "")), data)
    footer_template = str(template.get("footer", ""))
    title = resolve(str(template.get("title", "")), data)

    class NumberedCanvas(rl_canvas.Canvas):  # type: ignore[misc]
        """Two passes, so the footer can say page 2 of 5."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._saved: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 (ReportLab's name)
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            pages = len(self._saved)
            if pages > MAX_PAGES:
                raise DocumentError(f"the document would have more than {MAX_PAGES} pages")
            for state in self._saved:
                self.__dict__.update(state)
                self._decorate(pages)
                super().showPage()
            super().save()

        def _decorate(self, pages: int) -> None:
            self.setFont("Doc", 8)
            self.setFillColor(colors.HexColor("#6b7280"))
            if header:
                self.drawString(margin, size[1] - margin + 6 * mm, header[:200])
            if footer_template:
                shown = resolve(
                    footer_template.replace("{{page}}", str(self._pageNumber)).replace(
                        "{{pages}}", str(pages)
                    ),
                    data,
                )
                self.drawCentredString(size[0] / 2, margin - 8 * mm, shown[:200])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=title,
        author="",
        creator="",
        invariant=1,  # fixed dates and ids: the same input always gives the same bytes
    )
    doc.build(flow, canvasmaker=NumberedCanvas)
    return buffer.getvalue()
