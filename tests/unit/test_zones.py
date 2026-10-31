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
