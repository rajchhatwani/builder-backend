"""Validation for the `deployment` block (CI/CD workflows and Terraform).

Issues go through the `add(path, code, message)` callable that validation.validate passes in.
Besides the shape of the block, this refuses combinations the generated infrastructure does not yet
run correctly: a project that needs a payments worker, a malware scanner, Redis or its own Keycloak
cannot be deployed by these bundles, and saying so now is better than a half-working deployment.
"""

from collections.abc import Callable

from app.core import deploy_sizing as sizing
from app.core.spec_models import Spec, SpecDeployEnvironment, SpecDeployment
from app.core.validation_payments import payments_active
from app.core.validation_storage import storage_active

Add = Callable[[str, str, str], None]


def deployment_active(spec: Spec) -> SpecDeployment | None:
    block = spec.deployment
    return block if block is not None and block.enabled else None


def check_deployment(spec: Spec, add: Add) -> None:
    block = spec.deployment
    if block is None or not block.enabled:
        return
    if block.cloud not in sizing.CLOUDS:
        add("deployment.cloud", "invalid_value", f"must be one of {', '.join(sizing.CLOUDS)}")
        return
    if not sizing.REGION_RE[block.cloud].fullmatch(block.region):
        add(
            "deployment.region",
            "invalid_value",
            f"not a {block.cloud.upper()} region name (for example "
            f"{ {'aws': 'eu-west-1', 'azure': 'westeurope', 'gcp': 'europe-west1'}[block.cloud] })",
        )
    if not sizing.REPO_RE.fullmatch(block.github_repo):
        add(
            "deployment.github_repo",
            "invalid_value",
            "use the GitHub repository as owner/name; the cloud trusts only this repository",
        )
    _check_environments(block, add)
    _check_supported(spec, add)


def _check_environments(block: SpecDeployment, add: Add) -> None:
    envs = block.environments
    if not envs:
        add("deployment.environments", "required", "add at least one environment")
        return
    if len(envs) > sizing.MAX_ENVIRONMENTS:
        add("deployment.environments", "too_many", f"at most {sizing.MAX_ENVIRONMENTS}")
    seen: set[str] = set()
    for i, env in enumerate(envs):
        path = f"deployment.environments[{i}]"
        if not sizing.ENV_NAME_RE.fullmatch(env.name):
            add(
                f"{path}.name",
                "invalid_value",
                "2 to 12 lowercase letters or digits, starting with a letter (dev, staging, prod)",
            )
        elif env.name in seen:
            add(f"{path}.name", "duplicate", f"{env.name} is listed twice")
        seen.add(env.name)
        if env.profile not in sizing.PROFILES:
            add(f"{path}.profile", "invalid_value", f"must be one of {', '.join(sizing.PROFILES)}")
            continue
        _check_sizes(block.cloud, env, path, add)


def _check_sizes(cloud: str, env: SpecDeployEnvironment, path: str, add: Add) -> None:
    if (env.cpu is None) != (env.memory is None):
        add(
            path,
            "invalid_value",
            "set cpu and memory together (they must be a size the cloud offers)",
        )
    elif (
        env.cpu is not None
        and env.memory is not None
        and not sizing.valid_combo(cloud, env.cpu, env.memory)
    ):
        pairs = ", ".join(f"{c}m/{m}MB" for c, m in sizing.combos(cloud))
        add(f"{path}.cpu", "invalid_value", f"{cloud.upper()} offers only: {pairs}")
    if env.min_instances is not None and not 0 <= env.min_instances <= 100:
        add(f"{path}.min_instances", "invalid_value", "must be between 0 and 100")
    if env.max_instances is not None and not 1 <= env.max_instances <= 1000:
        add(f"{path}.max_instances", "invalid_value", "must be between 1 and 1000")
    if (
        env.min_instances is not None
        and env.max_instances is not None
        and env.min_instances > env.max_instances
    ):
        add(f"{path}.max_instances", "invalid_value", "must be at least the minimum")
    if env.db_storage_gb is not None and not 10 <= env.db_storage_gb <= 65536:
        add(f"{path}.db_storage_gb", "invalid_value", "must be between 10 and 65536")


def _check_supported(spec: Spec, add: Add) -> None:
    unsupported: list[tuple[str, str]] = []
    if payments_active(spec):
        unsupported.append(("payments", "the payments worker process"))
    if storage_active(spec):
        unsupported.append(("storage", "the malware scanner and the object store"))
    auth = spec.auth
    if auth is not None and auth.enabled:
        if (
            auth.provider == "keycloak"
            and auth.keycloak is not None
            and auth.keycloak.mode == "own"
        ):
            unsupported.append(("auth.keycloak", "a Keycloak server of its own"))
        if auth.provider == "builtin" and auth.token_store == "redis":
            unsupported.append(("auth.token_store", "a Redis service"))
    for path, what in unsupported:
        add(
            f"deployment.{path}",
            "deployment.unsupported",
            f"the cloud deployment bundles cannot run {what} yet: switch it off for this project, "
            "or turn deployment off and deploy it yourself",
        )
