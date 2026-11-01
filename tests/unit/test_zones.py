"""B1-2: platform/zones.json tags every generated file."""

import json

from app.core.generator.engine import generate
from app.core.generator.zones import ZONE_NAMES, ZONES_PATH, zone_for
from tests.unit.test_generator import NAMES, load_spec


def test_every_generated_file_has_a_valid_zone() -> None:
    for name in NAMES:
        files = generate(load_spec(name))
        zones = json.loads(files[ZONES_PATH])["zones"]
        assert set(zones) == set(files) - {ZONES_PATH}, name
        assert set(zones.values()) <= set(ZONE_NAMES), name


def test_classification_rules() -> None:
    assert zone_for("app/hooks/__init__.py") == "custom"
    assert zone_for("app/custom_routers/x.py") == "custom"
    assert zone_for("README.md") == "seeded"
    assert zone_for("app/main.py") == "generated"
    assert zone_for("something/unknown.txt") == "generated"  # fail closed


def test_hook_stubs_are_custom_and_the_generated_hook_files_are_not() -> None:
    assert zone_for("app/custom/hooks/match_invoice.py") == "custom"
    assert zone_for("app/custom/__init__.py") == "custom"
    assert zone_for("tests/custom/test_mine.py") == "custom"
    for generated in (
        "app/hooks_gen/contracts.py",
        "app/hooks_gen/registry.py",
        "app/platform_sdk/__init__.py",
        "app/platform_gate.py",
        "platform/hooks.json",
    ):
        assert zone_for(generated) == "generated"


def test_hook_files_are_tagged_in_the_manifest_of_a_project_with_hooks() -> None:
    files = generate(load_spec("hooks_invoice"))
    zones = json.loads(files[ZONES_PATH])["zones"]
    assert zones["app/custom/hooks/match_invoice.py"] == "custom"
    assert zones["app/custom/hooks/notify_approved.py"] == "custom"
    assert zones["app/hooks_gen/contracts.py"] == "generated"
    assert zones["app/hooks_gen/registry.py"] == "generated"
    assert zones["platform/hooks.json"] == "generated"
    assert set(zones) == set(files) - {ZONES_PATH}


def test_a_project_without_hooks_has_none_of_the_hook_files() -> None:
    files = generate(load_spec("flow_invoices"))
    assert not [p for p in files if "hooks_gen" in p or "platform_sdk" in p or p == "app/platform_gate.py"]
