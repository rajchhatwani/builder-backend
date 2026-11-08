"""S3-004/S3-005: approving needs the hash of what the reviewer saw. Older tests post bare
`{"approve": true}`; this fixture plays the careful reviewer (reads the approval, sends its hash).
A test that wants the raw call sends the `x-raw-decision` header."""

from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient, Response

_orig_post = AsyncClient.post


@pytest.fixture(autouse=True)
def reviewer_sends_hash(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def post(self: AsyncClient, url: Any, *args: Any, **kw: Any) -> Response:
        body = kw.get("json")
        headers = kw.get("headers") or {}
        if (
            str(url).endswith("/decision")
            and isinstance(body, dict)
            and body.get("approve") is True
            and "expected_payload_hash" not in body
            and "x-raw-decision" not in headers
        ):
            seen = await self.get(str(url).removesuffix("/decision"))
            if seen.status_code == 200 and seen.json().get("payload_hash"):
                kw["json"] = {**body, "expected_payload_hash": seen.json()["payload_hash"]}
        return await _orig_post(self, url, *args, **kw)

    monkeypatch.setattr(AsyncClient, "post", post)
    yield
