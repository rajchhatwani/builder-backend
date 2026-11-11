"""Text extraction from .docx and .xlsx for the quarantined reader (stdlib only, no network).

The file is hostile input. Nothing is executed or evaluated: macros are refused, formulas are never
calculated (only the value Excel cached is read), links and embedded objects are ignored.
Defences: size caps checked on the real decompressed bytes (never the zip header), a compression
ratio cap (zip bomb), a member-count cap, encrypted / duplicate-name members refused, and every XML
part containing a DOCTYPE or ENTITY declaration is refused before parsing (no entity expansion,
no external entity can exist). Returns plain text; the caller treats it exactly like PDF text.
"""

import io
import re
import time
import zipfile
import zlib
from xml.etree import ElementTree as ET

from app.exceptions import AppError

MAX_MEMBERS = 2000
MAX_PART_BYTES = 8 * 1024 * 1024  # decompressed, per XML part
MAX_TOTAL_BYTES = 32 * 1024 * 1024  # decompressed, all parts read
MAX_RATIO = 200  # decompressed / compressed, per member
MAX_SHEETS = 20
MAX_ROWS = 2000  # per sheet
MAX_COLS = 50
MAX_CELL_CHARS = 1000
MAX_SHARED_STRINGS = 100_000
MAX_NAME = 200

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOCTYPE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_COL = re.compile(r"^([A-Z]{1,3})(\d+)$")


def _bad(name: str, why: str) -> AppError:
    return AppError("file_invalid", f"{name} {why}", 422)


class _Package:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self.read_total = 0
        try:
            self.zf = zipfile.ZipFile(io.BytesIO(data))
            infos = self.zf.infolist()
        except (zipfile.BadZipFile, OSError, ValueError):
            raise _bad(name, "is not a valid Office document") from None
        if len(infos) > MAX_MEMBERS:
            raise _bad(name, "contains too many parts")
        self.parts: dict[str, zipfile.ZipInfo] = {}
        for zi in infos:
            if zi.filename in self.parts:
                raise _bad(name, "is not a valid Office document (duplicate parts)")
            self.parts[zi.filename] = zi
            if zi.flag_bits & 0x1:
                raise _bad(name, "is encrypted")
            if zi.file_size > MAX_PART_BYTES * 4 or (zi.compress_size and zi.file_size / zi.compress_size > MAX_RATIO and zi.file_size > 1_000_000):
                raise AppError("file_too_large", f"{name} expands too much when opened", 413)
        self._refuse_macros()

    def _refuse_macros(self) -> None:
        for fn in self.parts:
            low = fn.lower()
            if "vbaproject" in low or low.startswith(("word/vba", "xl/vba")) or low.endswith((".bin",)) and "vba" in low:
                raise AppError("file_macro_refused", f"{self.name} contains macros and is not accepted", 422)
        ct = self.read("[Content_Types].xml", required=False)
        if ct and re.search(rb"macroEnabled|vbaProject", ct, re.IGNORECASE):
            raise AppError("file_macro_refused", f"{self.name} contains macros and is not accepted", 422)

    def read(self, part: str, required: bool = True) -> bytes | None:
        zi = self.parts.get(part)
        if zi is None:
            if required:
                raise _bad(self.name, "is missing a required part")
            return None
        try:
            with self.zf.open(zi) as fh:
                raw = fh.read(MAX_PART_BYTES + 1)  # bounded on real bytes, not the header
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, zlib.error, EOFError, OSError, ValueError):
            raise _bad(self.name, "is not a valid Office document") from None
        if len(raw) > MAX_PART_BYTES:
            raise AppError("file_too_large", f"{self.name} expands too much when opened", 413)
        self.read_total += len(raw)
        if self.read_total > MAX_TOTAL_BYTES:
            raise AppError("file_too_large", f"{self.name} expands too much when opened", 413)
        return raw

    def xml(self, part: str, required: bool = True) -> ET.Element | None:
        raw = self.read(part, required)
        if raw is None:
            return None
        if b"\x00" in raw or raw[:2] in (b"\xff\xfe", b"\xfe\xff"):  # UTF-16/32 would hide the DOCTYPE scan
            raise _bad(self.name, "uses an unsupported XML encoding")
        if _DOCTYPE.search(raw):  # entity definitions / external entities: refused, never parsed
            raise _bad(self.name, "contains a forbidden XML declaration")
        try:
            return ET.fromstring(raw)  # noqa: S314 - DOCTYPE/ENTITY refused above, sizes capped
        except (ET.ParseError, ValueError):
            raise _bad(self.name, "is not a valid Office document") from None


def _clean(text: str) -> str:
    return _CTRL.sub("", text)


