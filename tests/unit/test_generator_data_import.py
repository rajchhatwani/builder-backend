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


def test_m1_imported_rows_run_after_save_and_after_commit_hooks() -> None:
    service = _spec_files()["app/imports/service.py"]
    assert 'run_stage("after_save", repo.hooks, ctx)' in service
    assert 'run_stage("after_commit", repo.hooks, ctx, fail_closed=False)' in service
    assert "ctx.item = item" in service
    # after_save runs between the flush and the commit; after_commit after it
    assert service.index("repo._flush()") < service.index('"after_save"') < service.index("repo._commit()")
    assert service.index("repo._commit()") < service.index('"after_commit"')
    assert "rollback" in service[service.index('"after_save"') :]


def test_m2_dedupe_uses_bounded_in_queries_and_never_a_silent_limit() -> None:
    service = _spec_files()["app/imports/service.py"]
    assert "MAX_EXISTING_ROWS" not in service and "_existing_keys" not in service
    assert "PROBE_CHUNK" in service and ".in_(" in service and "import_dedupe_too_large" in service
    assert "_scope(repo)" in service and "repo._alive()" in service and "tenant_id" in service


def test_l4_dry_run_runs_the_same_prepare_checks() -> None:
    service = _spec_files()["app/imports/service.py"]
    assert "if not dry_run:\n            try:" not in service
    assert "await _prepare(repo, values)" in service
    assert "Writes nothing" in service


def test_l3_a_key_over_an_unreadable_field_is_never_called_duplicate() -> None:
    files = _spec_files()
    assert "import_row_rejected" in files["app/imports/service.py"] and 'key[0] == "guarded"' in files["app/imports/service.py"]
    ns: dict[str, object] = {"__name__": "csv_import_under_test"}
    exec(compile(files["app/imports/csv_import.py"], "csv_import.py", "exec"), ns)  # noqa: S102
    entity = ns["SpecEntity"]("T", (ns["SpecField"]("code", "string", unique=True), ns["SpecField"]("name", "string")))
    keys = ns["DedupeKeys"](entity, frozenset({"code"}))  # the caller may not read `code`
    with_hidden = keys.of({"code": "A1", "name": "x"})
    assert with_hidden[0] == "guarded"
    # a key over the readable fields only: two rows differing only in the hidden value are the same plain key
    assert keys.of({"code": None, "name": "x"}) == keys.of({"code": None, "name": "x"})
    assert keys.of({"code": None, "name": "x"})[0] == "plain"
    assert keys.of({"code": "A1", "name": "x"}) != keys.of({"code": "A2", "name": "x"})  # guarded: full record
    open_keys = ns["DedupeKeys"](entity, frozenset())
    assert open_keys.of({"code": "A1", "name": "x"})[0] == "plain"
    assert open_keys.probe_names({"code": "A1", "name": "x"}) == ("code",)
    assert keys.probe_names({"code": None, "name": "x"}) == ("name",)  # never probes on a hidden column


def test_l8_the_router_limits_the_body_before_it_is_spooled() -> None:
    router = _spec_files()["app/imports/router.py"]
    assert "route_class=_BodyLimitRoute" in router and "BODY_LIMIT = _ci.MAX_BYTES" in router
    assert 'request.headers.get("content-length"' in router
    assert router.index("class _BodyLimitRoute") < router.index("async def import_tickets")
    assert "import_too_large" in router


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
