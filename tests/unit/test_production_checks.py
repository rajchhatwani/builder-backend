"""P4: production readiness refusals; local/test are unaffected."""

import pytest

from app.config import Settings
from app.core.production_checks import check_production_ready, production_problems

GOOD = dict(
    environment="production",
    sandbox_runner_url="http://127.0.0.1:9000",
    sandbox_runner_token="x" * 40,
    sandbox_runtime="runsc",
    preview_root="/srv/previews",
    preview_scheduler_enabled=True,
    key_provider="file",
    key_provider_file="/etc/bb/keys",
    public_api_url="https://api.example.com",
    database_url="postgresql+asyncpg://app:s3cret-pw@db.internal:5432/builder",
)


def mk(**over: object) -> Settings:
    return Settings(_env_file=None, **{**GOOD, **over})  # type: ignore[arg-type]


def test_pass_case() -> None:
    check_production_ready(mk())


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"sandbox_runner_url": None, "sandbox_runner_token": None}, "SANDBOX_RUNNER_URL"),
        ({"sandbox_runtime": "runc"}, "SANDBOX_RUNTIME"),
        ({"preview_root": None}, "PREVIEW_ROOT"),
        ({"preview_scheduler_enabled": False}, "SCHEDULER"),
        ({"key_provider": "env", "key_provider_file": None}, "KEY_PROVIDER"),
        ({"public_api_url": "http://localhost:8000"}, "ALLOWED_HOSTS"),
        ({"database_url": "postgresql+asyncpg://builder:builder@db.internal/builder"}, "DATABASE_URL"),
    ],
)
def test_refusals(over: dict[str, object], needle: str) -> None:
    with pytest.raises(RuntimeError) as e:
        check_production_ready(mk(**over))
    assert needle in str(e.value)
    assert "s3cret" not in str(e.value) and "xxxx" not in str(e.value)


def test_env_provider_override_and_hosts_and_loopback_db() -> None:
    assert production_problems(mk(key_provider="env", allow_env_key_provider=True)) == []
    assert production_problems(mk(public_api_url="http://localhost:8000", mcp_allowed_hosts=["api.internal"])) == []
    assert production_problems(mk(database_url="postgresql+asyncpg://builder:builder@localhost/builder")) == []


def test_local_test_and_unset_unaffected() -> None:
    assert production_problems(Settings(_env_file=None, environment="local")) == []
    assert production_problems(Settings(_env_file=None, environment="test")) == []
    assert production_problems(Settings(_env_file=None)) == []
