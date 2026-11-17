"""Rewrite examples/commerce/backend from examples/commerce/spec.json (keeps the example in sync with the generator)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.generator import generate
from app.core.spec_models import Spec

ROOT = Path(__file__).resolve().parents[1] / "examples" / "commerce"


def main() -> None:
    spec = Spec.model_validate(json.loads((ROOT / "spec.json").read_text(encoding="utf-8")))
    files = generate(spec)
    backend = ROOT / "backend"
    shutil.rmtree(backend, ignore_errors=True)
    for rel, text in files.items():
        target = backend / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(f"wrote {len(files)} files to {backend}")


if __name__ == "__main__":
    main()
