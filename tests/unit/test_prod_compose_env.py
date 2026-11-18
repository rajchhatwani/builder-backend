"""F-1142/F-1143: docker-compose.prod.yml (+ sandbox overlay) must satisfy the app's startup checks."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from app.config import Settings
from app.core import rls
from app.core.production_checks import production_problems

ROOT = Path(__file__).resolve().parents[2]
_PLACEHOLDERS = {
    "SECRET_KEY": "s" * 40,
    "APP_DB_PASSWORD": "apppw-123456789",
    "POSTGRES_PASSWORD": "pgpw-123456789",
    "BB_DOMAIN": "app.example.com",
    "BB_RUNNER_TOKEN": "r" * 40,
    "BB_DATA": "/srv/bb",
}


def _subst(v: Any) -> str:
    s = str(v)

    def rep(m: re.Match[str]) -> str:
        name, default = m.group(1), m.group(2)
        return _PLACEHOLDERS.get(name, default or "")

    return re.sub(r"\$\{([A-Z_]+)(?::[-?]([^}]*))?\}", rep, s)


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!reset", lambda loader, node: None)


def _load(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / name).read_text(), Loader=_Loader)  # noqa: S506 - SafeLoader subclass


def _env(doc: dict[str, Any], svc: str) -> dict[str, str]:
    e = doc["services"][svc]["environment"]
    if isinstance(e, list):
        e = dict(x.split("=", 1) for x in e)
    return {k: _subst(v) for k, v in e.items()}


def _settings(env: dict[str, str]) -> Settings:
    kw: dict[str, Any] = {}
    fields = Settings.model_fields
    for k, v in env.items():
        name = k.removeprefix("BUILDER_").lower() if k.startswith("BUILDER_") else k.lower()
        if name in fields and v != "":
            kw[name] = json.loads(v) if v[0] in "[{" else v
    kw["key_provider_file"] = "/tmp/keys.txt"
    return Settings(_env_file=None, **kw)


def test_base_prod_compose_passes_startup_checks() -> None:
    s = _settings(_env(_load("docker-compose.prod.yml"), "api"))
    assert production_problems(s) == []
    assert rls.startup_problem(s) is None


def test_sandbox_overlay_env_passes_startup_checks() -> None:
    base = _env(_load("docker-compose.prod.yml"), "api")
    over = _env(_load("docker-compose.sandbox.yml"), "api")
    s = _settings({**base, **over})
    assert s.sandbox_runner_url and production_problems(s) == []
    assert rls.startup_problem(s) is None


def test_scheduler_shares_api_env_and_keys_are_settings_fields() -> None:
    doc = _load("docker-compose.prod.yml")
    assert _env(doc, "scheduler") == _env(doc, "api")
    for svc in ("api", "migrate", "db-role"):
        for k in _env(doc, svc):
            if k.startswith("BUILDER_") and k != "BUILDER_APP_DB_PASSWORD":  # read by the rls CLI only
                assert k.removeprefix("BUILDER_").lower() in Settings.model_fields, k


def test_sandbox_disabled_flag_skips_only_sandbox_checks() -> None:
    s = Settings(_env_file=None, environment="production", sandbox_disabled=True, key_provider="file",
                 key_provider_file="/x", public_api_url="https://a.b")
    assert production_problems(s) == []
    s2 = Settings(_env_file=None, environment="production", key_provider="file",
                  key_provider_file="/x", public_api_url="https://a.b")
    assert any("SANDBOX_RUNNER" in p for p in production_problems(s2))
