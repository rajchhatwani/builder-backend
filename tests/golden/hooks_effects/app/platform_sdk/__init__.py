"""The platform SDK (generated): the only part of the platform a custom hook may import.

    from app.platform_sdk import log, clamp, find_rows

Pure hooks may use `log` and the helpers. `find_rows` (read-only lookups of the entities a hook
declares in `reads`) and `now` are for effect hooks. Effectful hooks (opt-in, trusted authors only) may also
call the effect functions they declare in `effects`, within their `effect_budget`. The gate `python -m app.platform_gate`
rejects every other import from the app.

The `reads` contract: a hook can only look at the entities it declares in `reads`, and what
`find_rows` returns is filtered by the access policies of the person whose request runs the hook,
exactly like the entity's own list endpoint (role permissions, owner / tenant / custom row rules,
abac / pbac policies, soft-deleted rows hidden, only the fields that endpoint returns). Declaring
`reads` never widens what that person may see; an entity they may not read raises `AccessDenied`.
"""

from app.auth.identity import Principal
from app.platform_sdk.effects import notify, send_email, send_sms
from app.platform_sdk.env import current_principal, find_rows, log, now
from app.platform_sdk.helpers import clamp, is_blank, pct_diff, slugify

__all__ = [
    "Principal",
    "clamp",
    "current_principal",
    "find_rows",
    "is_blank",
    "log",
    "notify",
    "now",
    "pct_diff",
    "send_email",
    "send_sms",
    "slugify",
]
