"""The `jobs` feature: a Postgres-backed job queue, cron schedules and worker groups (C11).

Emitted only when the spec has `jobs.enabled`:

  app/jobs/definitions.py   jobs, schedules, worker groups (plain data)
  app/jobs/models.py        `jb_jobs`, `jb_schedules`, `jb_schedule_fires`
  app/jobs/queue.py         enqueue (joins the caller's transaction), claim with a lease, retry, dead-letter
  app/jobs/registry.py      @handler registry and the handler context
  app/jobs/scheduler.py     cron ticks, each fired once however many processes run
  app/jobs/worker.py        `python -m app.jobs.worker --group NAME`
  app/jobs/admin.py         `python -m app.jobs.admin list-dead | requeue`
  app/jobs/cron.py          the strict 5-field cron the builder validated with (copied from the builder)
  app/hooks/jobs.py         YOUR handlers (custom zone, written once)
  alembic/versions/0013_jobs.py, tests/test_jobs.py
  docker-compose.yml        a `worker-<group>` service per same_server group (see the docker feature)
  deploy/workers/<group>/   compose.yml + .env.example per separate_server group
"""

import pprint
from pathlib import Path
from typing import Any

from app.core import jobs_cron
from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.events.module import migration_parent as _events_parent
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_events import events_active
from app.core.validation_jobs import jobs_active
from app.core.validation_webhooks import WEBHOOK_JOB, webhooks_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/jobs/__init__.py.tpl",
    "app/jobs/admin.py.tpl",
    "app/jobs/config.py.tpl",
    "app/jobs/models.py.tpl",
    "app/jobs/queue.py.tpl",
    "app/jobs/registry.py.tpl",
    "app/jobs/scheduler.py.tpl",
    "app/jobs/worker.py.tpl",
)


def migration_parent(project: ProjectCtx) -> str:
    """The revision this block's migration follows: the events' (0009) when the project has it, else
    whatever the events block would have followed."""
    if events_active(project.spec):
        return "0009"
    return _events_parent(project)


def _service_name(group: str) -> str:
    return group.replace("_", "-")


def definitions(project: ProjectCtx) -> dict[str, dict[str, Any]]:
    cfg = project.spec.jobs
    assert cfg is not None
    return {
        "JOBS": {
            j.name: {
                "queue": j.queue,
                "handler": j.handler,
                "timeout_seconds": j.timeout_seconds,
                "retry": {
                    "max_attempts": j.retry.max_attempts,
                    "backoff_seconds": j.retry.backoff_seconds,
                    "backoff": j.retry.backoff,
                },
            }
            for j in sorted(cfg.jobs, key=lambda x: x.name)
        },
        "SCHEDULES": {
            s.name: {
                "job": s.job,
                "cron": s.cron,
                "timezone": s.timezone,
                "enabled": s.enabled,
                "missed": s.missed,
            }
            for s in sorted(cfg.schedules, key=lambda x: x.name)
        },
        "GROUPS": {
            g.name: {
                "queues": sorted(g.queues),
                "concurrency": g.concurrency,
                "placement": g.placement,
            }
            for g in sorted(cfg.worker_groups, key=lambda x: x.name)
        },
    }


def _groups(project: ProjectCtx, placement: str) -> list[dict[str, Any]]:
    if not jobs_active(project.spec):
        return []
    cfg = project.spec.jobs
    assert cfg is not None
    return [
        {
            "name": g.name,
            "service": _service_name(g.name),
            "concurrency": g.concurrency,
            "queues": sorted(g.queues),
        }
        for g in sorted(cfg.worker_groups, key=lambda x: x.name)
        if g.placement == placement
    ]


def same_server_groups(project: ProjectCtx) -> list[dict[str, Any]]:
    """Worker groups that become services of the project's own docker-compose.yml."""
    return _groups(project, "same_server")


def _test_target(data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The job the generated tests drive: the first by name."""
    name = next(iter(data["JOBS"]))
    job = data["JOBS"][name]
    return {"name": name, "queue": job["queue"], "max_attempts": job["retry"]["max_attempts"]}


def _test_schedule(data: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for name, sched in data["SCHEDULES"].items():
        if sched["enabled"]:
            return {"name": name, "job": sched["job"]}
    return None


class JobsModule:
    name = "jobs"
    manifest = ModuleManifest(id="jobs", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not jobs_active(project.spec):
            return {}
        data = definitions(project)
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        files["app/jobs/definitions.py"] = (
            '"""Jobs, schedules and worker groups (generated from the spec: change it in the builder).\n\n'
            'Plain data."""\n\n'
            "from typing import Any\n\n"
            + "".join(
                f"{name}: dict[str, dict[str, Any]] = {pprint.pformat(value, width=96, sort_dicts=True)}\n\n"
                for name, value in data.items()
            ).rstrip("\n")
            + "\n"
        )
        files["app/jobs/cron.py"] = Path(jobs_cron.__file__).read_text(encoding="utf-8")
        platform_webhooks = webhooks_active(project.spec) and project.auth is not None
        files["app/hooks/jobs.py"] = render_template(
            self._env,
            "app/hooks/jobs.py.j2",
            jobs=[
                {
                    "name": name,
                    "handler": cfg["handler"],
                    "queue": cfg["queue"],
                    "max_attempts": cfg["retry"]["max_attempts"],
                    "timeout_seconds": cfg["timeout_seconds"],
                }
                for name, cfg in data["JOBS"].items()
                if not (platform_webhooks and name == WEBHOOK_JOB)
            ],
            platform_webhooks=platform_webhooks,
        )
        files["alembic/versions/0013_jobs.py"] = render_template(
            self._env,
            "alembic/versions/0013_jobs.py.j2",
            down_revision=migration_parent(project),
        )
        for group in _groups(project, "separate_server"):
            folder = f"deploy/workers/{group['name']}"
            files[f"{folder}/compose.yml"] = render_template(
                self._env, "deploy/workers.compose.yml.j2", g=group, slug=project.spec.project.slug
            )
            files[f"{folder}/.env.example"] = render_template(
                self._env, "deploy/workers.env.example.j2", g=group, slug=project.spec.project.slug
            )
        files["tests/test_jobs.py"] = render_template(
            self._env,
            "tests/test_jobs.py.j2",
            target=_test_target(data),
            sched=_test_schedule(data),
        )
        return files
