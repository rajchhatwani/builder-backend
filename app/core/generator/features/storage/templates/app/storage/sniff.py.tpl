"""Decides what a file really is from its first bytes (generated).

The `Content-Type` a client sends and the extension of its filename are claims, not facts, so
neither is used to decide anything. This looks at the leading bytes ("magic numbers"). It is a
second opinion next to the malware scan, not a replacement for it: it stops a renamed executable
from passing as a picture, and it decides what an allowlist means.
"""

import re
from dataclasses import dataclass

HEAD_BYTES = 8192
OCTET_STREAM = "application/octet-stream"
TEXT_PLAIN = "text/plain"

# Declared types that a plain-text file may legitimately carry (text has no magic number).
TEXT_DECLARED = frozenset(
    {
        "text/plain",
        "text/csv",
        "text/tab-separated-values",
        "text/markdown",
        "application/json",
        "application/x-ndjson",
        "application/yaml",
        "text/yaml",
    }
)
# Types that browsers can show inline without running anything of the file's own.
INLINE_SAFE = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"%PDF-", "application/pdf"),
    (b"\x1f\x8b", "application/gzip"),
    (b"BZh", "application/x-bzip2"),
    (b"\xfd7zXZ\x00", "application/x-xz"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"Rar!\x1a\x07", "application/vnd.rar"),
    (b"\x28\xb5\x2f\xfd", "application/zstd"),
    (b"OggS", "audio/ogg"),
    (b"fLaC", "audio/flac"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"\x1a\x45\xdf\xa3", "video/webm"),
    (b"SQLite format 3\x00", "application/vnd.sqlite3"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/x-ole-storage"),
    (b"MZ", "application/vnd.microsoft.portable-executable"),
    (b"\x7fELF", "application/x-executable"),
    (b"\xca\xfe\xba\xbe", "application/x-mach-binary"),
    (b"\xcf\xfa\xed\xfe", "application/x-mach-binary"),
    (b"#!", "text/x-shellscript"),
)
_HTML_RE = re.compile(rb"\s*(?:<!--.*?-->\s*)*<(?:!doctype\s+html|html|head|body|script|iframe)", re.I | re.S)
_SVG_RE = re.compile(rb"<svg[\s>]", re.I)
_XML_RE = re.compile(rb"\s*<\?xml", re.I)


@dataclass(frozen=True)
class Detected:
    mime: str
    # True for content that has no magic number and was recognised as text
    text: bool = False


def detect(head: bytes) -> Detected:
    """The type of a file from its first bytes (up to HEAD_BYTES)."""
    head = head[:HEAD_BYTES]
    if head.startswith(b"RIFF") and len(head) >= 12:
        kind = head[8:12]
        if kind == b"WEBP":
            return Detected("image/webp")
        if kind == b"WAVE":
            return Detected("audio/wav")
        if kind == b"AVI ":
            return Detected("video/x-msvideo")
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            return Detected("audio/mp4")
        if brand == b"qt  ":
            return Detected("video/quicktime")
        if brand in (b"heic", b"heix", b"mif1", b"avif"):
            return Detected("image/avif" if brand == b"avif" else "image/heic")
        return Detected("video/mp4")
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return Detected(_zip_flavour(head))
    for magic, mime in _SIGNATURES:
        if head.startswith(magic):
            return Detected(mime)
    if _looks_like_text(head):
        if _HTML_RE.match(head):
            return Detected("text/html", text=True)
        if _SVG_RE.search(head):
            return Detected("image/svg+xml", text=True)
        if _XML_RE.match(head):
            return Detected("application/xml", text=True)
        return Detected(TEXT_PLAIN, text=True)
    return Detected(OCTET_STREAM)


def _zip_flavour(head: bytes) -> str:
    """Office and OpenDocument files are zip containers; their member names say which."""
    if b"mimetypeapplication/vnd.oasis.opendocument.text" in head:
        return "application/vnd.oasis.opendocument.text"
    if b"mimetypeapplication/vnd.oasis.opendocument.spreadsheet" in head:
        return "application/vnd.oasis.opendocument.spreadsheet"
    if b"mimetypeapplication/vnd.oasis.opendocument.presentation" in head:
        return "application/vnd.oasis.opendocument.presentation"
    if b"mimetypeapplication/epub+zip" in head:
        return "application/epub+zip"
    if b"[Content_Types].xml" in head:
        if b"word/" in head:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if b"xl/" in head:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if b"ppt/" in head:
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return "application/zip"


def _looks_like_text(head: bytes) -> bool:
    if not head:
        return False
    if b"\x00" in head:
        return False
    body = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start < len(body) - 4:  # a cut-off character at the very end is fine
            return False
    return True


def _matches(allowed: str, mime: str) -> bool:
    if allowed.endswith("/*"):
        return mime.startswith(allowed[:-1])
    return allowed == mime


def type_allowed(allowed: tuple[str, ...], detected: Detected, declared: str) -> bool:
    """True when the allowlist (empty = any type) admits the file.

    The detected type decides. Plain text has no magic number, so for text a declared type from
    TEXT_DECLARED (csv, json, markdown...) may stand in, but only when the content really is text.
    """
    if not allowed:
        return True
    if any(_matches(a, detected.mime) for a in allowed):
        return True
    return (
        detected.mime == TEXT_PLAIN
        and declared in TEXT_DECLARED
        and any(_matches(a, declared) for a in allowed)
    )


def normalize_declared(value: str | None) -> str:
    """The client's Content-Type without parameters, lower-cased; a lie we only record."""
    if not value:
        return OCTET_STREAM
    base = value.split(";", 1)[0].strip().lower()
    return base[:100] if re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", base) else OCTET_STREAM


def served_type(detected_mime: str) -> str:
    """The Content-Type a download is sent with: the detected type if it is one of the inline-safe
    images, else a generic binary type so a browser never interprets the file."""
    return detected_mime if detected_mime in INLINE_SAFE else OCTET_STREAM
