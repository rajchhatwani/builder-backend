"""Filenames and storage keys (generated).

A client-supplied filename is shown back to people and nothing else: it is never part of the
storage key and never used as a path. It is cleaned here so it is safe to show and to send in a
header.
"""

import re
import unicodedata
import uuid
from datetime import datetime
from urllib.parse import quote

MAX_NAME_LENGTH = 200

# Control characters, line separators, bidirectional overrides and zero-width characters: they
# make a name look different from what it is (e.g. "invoice‮gpj.exe").
_INVISIBLE_RE = re.compile(
    "[\x00-\x1f\x7f-\x9f​-‏ -‮⁠-⁯﻿]"
)
_FORBIDDEN_RE = re.compile(r'[<>:"|?*\\/]')
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)


def safe_filename(raw: str | None) -> str:
    """A display name that is safe to store, show and put in a header. Never empty."""
    if not raw:
        return "file"
    name = unicodedata.normalize("NFC", raw)
    name = name.replace("\\", "/").rsplit("/", 1)[-1]  # a path becomes its last part
    name = _INVISIBLE_RE.sub("", name)
    name = _FORBIDDEN_RE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")  # no leading/trailing dots or spaces
    if not name:
        return "file"
    stem, dot, ext = name.rpartition(".")
    if dot and stem.lower() in _WINDOWS_RESERVED or (not dot and name.lower() in _WINDOWS_RESERVED):
        name = f"_{name}"
    if len(name) > MAX_NAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 16:
            name = stem[: MAX_NAME_LENGTH - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            name = name[:MAX_NAME_LENGTH].rstrip(" .")
    return name or "file"


def content_disposition(name: str, *, inline: bool = False) -> str:
    """`attachment; filename="ascii"; filename*=UTF-8''percent-encoded` (RFC 6266 / 8187)."""
    kind = "inline" if inline else "attachment"
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace("?", "_")
    ascii_name = re.sub(r'["\\]', "_", ascii_name)
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


def make_key(prefix: str, tenant_id: uuid.UUID | None, file_id: uuid.UUID, now: datetime) -> str:
    """Where the bytes live. Built only from the configured prefix, ids and the date."""
    tenant = str(tenant_id) if tenant_id is not None else "_"
    return f"{prefix}/{tenant}/{now:%Y/%m}/{file_id}"
