"""A-008 (B2-6): a refused credential is not echoed back and is not written to any log. Fake secret is split."""

import json
import logging
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import make_project

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"
FAKE = "sk_" "live_" "4eC39HqLyjWDarjtT1zdp7dc"


async def test_a_refused_secret_is_in_neither_the_response_nor_the_logs(
    client: AsyncClient, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    pid = await make_project(client)
    nf = json.loads((FIXTURES / "notifications_orders.json").read_text(encoding="utf-8"))["notifications"]
    nf["types"][0]["templates"][0]["body"] = f"key {FAKE} {{{{ name }}}}"
    with caplog.at_level(logging.DEBUG):
        r = await client.put(f"/projects/{pid}/behavior/notifications", json={"notifications": nf})
        whole = await client.get(f"/projects/{pid}/spec")
    assert r.status_code == 422 and r.json()["code"] == "secret_in_spec"
    assert FAKE not in r.text and FAKE[-12:] not in r.text
    assert FAKE not in whole.text  # and it was never stored
    out = capsys.readouterr()
    logged = caplog.text + out.out + out.err
    assert FAKE not in logged and FAKE[-12:] not in logged
