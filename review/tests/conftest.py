"""Reuse the repo's API-test fixtures (client_for, make_user, anon_client, session_factory, ...)
without editing any existing file.  Run from the repo root:

    uv run python -m pytest review/tests -p no:cacheprovider -q

A throwaway Postgres container is started by the repo fixtures (or set TEST_DATABASE_URL to a
disposable DB).
"""
from tests.api.conftest import *  # noqa: F401,F403
from tests.api.conftest import (  # noqa: F401
    _clean_tables,
    _fast_hashing_and_fresh_limiter,
    _secret_key,
    _unlimited_personal_plan,
)
