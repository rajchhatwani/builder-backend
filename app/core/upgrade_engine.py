"""Upgrade engine (P3), pure: no disk, no HTTP, no clock, no database.

A proposal compares the tree a project was last generated with (the BASE) to what the current generator
renders from the same spec (the NEW tree) and turns the difference into one git-compatible unified patch.
The owner applies it with `git apply --3way`, which merges seeded files hunk by hunk in their own repo.

Zones: generated and seeded files go into the patch; the custom zone NEVER does. Custom paths are only
listed as `kept`. Every path in a patch comes from a tree, and is checked against a strict character set,
so a hostile stored blob cannot name a path outside the project (no `..`, no absolute path, no quoting).
"""

import difflib
import hashlib
import json
import re
import tomllib
import zlib
from dataclasses import dataclass, field
from typing import Any

from app.core.generator.base import FileTree
from app.core.generator.zones import zone_for

# Bumped by hand when the generator's own behaviour changes (not the blocks). Not part of any generated file.
GENERATOR_VERSION = "1.0.0"
# A stored base tree may never inflate past this (decompression bomb cap).
MAX_BLOB_BYTES = 64 * 1024 * 1024

_SAFE_PATH = re.compile(r"^[A-Za-z0-9._+@=,~-]+(/[A-Za-z0-9._+@=,~-]+)*$")
_NULL_HASH = "0" * 40


