"""FX-4 / B-002: what an APPROVED apply_migration, create_pr or request_secret does.

Each effect goes through a small adapter, so a real integration (a git host, a dev database, a secret
vault) can replace the default later without touching the approval flow. The defaults are LOCAL: they do
no outbound call and hold no credential, and they say so in their answer (`adapter`, `outbound: false`).

  apply_migration  DevEnvironmentPlan: plans the schema change from the spec the run started on to the
                   draft with the platform migration planner and refuses a destructive plan. It does not
                   touch a database: `applied_to_database` is false (the generated Alembic revision runs
                   when the draft's preview starts or the project is deployed).
  create_pr        LocalPullRequests: records a pull request for the draft's branch (name + head commit);
                   nothing is pushed.
  request_secret   VaultSecretRequests: records that a human must set the named secret in the vault; the
                   value never passes through the agent.
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.spec_models import Spec
from app.exceptions import AppError
from app.models.agent import AiRun
from app.models.workspace import Workspace
from app.services.agent.draft import run_spec
from app.services.migration_planner.model import MigrationPlanError
from app.services.migration_planner.planner import plan_migration

SECRET_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")


class DevEnvironment(Protocol):
    async def apply_migration(self, session: AsyncSession, run: AiRun) -> dict[str, Any]: ...


class PullRequests(Protocol):
    async def create(self, session: AsyncSession, run: AiRun, title: str) -> dict[str, Any]: ...


class SecretRequests(Protocol):
    async def request(self, session: AsyncSession, run: AiRun, name: str) -> dict[str, Any]: ...


class DevEnvironmentPlan:
    async def apply_migration(self, session: AsyncSession, run: AiRun) -> dict[str, Any]:
        raw = (run.plan or {}).get("base_spec") if isinstance(run.plan, dict) else None
        if not isinstance(raw, dict):
            raise AppError("approval_not_applicable", "the run has no recorded base spec", 422)
        draft: Spec = await run_spec(session, run.id, run.project_id)
        try:
            plan = plan_migration(Spec.model_validate(raw), draft)
        except MigrationPlanError as exc:
            raise AppError("migration_plan_failed", f"the schema change cannot be planned: {str(exc)[:200]}", 422) from exc
        if not plan.apply_allowed():
            blocked = [f"{s.entity}.{s.field or ''}" for s in plan.blocked_steps()][:10]
            raise AppError("migration_destructive", f"the plan has destructive steps ({blocked}); remove them or ask "
                           "for a destructive-change approval first", 422)  # fmt: skip
        return {"adapter": "plan_only", "env": "dev", "applied_to_database": False, "outbound": False,
                "steps": len(plan.steps), "highest_safety": plan.to_dict()["highest_safety"],
                "requires_backfill": plan.requires_backfill,
                "note": "no dev database is connected; the generated Alembic revision runs when the preview "
                        "of the draft starts or the project is deployed"}  # fmt: skip


class LocalPullRequests:
    async def create(self, session: AsyncSession, run: AiRun, title: str) -> dict[str, Any]:
        ws = await session.get(Workspace, run.workspace_id) if run.workspace_id else None
        if ws is None or not ws.worktree_path or not Path(ws.worktree_path).is_dir():
            raise AppError("approval_not_applicable", "the run has no draft branch to open a pull request for", 422)
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", ws.worktree_path, "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        out, _ = await proc.communicate()
        head = out.decode().strip() if proc.returncode == 0 else None
        return {"adapter": "local", "outbound": False, "pushed": False,
                "pull_request": {"id": f"local-{run.id.hex[:8]}", "title": title[:200], "branch": ws.branch,
                                 "base": "main", "head": head, "url": None}}  # fmt: skip


class VaultSecretRequests:
    async def request(self, session: AsyncSession, run: AiRun, name: str) -> dict[str, Any]:
        if not SECRET_NAME_RE.fullmatch(name):
            raise AppError("secret_name_invalid", "a secret name is UPPER_SNAKE_CASE (2-64 characters)", 422)
        return {"adapter": "vault_request", "outbound": False, "secret": name, "status": "awaiting_value",
                "note": "a person with access sets the value in the project's secrets; the agent never sees it"}  # fmt: skip


@dataclass
class Adapters:
    dev: DevEnvironment
    pull_requests: PullRequests
    secrets: SecretRequests


_ADAPTERS = Adapters(DevEnvironmentPlan(), LocalPullRequests(), VaultSecretRequests())


def get_adapters() -> Adapters:
    return _ADAPTERS


def set_adapters(adapters: Adapters | None) -> None:
    """Tests and a deployment with a real integration replace the defaults here."""
    global _ADAPTERS
    _ADAPTERS = adapters or Adapters(DevEnvironmentPlan(), LocalPullRequests(), VaultSecretRequests())
