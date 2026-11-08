"""C0-F3: the committed OpenAPI snapshot the frontend drift test reads must match the app."""

import json
from pathlib import Path

from app.main import app

SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend" / "e2e" / "openapi.json"


def test_frontend_openapi_snapshot_is_current() -> None:
    expected = json.dumps(app.openapi(), indent=1, sort_keys=True) + "\n"
    assert SNAPSHOT.read_text() == expected, (
        "frontend/e2e/openapi.json is stale; run `PYTHONPATH=. uv run python scripts/dump_openapi.py`, "
        "then `npm --prefix frontend run test` to see what the frontend must follow"
    )
