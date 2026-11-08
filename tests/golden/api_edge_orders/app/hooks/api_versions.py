"""Your API version transformers. Written once; the platform never overwrites this file.

A client that sends `API-Version: 2026-01-01` (or is pinned to it) gets the shape that version had.
The code always produces the NEWEST declared version's shape; for each newer version there may be a
transformer here that undoes that version's change. For a client on version V they run newest first for
every declared version after V. Keep them pure: no database, no network, no clock. Return the new body.

    def undo_rename(method: str, path: str, body: Any) -> Any:
        if path.startswith("/orders") and isinstance(body, dict) and "reference" in body:
            body["ref"] = body.pop("reference")
        return body

    TRANSFORMERS = {"2026-06-01": undo_rename}   # the version that introduced the rename

Lists and pages are plain JSON: handle `body["items"]` yourself. They apply to successful (2xx) JSON
responses only. A transformer that raises turns the response into a 500: it never leaks the new shape.
"""

from collections.abc import Callable
from typing import Any

TRANSFORMERS: dict[str, Callable[[str, str, Any], Any]] = {}
