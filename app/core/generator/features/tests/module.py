"""The `tests` feature: conftest plus one smoke test per entity.

Each test walks the entity's enabled operations once (create, get, head, list with filter /
search / sort, patch, replace, delete) against a real database."""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import EntityCtx, ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation import auth_tables, uses_keycloak
from app.core.validation_history import CH_TABLES, history_active
from app.core.validation_payments import PAYMENTS_TABLES, payments_active
from app.core.validation_runtime import RC_TABLES, runtime_config_active
from app.core.validation_seed import SEED_TABLES, seed_active
from app.core.validation_storage import STORAGE_TABLES, storage_active

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
    if entity.policy:
        return (
            f"access to {entity.name} is decided by authorization policies, so a generic smoke "
            "test cannot know who may do what; see tests/test_authz.py and docs/AUTHORIZATION.md"
        )
    if creatable(entity, project):
        return None
    return (
        f"{entity.name} cannot be created through the API (create is disabled for it or for a "
        "required parent), so there is no smoke test to run"
    )


class TestsModule:
    name = "tests"
    manifest = ModuleManifest(id="tests", version="1", depends_on=('crud',))

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
        payments = payments_active(project.spec) and project.auth is not None
        if payments:
            # The audit table is append-only (its trigger refuses TRUNCATE) and the mode lock is
            # written at start-up, so neither is emptied between tests.
            tables |= set(PAYMENTS_TABLES) - {"pay_audit_log", "pay_lock"}
        storage = storage_active(project.spec) and project.auth is not None
        if storage:
            # Same reason as the payments audit table: it is append-only and cannot be truncated.
            tables |= set(STORAGE_TABLES) - {"stor_audit_log"}
        if project.spec.state_machines:
            tables.add("state_transitions")
        if runtime_config_active(project.spec):
            tables |= set(RC_TABLES)
        if history_active(project.spec):
            tables |= set(CH_TABLES)
        if seed_active(project.spec):
            tables |= set(SEED_TABLES)
        files["tests/conftest.py"] = render_template(
            self._env,
            "conftest.py.j2",
            tables=sorted(tables),
            auth=project.auth is not None,
            keycloak=uses_keycloak(project.auth),
            payments=payments,
            storage=storage,
            file_entities=storage and any(e.file_fields for e in project.entities),
        )
        creatable_entities = [e for e in project.entities if creatable(e, project)]
        files["tests/_factories.py"] = render_template(
            self._env,
            "_factories.py.j2",
            entities=creatable_entities,
            uploads=any(e.file_fields for e in creatable_entities),
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
        range_probe = next(
            (f.name for f in entity.fields if f.type in ("integer", "bigint", "decimal")), None
        )
        return {
            "range_probe": range_probe,
            "e": entity,
            "skip_reason": _skip_reason(entity, project),
            "gated": bool(entity.access),
            "filter_probe": filter_probe,
            "search_probe": search_probe,
            "patch_field": patch_field,
            "replace_args": "".join(
                f', {fk.column}=created["{fk.column}"]' for fk in entity.required_fks
            ),
            "has_required_input": any(f.required and not f.managed for f in entity.fields)
            or bool(entity.required_fks),
        }
