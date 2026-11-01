"""B2-11: apply_section stores a single-object block (and null) and bumps only its own version."""

import json
from pathlib import Path

from app.core.spec_models import Spec
from app.models.behavior_config import ProjectBehavior
from app.services.behavior_service import BLOCKS, SECTIONS, apply_section, section_version

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "specs" / "combined_async.json"


def test_block_stored_versioned_and_removed() -> None:
    spec = Spec.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    row = ProjectBehavior(sections={}, version=1)
    assert spec.jobs is not None
    apply_section(row, "jobs", spec.jobs)
    assert row.sections["jobs"] == spec.jobs.model_dump(mode="json")
    assert section_version(row, "jobs") == 1 and section_version(row, "events") == 0
    apply_section(row, "jobs", None)
    assert row.sections["jobs"] is None and section_version(row, "jobs") == 2


def test_every_block_is_a_section_and_a_spec_field() -> None:
    assert set(BLOCKS) <= set(SECTIONS) and set(BLOCKS) <= set(Spec.model_fields)
