"""S2-018: a viewer-level download never carries decrypted owner-only auth secrets."""

import pytest

from app.services import generation_service
from tests.api._auth_helpers import make_auth, make_entity, make_project
from tests.api.conftest import ClientFor, add_to_project_org

# split so the source never holds a whole secret-shaped literal
PASSWORD = "smtp-" + "pass-" + "QQ7"
USER = "mail" + "er-QQ7"


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Records what the generator is handed (runs the real generator)."""
    captured: list[str | None] = []
    real = generation_service.generate

    def spy(spec):  # type: ignore[no-untyped-def]
        captured.append(spec.auth.secrets.smtp_password if spec.auth is not None else None)
        return real(spec)

    monkeypatch.setattr(generation_service, "generate", spy)
    return captured


async def test_viewer_download_has_no_decrypted_secret_owner_still_gets_them(
    client_for: ClientFor, seen: list[str | None]
) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    p = await make_project(owner)
    await make_entity(owner, p)
    await make_auth(owner, p)
    put = await owner.put(
        f"/projects/{p}/auth/secrets", json={"smtp": {"username": USER, "password": PASSWORD}}
    )
    assert put.status_code == 200, put.text
    await add_to_project_org(p, "viewer@example.com")
    r = await owner.post(
        f"/projects/{p}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert r.status_code == 201, r.text

    got = await viewer.get(f"/projects/{p}/generate/download")
    assert got.status_code == 200, got.text
    assert seen == [None]  # nothing injected for a viewer

    got = await owner.get(f"/projects/{p}/generate/download")
    assert got.status_code == 200, got.text
    assert seen == [None, PASSWORD]  # owner path unchanged
