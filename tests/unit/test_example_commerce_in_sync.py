"""examples/commerce/backend must be exactly what the generator renders for examples/commerce/spec.json.

Regenerate with: PYTHONPATH=. uv run python scripts/regen_example_commerce.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.generator import generate
from app.core.spec_models import Spec

ROOT = Path(__file__).resolve().parents[2] / "examples" / "commerce"


def test_commerce_example_backend_matches_generator() -> None:
    spec = Spec.model_validate(json.loads((ROOT / "spec.json").read_text(encoding="utf-8")))
    files = generate(spec)
    backend = ROOT / "backend"
    on_disk = {
        p.relative_to(backend).as_posix()
        for p in backend.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert on_disk == set(files), (sorted(set(files) - on_disk)[:5], sorted(on_disk - set(files))[:5])
    differing = [k for k, v in files.items() if (backend / k).read_text(encoding="utf-8") != v]
    assert not differing, differing[:5]
