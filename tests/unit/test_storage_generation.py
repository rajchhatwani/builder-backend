"""What the generator emits for a project with file storage: the files, valid compose, pinned
images, the dependency floors, the migration chain, and the guarantee that nothing secret is
ever rendered."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.generator import generate
from app.core.generator.features.storage.module import CLAMAV_IMAGE, DEV_S3_IMAGE
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
NAMES = ["storage_s3", "storage_tenant", "storage_payments"]

SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:secret_access_key|access_key_id)\s*[:=]\s*['\"][A-Za-z0-9/+]{12,}"),
]
EICAR_START = "X5O!P%@AP"


def load(name: str) -> Spec:
    return Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=NAMES)
def project(request: pytest.FixtureRequest) -> tuple[Spec, dict[str, str]]:
    spec = load(request.param)
    return spec, generate(spec)


def test_no_secret_is_ever_rendered(project: tuple[Spec, dict[str, str]]) -> None:
    _, files = project
    leaks = [
        f"{path}: {pattern.pattern}"
        for path, content in files.items()
        for pattern in SECRET_PATTERNS
        if pattern.search(content)
    ]
    assert leaks == []


def test_the_real_antivirus_test_string_is_not_shipped(project: tuple[Spec, dict[str, str]]) -> None:
    """A file holding it would be quarantined by the developer's own antivirus."""
    _, files = project
    assert [p for p, content in files.items() if EICAR_START in content] == []


