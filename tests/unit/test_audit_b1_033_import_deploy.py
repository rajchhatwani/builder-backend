"""Audit B1-033: data-import dedupe / mapping / lifecycle fixes and deploy template fixes."""

import __future__

from app.core.generator import generate
from app.core.spec_models import Spec

from tests.unit.test_generator_data_import import _spec_files


def _files() -> dict[str, str]:
    return _spec_files()


def _ci() -> dict[str, object]:
    ns: dict[str, object] = {"__name__": "csv_import_under_test"}
    exec(compile(_files()["app/imports/csv_import.py"], "csv_import.py", "exec"), ns)  # noqa: S102
    return ns


def test_f1064_plain_key_without_unique_ignores_hidden_read_fields() -> None:
    ns = _ci()
    ent = ns["SpecEntity"](
        "P",
        (
            ns["SpecField"]("name", "string"),
            ns["SpecField"]("salary", "integer"),
            ns["SpecField"]("note", "string"),
        ),
    )
    keys = ns["DedupeKeys"](ent, frozenset({"salary"}))
    a = keys.of({"name": "x", "salary": 5, "note": "n"})
    b = keys.of({"name": "x", "salary": 6, "note": "n"})
    assert a == b and a[0] == "plain"


def _mapping_fn() -> object:
    """Run the generated `_mapping` with stubs (the module's own imports need the generated app)."""
    import ast
    import json

    src = _files()["app/imports/service.py"]
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_mapping")
    const = (
        next(
            n
            for n in tree.body
            if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "MAX_MAPPING_CHARS"
        )
        if "MAX_MAPPING_CHARS" in src
        else None
    )

    class AppError(Exception):
        def __init__(self, code: str, message: str, status: int) -> None:
            super().__init__(message)
            self.code = code

    class _Ci:
        class ImportDataError(Exception):
            pass

        @staticmethod
        def suggest_mapping(*_: object) -> dict[str, str]:
            return {}

        @staticmethod
        def clean_mapping(loaded: object, *_: object) -> object:
            return loaded

    mod = ast.Module(body=([const] if const else []) + [fn], type_ignores=[])
    ns: dict[str, object] = {
        "json": json,
        "AppError": AppError,
        "ci": _Ci,
        "_file_error": lambda e: e,
        "MAX_MAPPING_CHARS": 100_000,
    }
    exec(
        compile(
            ast.fix_missing_locations(mod),
            "svc",
            "exec",
            flags=__future__.annotations.compiler_flag,
        ),
        ns,
    )  # noqa: S102
    ns["_AppError"] = AppError
    return ns


def test_f1070_deeply_nested_mapping_is_a_422_not_a_500() -> None:
    ns = _mapping_fn()
    for raw in ("[" * 200000, "x" * 200000):
        try:
            ns["_mapping"](raw, None, None)  # type: ignore[operator]
        except ns["_AppError"] as exc:  # type: ignore[misc]
            assert exc.code == "import_bad_mapping"
        else:
            raise AssertionError("accepted")


def _service_ns(stub: dict[str, object]) -> dict[str, object]:
    import ast

    tree = ast.parse(_files()["app/imports/service.py"])
    keep = {"_prepare", "_lock_scope", "run_import"}
    body = [
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name in keep
    ]
    ns: dict[str, object] = {
        "Any": object,
        "Callable": object,
        "Awaitable": object,
        "Repository": object,
        **stub,
    }
    flags = __future__.annotations.compiler_flag
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            "svc",
            "exec",
            flags=flags,
        ),
        ns,
    )  # noqa: S102
    return ns


def test_f1071_numbers_are_drawn_before_before_save_hooks() -> None:
    import asyncio

    seen: list[dict[str, object]] = []

    class Ctx:
        def __init__(self, values: dict[str, object]) -> None:
            self.values = values

    class Repo:
        owner_id = None
        tenant_id = None
        policy = None
        hooks = ()

        def _ctx(self, _op: str, values: dict[str, object]) -> Ctx:
            return Ctx(values)

        async def _pop_related(self, _out: object) -> dict[str, object]:
            return {}

        async def _check_references(self, _out: object) -> None:
            return None

        async def draw_numbers(self, data: dict[str, object]) -> dict[str, object]:
            return {**data, "no": 7}

    async def run_stage(_stage: str, _hooks: object, ctx: Ctx, **_: object) -> None:
        seen.append(dict(ctx.values))

    ns = _service_ns({"run_stage": run_stage, "HookContext": object})
    repo = Repo()
    prepared, ctx = asyncio.run(ns["_prepare"](repo, {"a": 1}, repo.draw_numbers))  # type: ignore[operator]
    assert seen == [{"a": 1, "no": 7}] and prepared["no"] == 7 and ctx.values["no"] == 7
    seen.clear()
    prepared, _ = asyncio.run(ns["_prepare"](repo, {"a": 1}))  # type: ignore[operator]  # dry run: no draw
    assert seen == [{"a": 1}] and "no" not in prepared


def test_f1069_a_real_import_takes_an_advisory_lock_before_the_probe() -> None:
    service = _files()["app/imports/service.py"]
    assert "pg_advisory_xact_lock" in service
    run = service[service.index("async def run_import") :]
    assert run.index("_lock_scope(repo, entity.name)") < run.index("await _probe(")
    assert "if not dry_run" in run[run.index("_lock_scope") - 60 : run.index("_lock_scope")]


def _deploy_issues(cloud: str, region: str, gb: int) -> list[tuple[str, str]]:
    from tests.unit.test_deploy_validation import issues, with_block

    raw = with_block(cloud=cloud, region=region)
    raw["deployment"]["environments"] = [{"name": "dev", "db_storage_gb": gb}]
    return issues(raw)


def test_f1068_aws_db_storage_is_bounded_for_rds() -> None:
    path = ("deployment.environments[0].db_storage_gb", "invalid_value")
    assert path in _deploy_issues("aws", "eu-west-1", 10)
    assert path in _deploy_issues("aws", "eu-west-1", 20000)
    assert path not in _deploy_issues("aws", "eu-west-1", 20)
    assert path not in _deploy_issues("aws", "eu-west-1", 16384)
    assert path in _deploy_issues("azure", "westeurope", 40000)


def _deploy_files(cloud: str) -> dict[str, str]:
    from tests.unit.test_deploy_validation import load

    raw = load({"aws": "deploy_aws", "azure": "deploy_azure"}[cloud])
    return generate(Spec.model_validate(raw))


def test_f1067_azure_storage_mb_is_rounded_to_an_allowed_size() -> None:
    db = next(v for k, v in _deploy_files("azure").items() if k.endswith("azure/database.tf"))
    assert "var.db_storage_gb * 1024\n" not in db
    assert "32768, 65536, 131072" in db and "s >= var.db_storage_gb * 1024" in db


def test_f1065_waf_counts_the_body_size_rule() -> None:
    waf = next(v for k, v in _deploy_files("aws").items() if k.endswith("aws/waf.tf"))
    assert 'name = "SizeRestrictions_BODY"' in waf and "count {}" in waf


def test_f1066_service_waits_for_the_database_url_secret_and_redeploys_when_short() -> None:
    files = _deploy_files("aws")
    ecs = next(v for k, v in files.items() if k.endswith("aws/ecs.tf"))
    assert "aws_secretsmanager_secret_version.database_url" in ecs[ecs.index("depends_on") :]
    wf = next(v for k, v in files.items() if k == ".github/workflows/deploy.yml")
    assert "--force-new-deployment" in wf and wf.index("--force-new-deployment") < wf.index(
        "Wait until the service"
    )
