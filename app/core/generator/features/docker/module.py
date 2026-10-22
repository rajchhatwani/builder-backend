"""The `docker` feature: packaging and the run experience (Dockerfile, compose, env,
Makefile, dependency lists, tool config, README)."""

from pathlib import Path

from app.core.generator.base import FileTree
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    ".dockerignore.tpl",
    ".env.example.tpl",
    ".gitignore.tpl",
    "Dockerfile.tpl",
    "Makefile.tpl",
    "docker-compose.yml.tpl",
    "pyproject.toml.tpl",
    "requirements-dev.txt.tpl",
    "requirements.txt.tpl",
)


class DockerModule:
    name = "docker"

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        files["README.md"] = render_template(
            self._env,
            "README.md.j2",
            name=project.name,
            description=project.description,
            entities=project.entities,
        )
        return files
