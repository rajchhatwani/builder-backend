"""The `docker` feature: packaging and the run experience (Dockerfile, compose, env,
Makefile, dependency lists, tool config, README)."""

from pathlib import Path

from app.core.generator.base import FileTree
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation import invitations_enabled

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    ".dockerignore.tpl",
    ".gitignore.tpl",
    "Dockerfile.tpl",
    "Makefile.tpl",
    "pyproject.toml.tpl",
    "requirements-dev.txt.tpl",
)
# Rendered because they change when the auth feature is on.
_RENDERED = (".env.example.j2", "docker-compose.yml.j2", "requirements.txt.j2")


class DockerModule:
    name = "docker"

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        auth = project.auth
        sms_provider = auth.sms_provider if auth is not None and auth.sms else None
        context = {
            "auth": auth,
            "sms_provider": sms_provider,
            "sns": sms_provider == "aws_sns",
            "invitations": auth is not None and invitations_enabled(auth),
            "rs256": auth is not None and auth.jwt_algorithm == "RS256",
            "redis_store": auth is not None and auth.token_store == "redis",
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
