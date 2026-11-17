"""An entity table named like a feature must not collide with that feature's test file."""

import json
from pathlib import Path

from app.core.generator import generate
from app.core.spec_models import Spec

SPEC = Path(__file__).parents[1] / "fixtures" / "specs" / "webhooks_orders.json"


def test_entity_named_webhooks_does_not_collide_with_the_webhooks_tests() -> None:
    data = json.loads(SPEC.read_text())
    data["entities"].append(
        {
            "name": "Hook",
            "table_name": "webhooks",
            "plural_path": "webhooks_list",
            "fields": [{"name": "title", "type": "string"}],
        }
    )
    spec = Spec.model_validate(data)
    files = generate(spec)
    assert "tests/test_webhooks.py" in files
    assert "tests/test_entity_webhooks.py" in files


def _gen(name: str, edit=None) -> dict:  # noqa: ANN001
    data = json.loads((SPEC.parent / f"{name}.json").read_text())
    if edit:
        edit(data)
    return generate(Spec.model_validate(data))


def _text(value: object) -> str:
    return value if isinstance(value, str) else value.decode()  # type: ignore[attr-defined]


def test_inbound_only_webhooks_generate_no_outgoing_api_tests() -> None:  # F-0512
    def edit(d: dict) -> None:
        d["webhooks"]["events"] = []

    text = _text(_gen("webhooks_orders", edit)["tests/test_webhooks.py"])
    assert "test_an_event_becomes_one_signed_delivery" not in text
    assert "test_a_tenant_never_sees_or_changes" not in text
    assert "test_an_unsigned_or_badly_signed_request_is_rejected" in text
    full = _text(_gen("webhooks_orders")["tests/test_webhooks.py"])
    assert "test_an_event_becomes_one_signed_delivery" in full


def test_resume_undo_clears_the_failed_compensate_record_and_the_test_reads_it() -> None:  # F-0513, F-0517
    files = _gen("workflows_orders")
    engine = _text(files["app/workflows/engine.py"])
    assert "sa.delete(StepRecord)" in engine and "StepRecord.phase == COMPENSATE" in engine
    tests = _text(files["tests/test_workflows.py"])
    assert 'phase == "compensate"' in tests
    assert "resume-undo" in tests and "purge_finished" in tests


def test_webhooks_housekeeping_is_scheduled_documented_and_validated() -> None:  # F-0514, F-0516
    files = _gen("webhooks_orders")
    assert "webhooks-maintenance:" in _text(files["Makefile"])
    assert "make webhooks-maintenance" in _text(files["README.md"])
    maintenance = _text(files["app/webhooks/maintenance.py"])
    assert "_retention_days" in maintenance and "RuntimeError" in maintenance
    assert "maintenance.purge" in _text(files["tests/test_webhooks.py"])


def test_subscription_description_refuses_control_characters() -> None:  # F-0515
    files = _gen("webhooks_orders")
    router = _text(files["app/webhooks/router.py"])
    assert router.count("field_validator(\"description\")(_clean_description)") == 2
    assert "a\\x00b" in _text(files["tests/test_webhooks.py"])
