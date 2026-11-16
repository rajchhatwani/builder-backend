"""Shared builders: two customers in two separate orgs, and a victim world seeded straight into the
database (the nested objects that need a sandbox, Stripe or an upload to create over HTTP)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.agent import AiApproval, AiRun
from app.models.data_import import ImportBatch, ImportRow
from app.models.dependency_policy import DependencyRequest
from app.models.generation import Generation
from app.models.metrics import Metric, Report, ReportRun
from app.models.platform import ApiToken
from app.models.preview import Preview
from app.models.registry import RegistryHookEntry
from app.models.requirements import RequirementItem, RequirementQuestion, RequirementsMap
from app.models.workspace import Workspace
from tests.api._auth_helpers import make_entity, make_project, make_role
from tests.api.conftest import ClientFor


async def two_orgs(client_for: ClientFor) -> tuple[AsyncClient, AsyncClient]:
    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    return a, b


def uid(x: Any) -> uuid.UUID:
    return uuid.UUID(str(x))


async def seed_nested(
    sf: async_sessionmaker[AsyncSession], project_id: str, user_id: uuid.UUID
) -> dict[str, str]:
    """One row of every nested kind, belonging to `project_id`. Returns their ids as strings."""
    pid = uid(project_id)
    now = datetime.now(UTC)
    out: dict[str, str] = {}
    async with sf() as s:
        ws = Workspace(
            project_id=pid, name="draft", state="active", base_spec_seq=0, spec_seq=0,
            branch="ws/x", created_by=user_id,
        )
        s.add(ws)
        pv = Preview(
            project_id=pid, created_by=user_id, state="running", token_hash="0" * 64,
            spec_hash="0" * 64, db_sandbox="a" * 32, app_sandbox="b" * 32, limits={},
            expires_at=now + timedelta(hours=1),
        )
        s.add(pv)
        batch = ImportBatch(
            project_id=pid, entity_name="Item", filename="x.csv", content_sha256="0" * 64,
            status="previewed", headers=["a"], mapping={}, counts={}, created_by=user_id,
        )
        s.add(batch)
        await s.flush()
        row = ImportRow(
            project_id=pid, batch_id=batch.id, row_no=1, raw={"a": "SECRET-ROW"}, record=None,
            status="ok", errors=[],
        )
        s.add(row)
        metric = Metric(project_id=pid, key="m1", definition={"agg": "count"}, version=1)
        s.add(metric)
        report = Report(
            project_id=pid, name="rep", metric_keys=["m1"], schedule="daily", timezone="UTC",
            enabled=True,
        )
        s.add(report)
        await s.flush()
        s.add(ReportRun(report_id=report.id, project_id=pid, scheduled_for=now, status="ok", values={}))
        rmap = RequirementsMap(project_id=pid, status="draft", sources=[], created_by=user_id)
        s.add(rmap)
        await s.flush()
        item = RequirementItem(
            project_id=pid, map_id=rmap.id, kind="must", text="SECRET-REQ", status="open"
        )
        question = RequirementQuestion(
            project_id=pid, map_id=rmap.id, text="q?", assumption="a", answer=None
        )
        s.add_all([item, question])
        dep = DependencyRequest(
            project_id=pid, package="leftpad", version="1.0.0", reason="r", hashes=[],
            status="pending", requested_by=user_id,
        )
        s.add(dep)
        hook = RegistryHookEntry(
            project_id=pid, hook_name="h", content_hash="0" * 64, author="victim"
        )
        s.add(hook)
        run = AiRun(project_id=pid, created_by=user_id, goal="SECRET-GOAL", state="running")
        s.add(run)
        await s.flush()
        appr = AiApproval(
            run_id=run.id, project_id=pid, kind="A", subject="s", payload={}, risk_flags=[],
            state="pending", bound_spec_hash="0" * 64, expires_at=now + timedelta(hours=1),
        )
        s.add(appr)
        gen = Generation(
            project_id=pid, spec_snapshot={}, spec_hash="0" * 64, file_manifest=[], created_by=user_id
        ) if "created_by" in Generation.__table__.c else Generation(
            project_id=pid, spec_snapshot={}, spec_hash="0" * 64, file_manifest=[]
        )
        s.add(gen)
        tok = ApiToken(
            user_id=user_id, name="t", public_id=uuid.uuid4().hex[:10], token_hash="0" * 64,
            scopes=["read"], project_id=pid, expires_at=now + timedelta(days=1),
        )
        s.add(tok)
        await s.flush()
        out.update(
            ws_id=str(ws.id), preview_id=str(pv.id), batch_id=str(batch.id), row_id=str(row.id),
            metric_key="m1", report_id=str(report.id), item_id=str(item.id),
            question_id=str(question.id), request_id=str(dep.id), entry_id=str(hook.id),
            run_id=str(run.id), approval_id=str(appr.id), generation_id=str(gen.id),
            token_id=str(tok.id),
        )
        await s.commit()
    return out


async def victim_world(a: AsyncClient, sf: async_sessionmaker[AsyncSession]) -> dict[str, str]:
    project = await make_project(a, "Victim")
    entity = await make_entity(a, project, "Secret")
    field = (
        await a.post(f"/entities/{entity}/fields", json={"name": "title", "type": "string"})
    ).json()["id"]
    role = (await make_role(a, project, name="staff"))["id"]
    w = {
        "project_id": project, "entity_id": entity, "field_id": field, "role_id": role,
        "user_id": str(a.user.id),  # type: ignore[attr-defined]
    }
    w.update(await seed_nested(sf, project, a.user.id))  # type: ignore[attr-defined]
    return w