def test_the_storage_files_are_generated(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    assert spec.storage is not None
    expected = {
        "app/storage/__init__.py",
        "app/storage/access.py",
        "app/storage/audit.py",
        "app/storage/backend.py",
        "app/storage/clamav.py",
        "app/storage/config.py",
        "app/storage/limits.py",
        "app/storage/maintenance.py",
        "app/storage/models.py",
        "app/storage/names.py",
        "app/storage/refs.py",
        "app/storage/router.py",
        "app/storage/schemas.py",
        "app/storage/service.py",
        "app/storage/sniff.py",
        "alembic/versions/0004_storage.py",
        "deploy/storage/STORAGE.md",
        "deploy/storage/bucket-policy.json",
        "deploy/storage/iam-policy.json",
        "deploy/storage/lifecycle.json",
        "docs/storage-security.md",
        "tests/fake_clamd.py",
        "tests/storage_support.py",
        "tests/test_storage_security.py",
        "tests/test_storage_sniff.py",
        "tests/test_storage_upload.py",
    }
    assert expected <= set(files)


def test_a_project_without_storage_has_none_of_it() -> None:
    for name in ("blog", "shop_auth", "payments_stripe", "keycloak_own"):
        files = generate(load(name))
        assert [p for p in files if "storage" in p] == [], name
        assert "boto3" not in files["requirements.txt"] or name == "shop_auth"
        assert "python-multipart" not in files["requirements.txt"]
        assert "clamav" not in files["docker-compose.yml"]
        assert "stor_" not in files["tests/conftest.py"]


def test_dependencies_have_the_researched_floors(project: tuple[Spec, dict[str, str]]) -> None:
    _, files = project
    lines = files["requirements.txt"].splitlines()
    assert "python-multipart>=0.0.22" in lines  # fixes CVE-2024-24762, -53981 and 2026-24486
    assert "boto3>=1.38.0" in lines
    assert len([ln for ln in lines if ln.startswith("boto3")]) == 1  # pip refuses duplicates


def test_the_migration_chain_is_linear(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    revisions = {
        path: re.search(r'down_revision: str \| None = (None|"\d+")', content).group(1)  # type: ignore[union-attr]
        for path, content in files.items()
        if path.startswith("alembic/versions/")
    }
    expected = {
        "alembic/versions/0001_initial.py": "None",
        "alembic/versions/0002_auth.py": '"0001"',
        "alembic/versions/0004_storage.py": '"0003"' if spec.payments else '"0002"',
    }
    if spec.payments:
        expected["alembic/versions/0003_payments.py"] = '"0002"'
    assert revisions == expected


def test_compose_runs_a_pinned_private_scanner(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    assert spec.storage is not None
    compose: dict[str, Any] = yaml.safe_load(files["docker-compose.yml"])
    clamav = compose["services"]["clamav"]
    assert clamav["image"] == CLAMAV_IMAGE and not CLAMAV_IMAGE.endswith(":latest")
    assert "ports" not in clamav  # clamd has no authentication: private network only
    assert "no-new-privileges:true" in clamav["security_opt"]
    limit = spec.storage.max_file_mb + 16
    env = clamav["environment"]
    assert env["CLAMD_CONF_StreamMaxLength"] == f"{limit}M"
    assert env["CLAMD_CONF_AlertExceedsMax"] == "yes"  # what cannot be scanned is not let through
    assert "clamav_db" in compose["volumes"]
    api_env = compose["services"]["api"]["environment"]
    assert api_env["CLAMD_HOST"].endswith("clamav}")


def test_the_dev_s3_server_exists_only_for_minio_projects(
    project: tuple[Spec, dict[str, str]],
) -> None:
    spec, files = project
    assert spec.storage is not None
    compose: dict[str, Any] = yaml.safe_load(files["docker-compose.yml"])
    services = compose["services"]
    if spec.storage.backend == "minio":
        store = services["objectstore"]
        assert store["image"] == DEV_S3_IMAGE and not DEV_S3_IMAGE.endswith(":latest")
        assert services["api"]["depends_on"]["objectstore"]["condition"] == "service_healthy"
        ports = store.get("ports", [])
        if spec.storage.download_mode == "presigned":
            assert ports and all(p.startswith("127.0.0.1:") for p in ports)  # loopback only
        else:
            assert ports == []
        for credential in ("STORAGE_ACCESS_KEY_ID", "STORAGE_SECRET_ACCESS_KEY"):
            assert ":?" in services["api"]["environment"][credential]  # required, no default
        assert "${STORAGE_ACCESS_KEY_ID:?" in store["environment"]["AWS_ACCESS_KEY_ID"]
    else:
        assert "objectstore" not in services and "objectstore_data" not in compose["volumes"]


def test_the_env_example_names_every_setting_and_holds_no_value(
    project: tuple[Spec, dict[str, str]],
) -> None:
    _, files = project
    env = files[".env.example"]
    for name in ("STORAGE_ACCESS_KEY_ID", "STORAGE_SECRET_ACCESS_KEY", "CLAMD_HOST", "STORAGE_SSE"):
        assert re.search(rf"^{name}=", env, re.M), name
    assert re.search(r"^STORAGE_SECRET_ACCESS_KEY=$", env, re.M)
    assert re.search(r"^STORAGE_ACCESS_KEY_ID=$", env, re.M)


def test_the_settings_in_the_spec_end_up_in_the_config(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    assert spec.storage is not None
    config = files["app/storage/config.py"]
    assert f"BUCKET = {spec.storage.bucket!r}" in config
    assert f"MAX_FILE_BYTES = {spec.storage.max_file_mb} * 1024 * 1024" in config
    assert f"DOWNLOAD_MODE = {spec.storage.download_mode!r}" in config
    assert f"AUDIT_RETENTION_DAYS = {spec.storage.security.audit_retention_days}" in config
    migration = files["alembic/versions/0004_storage.py"]
    assert f"make_interval(days => {spec.storage.security.audit_retention_days})" in migration
    for name, roles in spec.storage.roles.model_dump().items():
        listed = ", ".join(f'"{role}"' for role in roles)
        assert f"    {name!r}: ({listed}" in config, name


def test_main_wires_the_module_in(project: tuple[Spec, dict[str, str]]) -> None:
    _, files = project
    main = files["app/main.py"]
    assert "UploadSizeLimitMiddleware" in main
    assert "_storage_router" in main
    assert "get_storage_settings().check()" in main  # unsafe settings stop the app at start-up
    assert "_storage_models" in files["app/models/__init__.py"]


def test_file_fields_are_checked_on_every_write(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    file_fields = [
        (e.table_name, f.name) for e in spec.entities for f in e.fields if f.type == "file"
    ]
    refs = files["app/storage/refs.py"]
    for table, column in file_fields:
        assert f"({table!r}, {column!r})" in refs
        repo = files[f"app/crud/{table}.py"]
        assert "file_check = staticmethod(check_attachable)" in repo
        assert f'"{column}"' in repo
        assert f"{column}: _mapped" not in files[f"app/models/{table}.py"]
        assert "_sa.Uuid()" in files[f"app/models/{table}.py"]
    if not file_fields:
        assert "FILE_REFERENCES: tuple[tuple[str, str], ...] = (\n)" in refs


def test_the_scanner_failure_modes_have_no_fail_open_path(
    project: tuple[Spec, dict[str, str]],
) -> None:
    """Reads the generated service: every route from "scanner said something" to "stored" must go
    through a clean verdict."""
    _, files = project
    service = files["app/storage/service.py"]
    scan_at = service.index("clamav.scan(")
    store_at = service.index("get_backend().put(")
    assert scan_at < store_at
    block = service[scan_at:store_at]
    assert "ScannerUnavailable" in block and "not verdict.clean" in block
    assert "except Exception" not in block


def test_the_guide_states_the_numbers_and_the_limits(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    assert spec.storage is not None
    guide = files["deploy/storage/STORAGE.md"]
    assert f"**{spec.storage.max_file_mb} MB**" in guide
    assert "StreamMaxLength" in guide and "AlertExceedsMax" in guide
    assert "What this covers and what it does not" in guide
    assert "no compliance opinion" in guide.replace("not a compliance opinion", "no compliance opinion")
    if spec.storage.backend == "minio":
        assert "stopped publishing container images" in guide  # the MinIO situation is stated plainly


def test_policies_are_valid_json_scoped_to_the_bucket(project: tuple[Spec, dict[str, str]]) -> None:
    import json

    spec, files = project
    assert spec.storage is not None
    bucket, prefix = spec.storage.bucket, spec.storage.key_prefix
    policy = json.loads(files["deploy/storage/bucket-policy.json"])
    assert {s["Sid"] for s in policy["Statement"]} == {"DenyInsecureTransport", "DenyOldTlsVersions"}
    iam = json.loads(files["deploy/storage/iam-policy.json"])
    object_rule = next(s for s in iam["Statement"] if s["Sid"] == "ObjectsUnderThePrefixOnly")
    assert object_rule["Resource"] == f"arn:aws:s3:::{bucket}/{prefix}/*"
    assert "s3:*" not in str(iam)
    lifecycle = json.loads(files["deploy/storage/lifecycle.json"])
    assert {r["ID"] for r in lifecycle["Rules"]} >= {"abort-incomplete-uploads", "expire-old-versions"}
