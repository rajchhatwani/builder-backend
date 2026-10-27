"""Reject NUL characters in request input before any handler or database sees it.

PostgreSQL text can't hold U+0000: a name, e-mail or SCIM `userName` containing one used to reach
the database and answer 500 (review F-003), on public endpoints too. One app-wide dependency
answers 422 instead, for the path, the query string and JSON / form bodies.
"""

import re

from fastapi import Request

from app.exceptions import AppError

# `\u0000` in JSON text, unless the backslash is itself escaped (`\\u0000` is a literal backslash).
_JSON_NUL = re.compile(rb"(?<!\\)(?:\\\\)*\\u0000")
_CHECKED_BODIES = ("application/json", "application/scim+json", "application/x-www-form-urlencoded")


def _refuse() -> AppError:
    return AppError(
        code="validation_error",
        message="NUL characters are not allowed in request input",
        status_code=422,
    )


async def reject_nul_characters(request: Request) -> None:
    if "\x00" in request.url.path or b"%00" in request.scope.get("query_string", b""):
        raise _refuse()
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in _CHECKED_BODIES:
        return
    body = await request.body()  # cached by Starlette: the handler reads the same bytes
    if b"\x00" in body or (content_type == "application/x-www-form-urlencoded" and b"%00" in body):
        raise _refuse()
    if content_type != "application/x-www-form-urlencoded" and _JSON_NUL.search(body):
        raise _refuse()
