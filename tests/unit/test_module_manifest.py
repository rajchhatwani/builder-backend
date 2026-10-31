"""B1-1: every generator block declares a manifest; the registry lists them all."""

import pytest

from app.core.generator.base import ModuleManifest
from app.core.generator.engine import default_modules, module_registry


def test_registry_lists_every_default_module_with_its_manifest() -> None:
    registry = module_registry()
    assert list(registry) == [m.name for m in default_modules()]
    assert all(isinstance(m, ModuleManifest) and m.version for m in registry.values())


def test_dependencies_exist_and_do_not_cycle() -> None:
    registry = module_registry()

    def walk(block: str, seen: tuple[str, ...]) -> None:
        assert block not in seen, f"dependency cycle: {seen + (block,)}"
        for dep in registry[block].depends_on:
            walk(dep, seen + (block,))

    for block in registry:
        walk(block, ())


def test_unknown_dependency_and_duplicate_id_are_rejected() -> None:
    class Fake:
        name = "fake"
        manifest = ModuleManifest(id="fake", version="1", depends_on=("nope",))

        def render(self, project: object) -> dict[str, str]:
            return {}

    with pytest.raises(RuntimeError, match="unknown block"):
        module_registry([Fake()])  # type: ignore[list-item]
    with pytest.raises(RuntimeError, match="duplicate"):
        module_registry([Fake(), Fake()])  # type: ignore[list-item]
