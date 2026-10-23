"""What the generator emits for a project with payments: the files, their consistency with the
sizing, valid deployment YAML, and the guarantee that nothing secret is ever rendered."""

import re
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.generator.features.payments.module import PROVIDERS
from app.core.payments_sizing import size
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
NAMES = ["payments_stripe", "payments_tenant", "payments_razorpay"]

# Shapes of real secrets. The generated tests build their fake keys at run time ("sk_test_" + "a" * 24)
# precisely so that this scan can be strict about every file.
SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{8,}"),
    re.compile(r"\brzp_(?:live|test)_[A-Za-z0-9]{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    re.compile(r"(?i)\bpassword\s*[:=]\s*['\"][^'\"$\s{][^'\"]{3,}"),
]


def load(name: str) -> Spec:
    return Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=NAMES)
def project(request: pytest.FixtureRequest) -> tuple[Spec, dict[str, str]]:
    spec = load(request.param)
    return spec, generate(spec)


def test_no_secret_is_ever_rendered(project: tuple[Spec, dict[str, str]]) -> None:
    _, files = project
    # Test files may hold throw-away passwords and tokens of their own (the auth tests sign users
    # in); provider-key shapes and private keys are forbidden everywhere, including tests.
    strict = SECRET_PATTERNS[:4]
    leaks = [
        f"{path}: {pattern.pattern}"
        for path, content in files.items()
        for pattern in (strict if path.startswith("tests/") else SECRET_PATTERNS)
        if pattern.search(content)
    ]
    assert leaks == []


