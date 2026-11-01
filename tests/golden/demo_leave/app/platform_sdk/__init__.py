"""The platform SDK (generated): the only part of the platform a custom hook may import.

    from app.platform_sdk import log, clamp, find_rows

Pure hooks may use `log` and the helpers. `find_rows` (read-only lookups of the entities a hook
declares in `reads`) and `now` are for effect hooks. The gate `python -m app.platform_gate`
rejects every other import from the app.
"""

from app.auth.identity import Principal
from app.platform_sdk.env import current_principal, find_rows, log, now
from app.platform_sdk.helpers import clamp, is_blank, pct_diff, slugify

__all__ = [
    "Principal",
    "clamp",
    "current_principal",
    "find_rows",
    "is_blank",
    "log",
    "now",
    "pct_diff",
    "slugify",
]