class UpgradeError(Exception):
    """A tree or blob that cannot be trusted. `code` is the machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def safe_path(path: str) -> bool:
    return (
        bool(_SAFE_PATH.match(path))
        and not path.startswith("/")
        and all(part not in ("", ".", "..") for part in path.split("/"))
        and len(path) <= 300
    )


def non_custom(tree: FileTree) -> FileTree:
    """The files the platform owns or seeds; the custom zone is never stored or diffed."""
    return {p: c for p, c in tree.items() if zone_for(p) != "custom"}


# -- base tree storage -------------------------------------------------------------------------
def encode_blob(tree: FileTree) -> bytes:
    payload = json.dumps(non_custom(tree), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return zlib.compress(payload.encode("utf-8"), 9)


def decode_blob(blob: bytes, max_bytes: int | None = None) -> FileTree:
    """Inflate a stored tree, refusing anything that would exceed `max_bytes` or names an unsafe path."""
    max_bytes = MAX_BLOB_BYTES if max_bytes is None else max_bytes
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(blob, max_bytes + 1)
        if len(raw) > max_bytes or inflater.unconsumed_tail:
            raise UpgradeError("baseline_too_large", "the stored base tree is larger than the allowed size")
        raw += inflater.flush()
        if len(raw) > max_bytes:
            raise UpgradeError("baseline_too_large", "the stored base tree is larger than the allowed size")
        data = json.loads(raw.decode("utf-8"))
    except UpgradeError:
        raise
    except (zlib.error, ValueError, UnicodeDecodeError) as exc:
        raise UpgradeError("baseline_unreadable", "the stored base tree cannot be read") from exc
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise UpgradeError("baseline_unreadable", "the stored base tree has the wrong shape")
    for path in data:
        if not safe_path(path):
            raise UpgradeError("baseline_unreadable", "the stored base tree names an unsafe path")
    return non_custom(data)


# -- semver ------------------------------------------------------------------------------------
def _parse(version: str) -> tuple[int, int, int] | None:
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", version.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)


def classify_bump(old: str | None, new: str | None) -> str | None:
    """patch | minor | major, or None when nothing changed. A new block is minor, a removed one major,
    a downgrade or an unparsable version major (the conservative answer)."""
    if old == new:
        return None
    if old is None:
        return "minor"
    if new is None:
        return "major"
    if "-" in old.strip() or "-" in new.strip():
        return "major"  # pre-release tags are not comparable: conservative
    a, b = _parse(old), _parse(new)
    if a is None or b is None or b < a:
        return "major"
    if a[0] != b[0]:
        return "major"
    if a[1] != b[1]:
        return "minor"
    return "patch"


def block_changes(base: dict[str, str], current: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for block in sorted(set(base) | set(current)):
        bump = classify_bump(base.get(block), current.get(block))
        if bump is not None:
            out.append({"block": block, "from": base.get(block), "to": current.get(block), "bump": bump})
    return out


# -- unified diff ------------------------------------------------------------------------------
def _lines(text: str) -> list[str]:
    parts = text.split("\n")  # only \n ends a line (str.splitlines would also split on \r, \x0c, ...)
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def git_blob_hash(content: str) -> str:
    data = content.encode("utf-8")
    return hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False).hexdigest()  # noqa: S324


def file_diff(path: str, old: str | None, new: str | None) -> str:
    """One git-style diff section. `old` None = new file, `new` None = deleted file."""
    if not safe_path(path):
        raise UpgradeError("unsafe_path", "refusing to write a patch for an unsafe path")
    head = [f"diff --git a/{path} b/{path}\n"]
    if old is None:
        head.append("new file mode 100644\n")
    elif new is None:
        head.append("deleted file mode 100644\n")
    old_id = _NULL_HASH if old is None else git_blob_hash(old)
    new_id = _NULL_HASH if new is None else git_blob_hash(new)
    head.append(f"index {old_id}..{new_id}" + (" 100644\n" if old is not None and new is not None else "\n"))
    old_lines = [] if old is None else _lines(old)
    new_lines = [] if new is None else _lines(new)
    if old_lines == new_lines:
        return "".join(head)  # empty new/deleted file: header only
    head.append("--- " + ("/dev/null" if old is None else f"a/{path}") + "\n")
    head.append("+++ " + ("/dev/null" if new is None else f"b/{path}") + "\n")
    body: list[str] = []
    diff = difflib.unified_diff(old_lines, new_lines, n=3, lineterm="\n")
    for line in list(diff)[2:]:
        body.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(head + body)


# -- SBOM --------------------------------------------------------------------------------------
_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


def _requirement(line: str) -> tuple[str, str] | None:
    line = line.split("#", 1)[0].split(" --hash", 1)[0].strip().rstrip("\\").strip()
    if not line or line.startswith("-"):
        return None
    m = _REQ.match(line)
    if not m:
        return None
    return m.group(1).lower().replace("_", "-"), m.group(3).split(";", 1)[0].strip()


def parse_dependencies(tree: FileTree) -> dict[str, str]:
    """name -> version spec from requirements*.txt and pyproject.toml (project + optional dependencies)."""
    deps: dict[str, str] = {}
    for path in sorted(tree):
        if "/" not in path and path.startswith("requirements") and path.endswith(".txt"):
            for line in tree[path].splitlines():
                req = _requirement(line)
                if req:
                    deps[req[0]] = req[1]
        elif path == "pyproject.toml":
            try:
                project = tomllib.loads(tree[path]).get("project", {})
            except tomllib.TOMLDecodeError:
                continue
            groups = [project.get("dependencies", [])] + list(project.get("optional-dependencies", {}).values())
            for group in groups:
                for item in group:
                    req = _requirement(str(item))
                    if req:
                        deps[req[0]] = req[1]
    return deps


def sbom_diff(base: FileTree, new: FileTree) -> dict[str, list[dict[str, str | None]]]:
    a, b = parse_dependencies(base), parse_dependencies(new)
    return {
        "added": [{"name": n, "spec": b[n]} for n in sorted(b.keys() - a.keys())],
        "removed": [{"name": n, "spec": a[n]} for n in sorted(a.keys() - b.keys())],
        "changed": [{"name": n, "from": a[n], "to": b[n]} for n in sorted(a.keys() & b.keys()) if a[n] != b[n]],
    }


# -- the plan ----------------------------------------------------------------------------------
@dataclass
class UpgradePlan:
    files: list[dict[str, str]] = field(default_factory=list)  # {path, zone, change}
    kept: list[str] = field(default_factory=list)  # custom-zone paths, never touched
    patch_text: str = ""
    sbom: dict[str, list[dict[str, str | None]]] = field(default_factory=dict)
    migrations: list[dict[str, str]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.files


def plan_upgrade(base_tree: FileTree, new_tree: FileTree) -> UpgradePlan:
    """Classify every difference per zone and build the patch. Custom-zone paths (in either tree) are
    listed in `kept` only: they never appear in `files` or `patch_text`."""
    kept = sorted({p for p in (*base_tree, *new_tree) if zone_for(p) == "custom"})
    base, new = non_custom(base_tree), non_custom(new_tree)
    plan = UpgradePlan(kept=kept)
    sections: list[str] = []
    for path in sorted(base.keys() | new.keys()):
        old, cur = base.get(path), new.get(path)
        if old == cur:
            continue
        change = "added" if old is None else "removed" if cur is None else "modified"
        plan.files.append({"path": path, "zone": zone_for(path), "change": change})
        sections.append(file_diff(path, old, cur))
    plan.patch_text = "".join(sections)
    plan.sbom = sbom_diff(base, new)
    plan.migrations = [
        {"path": f["path"], "change": f["change"]}
        for f in plan.files
        if re.match(r"^alembic/versions/[^/]+\.py$", f["path"])
    ]
    return plan


def auto_apply_eligible(
    changes: list[dict[str, Any]],
    files: list[dict[str, str]],
    migrations: list[dict[str, str]],
    scorecard_passing: bool,
    sbom: dict[str, Any] | None = None,
    generator_bump: str | None = None,
) -> bool:
    """A flag only; nothing merges by itself. Never with a major bump, never on a failing scorecard, never
    with a migration. With block changes every bump must be patch; with none, only generated-zone edits."""
    if not scorecard_passing or migrations:
        return False
    # any dependency change or removed file or non-patch generator bump needs a person
    if sbom and any(sbom.get(k) for k in sbom):
        return False
    if generator_bump not in (None, "patch"):
        return False
    if any(f["change"] == "removed" for f in files):
        return False
    if any(c["bump"] == "major" for c in changes):
        return False
    if changes:
        return all(c["bump"] == "patch" for c in changes)
    return bool(files) and all(f["zone"] == "generated" for f in files)