def test_the_payments_files_are_generated(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    assert spec.payments is not None
    expected = {
        "app/payments/config.py",
        "app/payments/service.py",
        "app/payments/worker.py",
        "app/payments/reconcile.py",
        f"app/payments/providers/{spec.payments.provider}.py",
        f"tests/fake_{spec.payments.provider}.py",
        "alembic/versions/0003_payments.py",
        "deploy/DEPLOYMENT.md",
        "deploy/compose.worker.yml",
        "deploy/sql/roles.sql",
        "tests/payments_support.py",
        "tests/test_payments_flow.py",
        "tests/test_payments_security.py",
    }
    assert expected <= set(files)
    other = "razorpay" if spec.payments.provider == "stripe" else "stripe"
    assert f"app/payments/providers/{other}.py" not in files, "only the chosen provider ships"
    has_k8s = any(path.startswith("deploy/k8s/") for path in files)
    assert has_k8s is spec.payments.scale.kubernetes


def test_without_payments_nothing_of_it_is_generated() -> None:
    spec = load("payments_stripe")
    assert spec.payments is not None
    spec.payments.enabled = False
    files = generate(spec)
    assert not [p for p in files if "payments" in p or p.startswith("deploy/")]
    assert "STRIPE" not in files[".env.example"] and "RAZORPAY" not in files[".env.example"]
    assert "payments-worker" not in files["docker-compose.yml"]


def test_compose_files_are_valid_and_wire_the_workers(project: tuple[Spec, dict[str, str]]) -> None:
    yaml = pytest.importorskip("yaml")
    spec, files = project
    assert spec.payments is not None
    sizing = size(spec.payments.scale)
    compose: dict[str, Any] = yaml.safe_load(files["docker-compose.yml"])
    services = compose["services"]
    assert {"db", "api", "payments-worker"} <= set(services)
    assert ("pgbouncer" in services) is spec.payments.scale.pgbouncer

    worker = services["payments-worker"]
    assert worker["command"] == ["python", "-m", "app.payments.worker"]
    assert worker["read_only"] is True and worker["cap_drop"] == ["ALL"]
    assert worker["deploy"]["replicas"].endswith(f"{sizing.worker_replicas}}}")
    prov = PROVIDERS[spec.payments.provider]
    for service in (services["api"], worker):
        env = service["environment"]
        # Provider secrets are required from the environment, never given a value here.
        for name in (*prov.key_envs, prov.webhook_secret_env):
            assert env[name].startswith("${" + name + ":?"), name
        if spec.payments.scale.pgbouncer:
            assert "pgbouncer:6432" in env["DATABASE_URL"] and env["DB_PGBOUNCER"] == "true"
    for service in services.values():
        image = service.get("image", "")
        assert not image.endswith(":latest") and (":" in image or not image)

    worker_file: dict[str, Any] = yaml.safe_load(files["deploy/compose.worker.yml"])
    only = worker_file["services"]["payments-worker"]
    assert only["image"].startswith("${APP_IMAGE:?")
    assert only["environment"]["DATABASE_URL"].startswith("${DATABASE_URL:?")


def test_kubernetes_manifests_match_the_sizing(project: tuple[Spec, dict[str, str]]) -> None:
    yaml = pytest.importorskip("yaml")
    spec, files = project
    assert spec.payments is not None
    if not spec.payments.scale.kubernetes:
        pytest.skip("kubernetes files are not requested for this project")
    sizing = size(spec.payments.scale)
    documents: list[dict[str, Any]] = []
    for path, content in files.items():
        if path.startswith("deploy/k8s/") and path.endswith(".yaml"):
            documents += [d for d in yaml.safe_load_all(content) if d]
    kinds = {d["kind"] for d in documents}
    assert {"Deployment", "HorizontalPodAutoscaler", "PodDisruptionBudget", "Job", "CronJob"} <= kinds
    assert {"NetworkPolicy", "Service", "Kustomization"} <= kinds

    deployments = {d["metadata"]["name"]: d for d in documents if d["kind"] == "Deployment"}
    slug = spec.project.slug
    assert deployments[f"{slug}-api"]["spec"]["replicas"] == sizing.api_replicas
    assert deployments[f"{slug}-payments-worker"]["spec"]["replicas"] == sizing.worker_replicas
    for deployment in deployments.values():
        pod = deployment["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["automountServiceAccountToken"] is False
        container = pod["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["capabilities"] == {"drop": ["ALL"]}
        assert container["securityContext"]["allowPrivilegeEscalation"] is False
    api_command = deployments[f"{slug}-api"]["spec"]["template"]["spec"]["containers"][0]["command"]
    assert "alembic" not in " ".join(api_command), "migrations must not run from every replica"
    policies = [d for d in documents if d["kind"] == "NetworkPolicy"]
    assert any(p["spec"]["policyTypes"] == ["Ingress", "Egress"] and "ingress" not in p["spec"] for p in policies)


def test_the_deployment_guide_states_the_numbers_and_the_limits(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    assert spec.payments is not None
    sizing = size(spec.payments.scale)
    guide = files["deploy/DEPLOYMENT.md"]
    assert f"**{sizing.total_db_connections}**" in guide
    assert f"{sizing.worker_replicas} replica(s)" in guide
    assert "estimate, not a measurement" in guide
    prov = PROVIDERS[spec.payments.provider]
    assert f"not** been run against {prov.title} itself" in guide
    assert f"/payments/webhooks/{prov.name}" in guide
    assert all(f"`{event}`" in guide for event in prov.events)
    assert prov.webhook_secret_env in guide
    # The guide never invents a number: every figure in the table is the sizing's own.
    assert str(sizing.payments_per_minute) in guide


def test_the_image_runs_as_an_unprivileged_user_with_configurable_workers(
    project: tuple[Spec, dict[str, str]],
) -> None:
    _, files = project
    dockerfile = files["Dockerfile"]
    assert "USER 10001" in dockerfile
    assert "${UVICORN_WORKERS:-1}" in dockerfile


def test_database_roles_cannot_alter_the_audit_log(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    sql = files["deploy/sql/roles.sql"]
    slug = spec.project.slug.replace("-", "_")
    assert f"REVOKE UPDATE, DELETE, TRUNCATE ON pay_audit_log FROM {slug}_app" in sql
    assert ":'migrator_password'" in sql and ":'app_password'" in sql  # passed in, never written


def test_the_migration_protects_the_audit_table(project: tuple[Spec, dict[str, str]]) -> None:
    spec, files = project
    assert spec.payments is not None
    migration = files["alembic/versions/0003_payments.py"]
    assert "pay_audit_append_only" in migration and "BEFORE TRUNCATE" in migration
    assert f"days => {spec.payments.security.audit_retention_days}" in migration
    assert "uq_pay_payments_active_payable" in migration  # one live payment per item
    assert "ck_pay_refunds_two_people" in migration
