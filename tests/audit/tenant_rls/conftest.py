"""Reuse the API-test fixtures (Postgres container, clients, cleanup) for the tenant_rls attacks."""

import tests.api.conftest as _api

# Re-export every fixture, including the underscore-named autouse ones (a star import skips them).
globals().update({k: v for k, v in vars(_api).items() if not k.startswith("__")})
