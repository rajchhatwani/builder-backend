"""CP-6C: GET /projects/{id}/compliance/controls and /evidence."""

import hashlib
import io
import json
import zipfile

from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor


async def _project(client: AsyncClient) -> str:
    pid = await make_project(client)
    block = {"enabled": False, "key_provider": "file", "fields": []}
    r = await client.put(f"/projects/{pid}/behavior/regulated", json={"regulated": block, "expected_version": 0})
    assert r.status_code == 200, r.text
    return pid


async def test_controls_summary(client: AsyncClient) -> None:
    pid = await _project(client)
    r = await client.get(f"/projects/{pid}/compliance/controls", params={"framework": "soc2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["framework"] == "soc2"
    assert body["met"] + body["unmet"] + body["not_applicable"] == len(body["controls"]) >= 8
    enc = next(c for c in body["controls"] if c["id"] == "SOC2-CC6.7")
    assert enc["status"] == "unmet" and enc["tests"]
    allfw = await client.get(f"/projects/{pid}/compliance/controls")
    assert allfw.json()["framework"] == "all"


async def test_evidence_zip_downloads_and_verifies(client: AsyncClient) -> None:
    pid = await _project(client)
    r = await client.get(f"/projects/{pid}/compliance/evidence", params={"framework": "pci"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "evidence-pci.zip" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        manifest = json.loads(zf.read("MANIFEST.json"))["files"]
        assert manifest
        for name, digest in manifest.items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == digest


async def test_bad_framework_is_422(client: AsyncClient) -> None:
    pid = await _project(client)
    for path in ("controls", "evidence"):
        r = await client.get(f"/projects/{pid}/compliance/{path}", params={"framework": "iso"})
        assert r.status_code == 422, r.text
    assert (await client.get(f"/projects/{pid}/compliance/evidence")).status_code == 422


async def test_non_member_is_404_and_anonymous_401(client: AsyncClient, client_for: ClientFor, anon_client: AsyncClient) -> None:
    pid = await _project(client)
    other = await client_for("stranger@example.com")
    for path in ("controls", "evidence"):
        r = await other.get(f"/projects/{pid}/compliance/{path}", params={"framework": "soc2"})
        assert r.status_code == 404, r.text
    assert (await anon_client.get(f"/projects/{pid}/compliance/controls")).status_code == 401


async def test_evidence_is_identical_for_the_same_spec_and_honours_generated_at(client: AsyncClient) -> None:
    pid = await _project(client)
    url = f"/projects/{pid}/compliance/evidence"
    a = await client.get(url, params={"framework": "soc2"})
    b = await client.get(url, params={"framework": "soc2"})
    assert a.content == b.content
    stamped = await client.get(url, params={"framework": "soc2", "generated_at": "2026-02-03T04:05:06Z"})
    with zipfile.ZipFile(io.BytesIO(stamped.content)) as zf:
        assert json.loads(zf.read("MANIFEST.json"))["generated_at"] == "2026-02-03T04:05:06Z"
    bad = await client.get(url, params={"framework": "soc2", "generated_at": "yesterday"})
    assert bad.status_code == 422
