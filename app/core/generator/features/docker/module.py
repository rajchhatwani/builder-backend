"""The `docker` feature: packaging and the run experience (Dockerfile, compose, env,
Makefile, dependency lists, tool config, README)."""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.keycloak.module import (
    KEYCLOAK_IMAGE,
    KEYCLOAK_IMAGE_TAG,
    idp_secret_env,
)
from app.core.generator.features.payments.module import (
    MAX_UVICORN_WORKERS_ONE_HOST,
    PGBOUNCER_IMAGE,
    PROVIDERS,
    active,
    sizing_for,
)
from app.core.generator.features.storage.module import (
    CLAMAV_IMAGE,
    DEV_S3_IMAGE,
    clamd_limit_mb,
)
from app.core.generator.features.storage.module import active as storage_block
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation import invitations_enabled, uses_keycloak
from app.core.validation_documents import documents_active
from app.core.validation_observability import observability_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    ".dockerignore.tpl",
    ".gitignore.tpl",
    "Dockerfile.tpl",
    "pyproject.toml.tpl",
)
# Rendered because they change when the auth feature is on.
_RENDERED = (
    ".env.example.j2",
    "Makefile.j2",
    "docker-compose.yml.j2",
    "requirements.txt.j2",
    "requirements-dev.txt.j2",
)


class DockerModule:
    name = "docker"
    manifest = ModuleManifest(id="docker", version="1", depends_on=())

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        auth = project.auth
        keycloak = uses_keycloak(auth)
        kc = auth.keycloak if auth is not None and keycloak else None
        kc_own = kc is not None and kc.mode == "own"
        builtin = auth if auth is not None and not keycloak else None
        sms_provider = builtin.sms_provider if builtin is not None and builtin.sms else None
        pay = active(project)
        sizing = sizing_for(pay) if pay is not None else None
        stor = storage_block(project)
        otel = observability_active(project.spec)
        context = {
            "storage": stor is not None,
            "otel": otel is not None,
            "documents": documents_active(project.spec) is not None and project.auth is not None,
            "otel_db": otel is not None and otel.db_spans,
            "otel_ratio": otel.sample_ratio if otel is not None else 0.1,
            "otel_stack": otel is not None and otel.local_stack,
            "file_entities": any(e.file_fields for e in project.entities),
            "s": stor,
            "minio": stor is not None and stor.backend == "minio",
            "clamav_image": CLAMAV_IMAGE,
            "dev_s3_image": DEV_S3_IMAGE,
            "clamd_limit_mb": clamd_limit_mb(stor) if stor is not None else 0,
            "pay": pay,
            "prov": PROVIDERS[pay.provider] if pay is not None else None,
            "sizing": sizing,
            "pgbouncer_image": PGBOUNCER_IMAGE,
            "single_host_workers": (
                min(sizing.api_replicas * sizing.server_workers, MAX_UVICORN_WORKERS_ONE_HOST)
                if sizing is not None
                else 1
            ),
            "auth": auth,
            "sms_provider": sms_provider,
            "sns": sms_provider == "aws_sns",
            "invitations": builtin is not None and invitations_enabled(builtin),
            "rs256": builtin is not None and builtin.jwt_algorithm == "RS256",
            "redis_store": builtin is not None and builtin.token_store == "redis",
            "keycloak": keycloak,
            "kc": kc,
            "kc_own": kc_own,
            "keycloak_image": KEYCLOAK_IMAGE,
            "keycloak_tag": KEYCLOAK_IMAGE_TAG,
            "idp_secret_names": (
                [idp_secret_env(a) for a in sorted(i.alias for i in kc.identity_providers)]
                if kc_own and kc is not None
                else []
            ),
            "idp_secrets": (
                [(a, idp_secret_env(a)) for a in sorted(i.alias for i in kc.identity_providers)]
                if kc_own and kc is not None
                else []
            ),
        }
        for template in _RENDERED:
            files[template.rsplit(".", 1)[0]] = render_template(self._env, template, **context)
        files["README.md"] = render_template(
            self._env,
            "README.md.j2",
            name=project.name,
            description=project.description,
            entities=project.entities,
            **context,
        )
        return files
