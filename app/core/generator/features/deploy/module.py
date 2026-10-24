"""The `deploy` feature: CI workflows and Terraform for one cloud (AWS, Azure or GCP).

Emitted only when the spec has an enabled `deployment` block:

  .github/workflows/ci.yml        lint, tests, image build, scan, SBOM, terraform checks
  .github/workflows/deploy.yml    OIDC sign-in, build once, push, sign, migrate, deploy, smoke test
  .github/dependabot.yml          weekly update proposals for actions, providers, packages
  deploy/<cloud>/                 the stack: network, database, secrets, service, load balancing
  deploy/<cloud>/environments/    one .tfvars per environment (capacity is numbers in this file)
  deploy/<cloud>/bootstrap/       run once by an administrator: state storage, registry, OIDC trust
  docs/DEPLOYMENT.md              the one-time setup, every pipeline step, rollback, costs

No credential is written anywhere: pipelines use short-lived OIDC tokens and secrets live in the
cloud's secret manager, filled in by a person.
"""

import json
import re
from pathlib import Path

from app.core import deploy_pins as pins
from app.core import deploy_sizing as sizing
from app.core.generator.base import FileTree
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.spec_models import SpecDeployment
from app.core.validation import uses_keycloak
from app.core.validation_deploy import deployment_active
from app.core.validation_observability import observability_active

_TEMPLATES = Path(__file__).parent / "templates"

# Template folder -> files it contributes (names without the .j2 suffix).
_STACK_FILES = {
    "aws": (
        "versions.tf",
        "variables.tf",
        "network.tf",
        "database.tf",
        "secrets.tf",
        "iam.tf",
        "ecs.tf",
        "alb.tf",
        "waf.tf",
        "outputs.tf",
    ),
    "azure": (
        "versions.tf",
        "variables.tf",
        "network.tf",
        "database.tf",
        "secrets.tf",
        "app.tf",
        "outputs.tf",
    ),
    "gcp": (
        "versions.tf",
        "variables.tf",
        "network.tf",
        "database.tf",
        "secrets.tf",
        "app.tf",
        "outputs.tf",
    ),
}
_BOOTSTRAP_FILES = ("versions.tf", "main.tf", "variables.tf", "outputs.tf")


def secret_env_names(project: ProjectCtx) -> list[str]:
    """Environment variables the service needs that are secret. Their values are set by a person in
    the cloud's secret manager; DATABASE_URL is created by Terraform and is not in this list."""
    auth = project.auth
    if auth is None or not auth.enabled or uses_keycloak(auth):
        return []
    names = ["AUTH_JWT_PRIVATE_KEY" if auth.jwt_algorithm == "RS256" else "AUTH_JWT_SECRET"]
    if auth.smtp:
        names += ["SMTP_USERNAME", "SMTP_PASSWORD"]
    if auth.sms and auth.sms_provider == "twilio":
        names += ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]
    elif auth.sms and auth.sms_provider == "vonage":
        names += ["VONAGE_API_KEY", "VONAGE_API_SECRET"]
    return sorted(names)


def _env_rows(block: SpecDeployment) -> list[sizing.Resolved]:
    return [
        sizing.resolve(
            block.cloud,
            env.name,
            env.profile,
            **env.model_dump(exclude={"name", "profile"}),
        )
        for env in block.environments
    ]


def tfvars_for(block: SpecDeployment, env: sizing.Resolved, keycloak: bool = False) -> str:
    """One environment's tfvars: sizing numbers plus the few cloud-specific switches."""
    dev_like = env.name == block.environments[0].name and not env.deletion_protection
    text = sizing.tfvars_text(block.region, env, "development" if dev_like else "production")
    if block.cloud == "aws":
        text += "\n# HTTPS needs a certificate from AWS Certificate Manager in this region:\n"
        text += '# acm_certificate_arn = "arn:aws:acm:<region>:<account>:certificate/<id>"\n'
        text += sizing.assignments(
            [
                ("allow_http", "true" if dev_like else "false"),
                ("enable_waf", "false" if dev_like else "true"),
                ("single_nat_gateway", "true" if not env.db_high_availability else "false"),
            ]
        )
    if keycloak:
        text += "\n# Where this service finds your Keycloak (https in production):\n"
        text += (
            "app_env_vars = {\n"
            '  # KEYCLOAK_PUBLIC_URL = "https://sso.example.com"\n'
            '  # KEYCLOAK_INTERNAL_URL = ""\n'
            "}\n"
        )
    return text


