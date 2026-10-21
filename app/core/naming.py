"""Pure identifier-derivation helpers. No FastAPI or DB imports (see PLAN.md section 5).

Phase 1's strict identifier validation (reserved words, injection checks) lands in
M2 alongside the spec/validation pipeline; these are just the deterministic
defaulting rules used when a client omits table_name/plural_path/slug.
"""

import re

_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")


def to_snake_case(name: str) -> str:
    return _CAMEL_BOUNDARY_RE.sub("_", name).lower()


def pluralize(word: str) -> str:
    lower = word.lower()
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if lower.endswith("y") and len(word) > 1 and lower[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def slugify(name: str) -> str:
    slug = _SLUG_INVALID_RE.sub("-", name.lower()).strip("-")
    return slug or "project"
