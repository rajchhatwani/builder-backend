"""Write the builder's OpenAPI schema to frontend/e2e/openapi.json (sorted, stable).

  PYTHONPATH=. uv run python scripts/dump_openapi.py          # rewrite the snapshot
  PYTHONPATH=. uv run python scripts/dump_openapi.py --check  # exit 1 when the snapshot is stale
"""

import json
import sys
from pathlib import Path

from app.main import app

TARGET = Path(__file__).resolve().parent.parent / "frontend" / "e2e" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text() != text:
            print("openapi.json is stale: run `PYTHONPATH=. uv run python scripts/dump_openapi.py`")
            raise SystemExit(1)
        print("openapi.json is current")
    else:
        TARGET.write_text(text)
        print(f"wrote {TARGET} ({len(text)} bytes)")