def _para_text(p: ET.Element) -> str:
    out: list[str] = []
    for el in p.iter():
        if el.tag == f"{_W}t" and el.text:
            out.append(el.text)
        elif el.tag == f"{_W}tab":
            out.append("\t")
        elif el.tag in (f"{_W}br", f"{_W}cr"):
            out.append("\n")
    return _clean("".join(out)).strip()


def _is_heading(p: ET.Element) -> bool:
    ps = p.find(f"{_W}pPr/{_W}pStyle")
    val = (ps.get(f"{_W}val") or "") if ps is not None else ""
    return val.lower().startswith(("heading", "title"))


def docx_text(name: str, data: bytes, max_chars: int, deadline: float) -> str:
    pkg = _Package(name, data)
    root = pkg.xml("word/document.xml")
    body = root.find(f"{_W}body") if root is not None else None
    if body is None:
        raise _bad(name, "is not a valid Word document")
    lines: list[str] = []
    total = 0

    def add(line: str) -> None:
        nonlocal total
        total += len(line) + 1
        if total > max_chars or time.monotonic() > deadline:
            raise AppError("file_too_large", f"{name} has too much text to read", 413)
        lines.append(line)

    def walk(parent: ET.Element) -> None:
        for el in parent:
            if el.tag == f"{_W}p":
                t = _para_text(el)
                if t:
                    add(f"# {t[:120]}" if _is_heading(el) else t)
            elif el.tag == f"{_W}tbl":
                for tr in el.iter(f"{_W}tr"):
                    cells = [" ".join(x for x in (_para_text(p) for p in tc.iter(f"{_W}p")) if x)
                             for tc in tr.findall(f"{_W}tc")]
                    if any(cells):
                        add("\t".join(cells[:MAX_COLS]))
            elif el.tag in (f"{_W}sdt", f"{_W}sdtContent"):
                walk(el)

    walk(body)
    return "\n".join(lines)


def _col_index(ref: str) -> int | None:
    m = _COL.match(ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1


def xlsx_text(name: str, data: bytes, max_chars: int, deadline: float) -> str:
    pkg = _Package(name, data)
    wb = pkg.xml("xl/workbook.xml")
    rels = pkg.xml("xl/_rels/workbook.xml.rels", required=False)
    if wb is None:
        raise _bad(name, "is not a valid Excel workbook")
    targets: dict[str, str] = {}
    for rel in (rels if rels is not None else []):
        if rel.tag == f"{_PR}Relationship" and rel.get("TargetMode") != "External":
            targets[rel.get("Id") or ""] = rel.get("Target") or ""
    shared: list[str] = []
    sst = pkg.xml("xl/sharedStrings.xml", required=False)
    if sst is not None:
        for si in sst.findall(f"{_S}si")[:MAX_SHARED_STRINGS]:
            shared.append(_clean("".join(t.text or "" for t in si.iter(f"{_S}t")))[:MAX_CELL_CHARS])
    sheets = wb.find(f"{_S}sheets")
    out: list[str] = []
    total = 0
    for sheet in (list(sheets) if sheets is not None else [])[:MAX_SHEETS]:
        target = targets.get(sheet.get(f"{_R}id") or "", "")
        part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        part = part.replace("xl/xl/", "xl/")
        if ".." in part.split("/") or part not in pkg.parts:
            continue  # a sheet we cannot locate safely is skipped, never guessed
        sx = pkg.xml(part)
        if sx is None:
            continue
        title = _clean(sheet.get("name") or "sheet")[:MAX_NAME]
        rows = [f"# Sheet: {title}"]
        for n, row in enumerate(sx.iter(f"{_S}row")):
            if n >= MAX_ROWS:
                rows.append(f"[sheet truncated at {MAX_ROWS} rows]")
                break
            cells: dict[int, str] = {}
            for pos, c in enumerate(row.findall(f"{_S}c")):
                idx = _col_index(c.get("r") or "")
                idx = pos if idx is None else idx
                if idx >= MAX_COLS:
                    continue
                kind = c.get("t")
                if kind == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter(f"{_S}t"))
                else:
                    v = c.find(f"{_S}v")
                    val = (v.text or "") if v is not None else ""
                    if kind == "s":
                        val = shared[int(val)] if val.isdigit() and int(val) < len(shared) else ""
                    elif kind == "b":
                        val = "TRUE" if val == "1" else "FALSE"
                val = _clean(val).replace("\t", " ").replace("\n", " ")[:MAX_CELL_CHARS]
                if val:
                    cells[idx] = val
            if cells:
                rows.append("\t".join(cells.get(i, "") for i in range(max(cells) + 1)))
            total += sum(len(r) + 1 for r in rows[-1:])
            if total > max_chars or time.monotonic() > deadline:
                raise AppError("file_too_large", f"{name} has too much text to read", 413)
        if len(rows) > 1:  # a sheet with no cells says nothing
            out.append("\n".join(rows))
    return "\n\n".join(out)
