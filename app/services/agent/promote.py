"""B-004: promotion of agent-written custom-zone files (hook bodies, tests) on apply.

The live project keeps its custom code on the `main` branch of the project's repo
(`WorkspaceService.promote_files`); every new workspace starts from it. What is promoted is decided
by the final review (kind C), never by the worktree's current content:

  1. When the review is asked, the custom-zone files the run changed are listed WITH their sha256
     (`custom_file_hashes`, stored in the approval payload as `file_hashes`; the payload itself is
     bound to the approval by its payload hash).
  2. On apply, `collect` re-reads each listed file from the worktree. A file whose bytes no longer hash
     to the approved value (or that is gone, linked, outside the custom zone) refuses the whole
     promotion. Files that are not in the approved list are never promoted.
"""

import base64
import binascii
import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.generator.zones import zone_for
from app.exceptions import AppError
from app.services.agent.tools._common import _clean_rel, _denied

MAX_PROMOTED_FILES = 100
MAX_PROMOTED_BYTES = 256 * 1024
MAX_PROMOTED_TOTAL = 1024 * 1024  # all files of one promotion (they are stored with the apply, FX-3)
MAX_PROMOTION_ATTEMPTS = 5


def encode(files: dict[str, bytes]) -> dict[str, Any] | None:
    """FX-3 / B-004: what the apply transaction stores so a crash between the spec apply and the git
    commit can be retried: {"state": "pending", "attempts": 0, "files": {rel: base64}}."""
    if not files:
        return None
    return {"state": "pending", "attempts": 0,
            "files": {rel: base64.b64encode(data).decode("ascii") for rel, data in sorted(files.items())}}


def decode(doc: Any) -> dict[str, bytes] | None:
    """The stored pending files, or None when the document is not a well-formed pending promotion."""
    if not isinstance(doc, dict) or doc.get("state") != "pending" or not isinstance(doc.get("files"), dict):
        return None
    out: dict[str, bytes] = {}
    for rel, b64 in doc["files"].items():
        if not isinstance(rel, str) or not isinstance(b64, str) or not promotable(rel):
            return None
        try:
            out[rel] = base64.b64decode(b64.encode("ascii"), validate=True)
        except (binascii.Error, ValueError):
            return None
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(root: Path, rel: str) -> bytes | None:
    """The bytes of a regular file inside root, never through a link; None otherwise."""
    cur = root
    for part in PurePosixPath(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            return None
    if not cur.is_file():
        return None
    if cur.stat().st_size > MAX_PROMOTED_BYTES:
        return None
    return cur.read_bytes()


def promotable(rel: str) -> bool:
    """A path the promotion may ever carry: custom zone, plain relative path, not a denied name."""
    try:
        p = _clean_rel(rel, "promote")
    except Exception:
        return False
    return zone_for(p.as_posix()) == "custom" and not _denied(p)


def custom_file_hashes(root: Path, changed: list[str]) -> dict[str, str]:
    """{rel: sha256} of the changed files that sit in the custom zone (what the reviewer is shown)."""
    out: dict[str, str] = {}
    for rel in changed:
        if len(out) >= MAX_PROMOTED_FILES:
            break
        if not promotable(rel):
            continue
        data = _read_regular(root, rel)
        if data is not None:
            out[rel] = _sha(data)
    return out


def collect(root: Path, declared: Any) -> dict[str, bytes]:
    """The approved files, verified against the worktree. AppError (409) on any mismatch: a half
    promotion is never produced."""
    if not isinstance(declared, dict) or not declared:
        return {}
    if len(declared) > MAX_PROMOTED_FILES:
        raise AppError("promotion_refused", "the approval lists too many files", 409)
    out: dict[str, bytes] = {}
    total = 0
    for rel, sha in sorted(declared.items()):
        if not isinstance(rel, str) or not isinstance(sha, str) or not promotable(rel):
            raise AppError("promotion_refused", f"{str(rel)[:80]} is not a promotable custom-zone file", 409)
        data = _read_regular(root, rel)
        if data is None or _sha(data) != sha:
            raise AppError(
                "promotion_hash_mismatch",
                f"{rel[:80]} differs from the file that was approved; nothing was promoted",
                409,
            )
        total += len(data)
        if total > MAX_PROMOTED_TOTAL:
            raise AppError("promotion_refused", "the approved files are too large to promote together", 409)
        out[rel] = data
    return out