_TOKEN_RE = re.compile(r"@@(pin:[A-Za-z0-9_./-]+|[A-Z_]+)@@")


def fill_tokens(text: str, values: dict[str, str]) -> str:
    """Workflows are YAML full of GitHub's own `${{ }}` expressions, so they are not Jinja: plain
    `@@TOKEN@@` placeholders are replaced here and `@@pin:owner/action@@` becomes a pinned
    reference.
    An unknown token raises, so a typo can never reach a generated file."""

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.startswith("pin:"):
            return pins.pin(token[4:])
        return values[token]

    return _TOKEN_RE.sub(replace, text)


class DeployModule:
    name = "deploy"

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def _render(self, template: str, context: dict[str, object]) -> str:
        return render_template(self._env, template, **context)

    def render(self, project: ProjectCtx) -> FileTree:
        block = deployment_active(project.spec)
        if block is None:
            return {}
        cloud = block.cloud
        secrets = secret_env_names(project)
        otel = observability_active(project.spec)
        rows = _env_rows(block)
        context: dict[str, object] = {
            "project_name": project.name,
            "slug": project.slug,
            "cloud": cloud,
            "region": block.region,
            "repo": block.github_repo,
            "environments": [e.name for e in block.environments],
            "env_rows": rows,
            "secret_names": secrets,
            "secret_names_hcl": json.dumps(secrets),
            "keycloak": uses_keycloak(project.auth),
            "has_auth": project.auth is not None and project.auth.enabled,
            "otel": otel is not None,
            "pins": pins.ACTION_PINS,
            "pin": pins.pin,
            "images": pins.IMAGES,
            "terraform_version": pins.TERRAFORM_VERSION,
        }
        files: FileTree = {}
        for name in _STACK_FILES[cloud]:
            files[f"deploy/{cloud}/{name}"] = self._render(f"{cloud}/{name}.j2", context)
        for name in _BOOTSTRAP_FILES:
            files[f"deploy/{cloud}/bootstrap/{name}"] = self._render(
                f"{cloud}_bootstrap/{name}.j2", context
            )
        for env, resolved in zip(block.environments, rows, strict=True):
            files[f"deploy/{cloud}/environments/{env.name}.tfvars"] = tfvars_for(
                block, resolved, uses_keycloak(project.auth)
            )
        tokens = {
            "PROJECT": project.name,
            "SLUG": project.slug,
            "CLOUD": cloud,
            "REGION": block.region,
            "TERRAFORM_VERSION": pins.TERRAFORM_VERSION,
            "POSTGRES_IMAGE": pins.IMAGES["postgres"],
            "FIRST_ENV": block.environments[0].name,
            "ENV_OPTIONS": ", ".join(e.name for e in block.environments),
            "ENV_LIST": ", ".join(e.name for e in block.environments),
        }
        for target, template in (
            (".github/workflows/ci.yml", "workflows/ci.yml.tpl"),
            (".github/workflows/deploy.yml", f"workflows/deploy_{cloud}.yml.tpl"),
        ):
            files[target] = fill_tokens(read_verbatim(_TEMPLATES, template), tokens)
        files[".github/dependabot.yml"] = self._render("workflows/dependabot.yml.j2", context)
        files["docs/DEPLOYMENT.md"] = self._render("docs/DEPLOYMENT.md.j2", context)
        return files
