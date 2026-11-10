"""The generated CSV import / export (CP-4F2 WP-A): POST /<entity>/import and GET /<entity>/export.csv for
entities with a create op. Specs without a create op render exactly as before."""

import ast
import json
from pathlib import Path

from app.core.generator import generate
from app.core.spec_models import Spec

TESTS = Path(__file__).resolve().parent.parent
FIXTURES = TESTS / "fixtures" / "specs"


def _spec(name: str = "search") -> Spec:
    return Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def test_module_and_routes_are_rendered() -> None:
    files = generate(_spec())
    for path in ("__init__", "csv_import", "fields", "service", "router"):
        ast.parse(files[f"app/imports/{path}.py"])
    router = files["app/imports/router.py"]
    assert '"/tickets/import"' in router and '"/tickets/export.csv"' in router
    assert '_ACCESS_tickets["create"]' in router and '_ACCESS_tickets["list"]' in router
    assert "_fx.hidden_write(" in router and "_fx.hidden_read(" in router
    assert "neutralize_formula" in router and "X-Export-Truncated" in router
    main = files["app/main.py"]
    assert main.index("include_router(_imports_router)") < main.index("include_router(tickets_router)")
    assert "python-multipart" in files["requirements.txt"]


def test_parser_keeps_the_platform_caps_and_checks() -> None:
    csv_import = _spec_files()["app/imports/csv_import.py"]
    for needle in ("MAX_BYTES = 5 * 1024 * 1024", "MAX_ROWS = 20_000", "MAX_COLUMNS = 100", "NUL bytes", "utf-8-sig"):
        assert needle in csv_import
    assert "def neutralize_formula" in csv_import and "def dedupe_key" in csv_import
    assert "app.core.spec_models" not in csv_import


def test_field_access_and_dedupe_are_enforced_in_the_service() -> None:
    service = _spec_files()["app/imports/service.py"]
    assert "field_not_writable" in service
    assert "MAX_REJECTED_SHOWN = 100" in service
    assert "hidden_headers" in service  # hidden fields are never echoed
    assert "repo._flush()" in service and "repo._commit()" in service  # one transaction
    assert "repo._alive()" in service  # existing rows are read through the access scope


def test_the_generated_files_compile() -> None:
    for name, source in _spec_files().items():
        if name.startswith("app/imports/") and name.endswith(".py"):
            compile(source, name, "exec")


def test_no_create_operation_means_no_module() -> None:
    spec = _spec()
    spec.entities[0].options.operations = ["list", "get"]
    assert spec.auth is not None
    spec.auth.permissions = [p for p in spec.auth.permissions if p.operation in ("list", "get")]
    files = generate(spec)
    assert not any(p.startswith("app/imports/") for p in files)
    assert not any("_imports_router" in t or "python-multipart" in t for t in files.values())


def _spec_files() -> dict[str, str]:
    return generate(_spec())
