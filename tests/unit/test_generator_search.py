"""The generated search endpoint (CP-4F1 WP2): GET /<entity>/search for entities with a list op and searchable
fields, FTS by default, OpenSearch switch. Specs without such an entity render exactly as before."""

import ast
import json
from pathlib import Path

from app.core.generator import generate
from app.core.spec_models import Spec

TESTS = Path(__file__).resolve().parent.parent
FIXTURES = TESTS / "fixtures" / "specs"
GOLDEN = TESTS / "golden"


def _spec(name: str = "search") -> Spec:
    return Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def test_search_module_and_route_are_rendered() -> None:
    files = generate(_spec())
    for path in ("config", "adapters", "service", "hooks", "router", "__init__"):
        ast.parse(files[f"app/search/{path}.py"])
    router = files["app/search/router.py"]
    assert '"/tickets/search"' in router
    assert '_ACCESS_tickets["list"]' in router  # the list operation's own access dependency
    assert "response_model_exclude_unset=True" in router and "_fx.hidden_read(" in router
    assert "le=100" in router and "max_length=200" in router
    main = files["app/main.py"]
    assert "_search_config.check_boot()" in main
    assert main.index("include_router(_search_router)") < main.index("include_router(tickets_router)")
    assert "_search_hooks.attach(" in files["app/crud/tickets.py"]
    assert "SEARCH_BACKEND" in files[".env.example"] and "## Search" in files["README.md"]


def test_the_engine_is_in_the_database_query_not_in_python() -> None:
    service = generate(_spec())["app/search/service.py"]
    assert "repo._alive()" in service  # soft delete, owner / tenant scope and policy
    assert "to_tsvector" in service and "plainto_tsquery" in service
    assert "repo._col(\"id\").in_(ids), *conditions" in service  # opensearch ids are re-read through the scope
    assert "f\"{q}" not in service and "% q" not in service  # q is only ever a bound parameter


def test_opensearch_fails_closed_and_the_fake_is_marked_test_only() -> None:
    files = generate(_spec())
    config = files["app/search/config.py"]
    assert "needs SEARCH_OPENSEARCH_URL" in config and "refused in production" in config
    assert "SEARCH_OPENSEARCH_API_KEY" in files["app/search/adapters.py"]
    assert "logger" in files["app/search/hooks.py"] and "API_KEY" not in files["app/search/hooks.py"]


def test_an_entity_without_searchable_fields_gets_nothing() -> None:
    spec = _spec()
    spec.entities[0].options.searchable = []
    files = generate(spec)
    assert not any(p.startswith("app/search/") for p in files)
    assert not any(("_search" in t or "SEARCH_BACKEND" in t) for t in files.values())


def test_an_entity_without_a_list_operation_gets_nothing() -> None:
    spec = _spec()
    spec.entities[0].options.operations = ["get", "create"]
    assert spec.auth is not None
    spec.auth.permissions = [p for p in spec.auth.permissions if p.operation in ("get", "create")]
    files = generate(spec)
    assert not any(p.startswith("app/search/") for p in files)


def test_specs_without_searchable_entities_match_their_goldens() -> None:
    for name in ("desk_auth", "events_orders"):
        files = generate(_spec(name))
        golden = GOLDEN / name
        expected = {
            p.relative_to(golden).as_posix(): p.read_text(encoding="utf-8")
            for p in golden.rglob("*")
            if p.is_file()
        }
        assert files == expected, name
        assert not any(p.startswith("app/search/") for p in files)
