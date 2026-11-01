"""The `workflows` feature: durable sagas on Postgres, a worker, and a start / inspect / cancel API (C12).

Emitted only when the spec has `workflows.enabled` (and the project has auth):

  app/workflows/definitions.py  workflows, steps, roles, failure policy (plain data)
  app/workflows/models.py       `wf_runs`, `wf_steps`
  app/workflows/engine.py       start, claim under a lease, step-by-step execution, compensation, cancel
  app/workflows/registry.py     @step / @compensation registry and the step context
  app/workflows/worker.py       `python -m app.workflows.worker`
  app/workflows/router.py       POST /workflows/{name}/runs, GET /workflows/runs[/{id}], POST /workflows/runs/{id}/cancel
  app/hooks/workflows.py        YOUR step and undo functions (custom zone, written once)
  alembic/versions/0020_workflows.py, tests/test_workflows.py
  docker-compose.yml            a `workflow-worker` service (see the docker feature)

Runtime: `postgres`, the built-in durable runner (the adapter seam is `engine.py`: start / claim / drive / cancel).
`dbos` and `temporal` are accepted by the schema and refused by validation (not_yet_implemented).
"""

import pprint
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_workflows import workflows_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/workflows/__init__.py.tpl",
    "app/workflows/config.py.tpl",
    "app/workflows/engine.py.tpl",
    "app/workflows/models.py.tpl",
    "app/workflows/registry.py.tpl",
    "app/workflows/router.py.tpl",
    "app/workflows/worker.py.tpl",
)


def workflows_enabled(project: ProjectCtx) -> bool:
    """The block is emitted only for a project with auth (the API is role-checked and tenant-scoped)."""
    return workflows_active(project.spec) and project.auth is not None


def multi_tenant(project: ProjectCtx) -> bool:
    return project.auth is not None and project.auth.multi_tenant


def definitions(project: ProjectCtx) -> dict[str, Any]:
    cfg = project.spec.workflows
    assert cfg is not None
    return {
        "RUNTIME": cfg.runtime,
        "MULTI_TENANT": multi_tenant(project),
        "CONCURRENCY": cfg.worker.concurrency,
        "WORKFLOWS": {
            wf.name: {
                "roles": sorted(wf.roles),
                "on_failure": wf.on_failure,
                "timeout_seconds": wf.timeout_seconds,
                "steps": [
                    {
                        "name": s.name,
                        "kind": s.kind,
                        "job": s.job,
                        "compensate": s.compensate,
                        "timeout_seconds": s.timeout_seconds,
                        "retry": {
                            "max_attempts": s.retry.max_attempts,
                            "backoff_seconds": s.retry.backoff_seconds,
                            "backoff": s.retry.backoff,
                        },
                    }
                    for s in wf.steps
                ],
            }
            for wf in sorted(cfg.workflows, key=lambda x: x.name)
        },
    }


def _test_target(data: dict[str, Any]) -> dict[str, Any] | None:
    """The workflow the generated tests drive: the first (by name) whose steps are all hook steps."""
    for name, wf in data["WORKFLOWS"].items():
        if all(s["kind"] == "hook" for s in wf["steps"]):
            return {"name": name, "role": wf["roles"][0], "steps": [s["name"] for s in wf["steps"]]}
    return None


def _job_target(data: dict[str, Any]) -> dict[str, Any] | None:
    for name, wf in data["WORKFLOWS"].items():
        for s in wf["steps"]:
            if s["kind"] == "job":
                return {"name": name, "step": s["name"], "job": s["job"], "role": wf["roles"][0]}
    return None


class WorkflowsModule:
    name = "workflows"
    manifest = ModuleManifest(id="workflows", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not workflows_enabled(project):
            return {}
        data = definitions(project)
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM
        }
        files["app/workflows/definitions.py"] = (
            '"""Workflows (generated from the spec: change it in the builder).\n\nPlain data."""\n\n'
            + "".join(f"{key} = {pprint.pformat(value, width=96, sort_dicts=True)}\n\n" for key, value in data.items()).rstrip("\n")
            + "\n"
        )
        files["app/hooks/workflows.py"] = render_template(
            self._env,
            "app/hooks/workflows.py.j2",
            workflows=[
                {
                    "name": name,
                    "steps": [
                        {
                            "name": s["name"],
                            "kind": s["kind"],
                            "compensate": s["compensate"],
                            "max_attempts": s["retry"]["max_attempts"],
                            "timeout_seconds": s["timeout_seconds"],
                        }
                        for s in wf["steps"]
                    ],
                }
                for name, wf in data["WORKFLOWS"].items()
            ],
        )
        files["alembic/versions/0020_workflows.py"] = render_template(
            self._env, "alembic/versions/0020_workflows.py.j2"
        )
        files["tests/test_workflows.py"] = render_template(
            self._env,
            "tests/test_workflows.py.j2",
            target=_test_target(data),
            job_target=_job_target(data),
            tenant=multi_tenant(project),
        )
        return files
