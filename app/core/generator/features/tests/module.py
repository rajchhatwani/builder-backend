"""The `tests` feature: conftest plus one smoke test per entity.

Each test walks the entity's enabled operations once (create, get, head, list with filter /
search / sort, patch, replace, delete) against a real database."""

from pathlib import Path

from app.core.generator.base import FileTree
from app.core.generator.context import EntityCtx, ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation import auth_tables, uses_keycloak

_TEMPLATES = Path(__file__).parent / "templates"

_FILTER_PROBE_TYPES = {"string", "integer", "bigint", "boolean", "enum"}
_SEARCH_PROBE_TYPES = {"string", "text"}


def creatable(entity: EntityCtx, project: ProjectCtx, seen: frozenset[str] = frozenset()) -> bool:
    """True if a row can be created through the API, including its required parents."""
    if "create" not in entity.ops or entity.name in seen:
        return False
    return all(
        creatable(project.entity_by_name[fk.target_entity], project, seen | {entity.name})
        for fk in entity.required_fks
    )


def _skip_reason(entity: EntityCtx, project: ProjectCtx) -> str | None:
    if creatable(entity, project):
        return None
    return (
        f"{entity.name} cannot be created through the API (create is disabled for it or for a "
        "required parent), so there is no smoke test to run"
    )


class TestsModule:
    name = "tests"

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        files: FileTree = {
            "tests/__init__.py": "",
            "tests/_prepare_db.py": read_verbatim(_TEMPLATES, "_prepare_db.py.tpl"),
            "tests/test__health.py": read_verbatim(_TEMPLATES, "test__health.py.tpl"),
        }
        tables = {e.table for e in project.entities} | {j.name for j in project.join_tables}
        if project.auth is not None:
            # The provider lock row is written at start-up, not per test, so it is not emptied.
            tables |= set(auth_tables(project.auth)) - {"auth_provider_lock"}
            if project.auth.token_store == "redis":
                tables.discard("auth_refresh_tokens")  # refresh tokens live in Redis
        files["tests/conftest.py"] = render_template(
            self._env,
            "conftest.py.j2",
            tables=sorted(tables),
            auth=project.auth is not None,
            keycloak=uses_keycloak(project.auth),
        )
        creatable_entities = [e for e in project.entities if creatable(e, project)]
        files["tests/_factories.py"] = render_template(
            self._env, "_factories.py.j2", entities=creatable_entities
        )
        for entity in project.entities:
            files[f"tests/test_{entity.table}.py"] = render_template(
                self._env, "entity_test.py.j2", **self._entity_context(entity, project)
            )
        return files

    def _entity_context(self, entity: EntityCtx, project: ProjectCtx) -> dict[str, object]:
        fields = {f.name: f for f in entity.fields}
        filter_probe = next(
            (
                name
                for name in entity.filterable_names
                if name in fields and fields[name].type in _FILTER_PROBE_TYPES
            ),
            None,
        )
        search_probe = next(
            (
                name
                for name in entity.searchable
                if name in fields and fields[name].type in _SEARCH_PROBE_TYPES
            ),
            None,
        )
        patch_field = next((f.name for f in entity.fields if f.patchable), None)
        return {
            "e": entity,
            "skip_reason": _skip_reason(entity, project),
            "gated": bool(entity.access),
            "filter_probe": filter_probe,
            "search_probe": search_probe,
            "patch_field": patch_field,
            "replace_args": "".join(
                f', {fk.column}=created["{fk.column}"]' for fk in entity.required_fks
            ),
            "has_required_input": any(f.required for f in entity.fields)
            or bool(entity.required_fks),
        }
