"""Audit B1-008 (F-0475): deploy docs must say the environment gate needs separate accounts."""

import json
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


@pytest.mark.parametrize("cloud", ["aws", "azure", "gcp"])
def test_step2_states_gate_needs_separate_accounts(cloud: str) -> None:
    raw = json.loads((FIXTURES / f"deploy_{cloud}.json").read_text(encoding="utf-8"))
    doc = generate(Spec.model_validate(raw))["docs/DEPLOYMENT.md"]
    step2 = doc.split("2. **Create the GitHub environments**")[1].split("3. **Set the variables**")[0]
    assert "separate" in step2 and "only" in step2
    assert "same account" in step2
