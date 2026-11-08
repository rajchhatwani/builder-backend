"""A-003 (B3-9): the user-facing workspace write API refuses dependency manifests, like the agent does."""

import shutil
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import Settings
from tests.api.test_workspace_files import (  # noqa: F401  (fixtures)
    CUSTOM,
    _discard_workspaces,
    _mk,
    _sha,
    ws_settings,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

HAND_WRITTEN = [
    "app/custom/requirements.txt",
    "app/custom/pyproject.toml",
    "app/custom/package.json",
    "app/custom/constraints.txt",
    "tests/custom/requirements-dev.txt",
]


@pytest.mark.parametrize("rel", HAND_WRITTEN)
async def test_a_user_cannot_write_a_dependency_manifest_into_a_workspace(
    client: AsyncClient, ws_settings: Settings, rel: str
) -> None:
    pid, base, wt = await _mk(client, ws_settings)
    target = wt / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# empty\n")
    r = await client.put(
        f"{base}/files/content",
        json={"path": rel, "content": "left-pad==9.9.9\n", "expected_sha256": _sha("# empty\n")},
    )
    assert r.status_code == 403 and r.json()["code"] == "dependency_manifest_denied", r.text
    assert target.read_text() == "# empty\n"  # nothing was written


async def test_ordinary_custom_files_are_still_editable(client: AsyncClient, ws_settings: Settings) -> None:
    pid, base, wt = await _mk(client, ws_settings)
    r = await client.put(
        f"{base}/files/content",
        json={"path": CUSTOM, "content": "print('v2')\n", "expected_sha256": _sha("print('v1')\n")},
    )
    assert r.status_code == 200, r.text
    assert Path(wt / CUSTOM).read_text() == "print('v2')\n"
