"""Requirements map persistence and the intake / answer / start-run flows (B3-6)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.core.shared_limiter import SharedLimiter
from app.db import get_session_factory
from app.exceptions import AppError
from app.models.agent import AiRun
from app.models.project import Project
from app.models.requirements import RequirementItem, RequirementQuestion, RequirementsMap
from app.schemas.requirements import (
    Coverage,
    ItemRead,
    ItemUpdate,
    PhaseRead,
    QuestionRead,
    RequirementsRead,
    SourceRead,
)
from app.services.agent.run_service import RunService
from app.services.ai.gateway import ModelGateway, ProviderFactory
from app.services.requirements import planner
from app.services.requirements import reader as rd

_limiter = SlidingWindowLimiter(attempts=12, window_seconds=3600)  # intakes per project per hour
_user_limiter = SlidingWindowLimiter(attempts=20, window_seconds=3600)  # intakes per user per hour
_IN_FLIGHT: set[uuid.UUID] = set()
_shared = SharedLimiter(lambda: get_session_factory())  # S2-011b: the count every worker shares


@dataclass
class ReaderDeps:
    provider_factory: ProviderFactory | None = None
    settings: Settings | None = None


class RequirementsService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # -- reading -----------------------------------------------------------------------------

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.s.get(Project, project_id)
        if project is None:
            raise AppError("not_found", "project not found", 404)
        return project

    async def _map(self, project_id: uuid.UUID) -> RequirementsMap | None:
        return (
            await self.s.execute(
                select(RequirementsMap).where(RequirementsMap.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def _items(self, map_id: uuid.UUID) -> list[RequirementItem]:
        rows = await self.s.execute(
            select(RequirementItem)
            .where(RequirementItem.map_id == map_id)
            .order_by(RequirementItem.created_at, RequirementItem.id)
        )
        return list(rows.scalars())

    async def _questions(self, map_id: uuid.UUID) -> list[RequirementQuestion]:
        rows = await self.s.execute(
            select(RequirementQuestion)
            .where(RequirementQuestion.map_id == map_id)
            .order_by(RequirementQuestion.created_at, RequirementQuestion.id)
        )
        return list(rows.scalars())

    async def get(self, project_id: uuid.UUID) -> RequirementsRead:
        await self._project(project_id)
        m = await self._map(project_id)
        if m is None:
            return self._render(project_id, None, [], [])
        return self._render(project_id, m, await self._items(m.id), await self._questions(m.id))

    @staticmethod
    def _render(
        project_id: uuid.UUID,
        m: RequirementsMap | None,
        items: list[RequirementItem],
        questions: list[RequirementQuestion],
    ) -> RequirementsRead:
        n_open = sum(1 for i in items if i.status == "open")
        n_cov = sum(1 for i in items if i.status == "covered")
        n_out = sum(1 for i in items if i.status == "out_of_scope")
        scoped = n_open + n_cov
        return RequirementsRead(
            id=m.id if m else None,
            project_id=project_id,
            status=m.status if m else "empty",
            items=[ItemRead.model_validate(i) for i in items],
            questions=[QuestionRead.model_validate(q) for q in questions],
            sources=[SourceRead(**s) for s in (m.sources if m else [])],
            coverage=Coverage(
                total=len(items),
                open=n_open,
                covered=n_cov,
                out_of_scope=n_out,
                percent_covered=round(100 * n_cov / scoped) if scoped else 0,
                open_questions=sum(1 for q in questions if q.state == "open"),
            ),
            phases=[PhaseRead(**p) for p in planner.suggest_phases(items)] if items else [],  # type: ignore[arg-type]
            created_at=m.created_at if m else None,
            updated_at=m.updated_at if m else None,
        )

    async def _refresh_status(self, m: RequirementsMap) -> None:
        items, qs = await self._items(m.id), await self._questions(m.id)
        m.status = (
            "draft" if not items else "needs_answers" if any(q.state == "open" for q in qs) else "ready"
        )

    # -- intake ------------------------------------------------------------------------------

    async def _limited(self, shared_key: str, local_key: str, local: SlidingWindowLimiter) -> int | None:
        """None = allowed, else Retry-After seconds. The in-process window is the cheap first
        check; the shared window (all workers) is the one that bounds the total."""
        if not local.allow(local_key):
            return local.retry_after(local_key)
        bind = self.s.bind
        factory = async_sessionmaker(bind, expire_on_commit=False) if bind is not None else None
        return await _shared.hit(shared_key, local.attempts, int(local.window), factory)

    async def intake(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        prompt: str | None,
        files: list[tuple[str, bytes]],
        deps: ReaderDeps,
    ) -> RequirementsRead:
        project = await self._project(project_id)
        if not (prompt and prompt.strip()) and not files:
            raise AppError("intake_empty", "send a prompt, files, or both", 422)
        if len(files) > rd.MAX_FILES:
            raise AppError("too_many_files", f"at most {rd.MAX_FILES} files per intake", 413)
        if sum(len(d) for _, d in files) > rd.MAX_TOTAL_BYTES:
            raise AppError("files_too_large", "the files together are too large", 413)
        ukey = str(user_id)  # before any parsing: refused intakes must not cost CPU
        user_wait = await self._limited(f"intake:user:{ukey}", ukey, _user_limiter)
        if user_wait is not None:
            raise AppError(
                "intake_user_rate_limited",
                "too many intakes from you; try again later",
                429,
                headers={"Retry-After": str(user_wait)},
            )
        docs: list[rd.ReadDoc] = []
        if prompt and prompt.strip():
            docs.append(rd.read_prompt(prompt))
        for name, data in files:  # all validated before any model call; extraction off the loop
            docs.append(await rd.read_document_async(name, data))

        if project_id in _IN_FLIGHT:
            raise AppError("intake_in_progress", "an intake is already running for this project", 409)
        project_wait = await self._limited(f"intake:project:{project_id}", str(project_id), _limiter)
        if project_wait is not None:
            raise AppError(
                "intake_rate_limited",
                "too many intakes for this project; try again later",
                429,
                headers={"Retry-After": str(project_wait)},
            )
        _IN_FLIGHT.add(project_id)
        try:
            await self._run_intake(project, user_id, docs, deps)
        finally:
            _IN_FLIGHT.discard(project_id)
        return await self.get(project_id)

    async def _run_intake(
        self, project: Project, user_id: uuid.UUID, docs: list[rd.ReadDoc], deps: ReaderDeps
    ) -> None:
        """Every chunk is a paid model call, so its items are committed before the next call: a
        budget or provider error mid-intake keeps the work already paid for."""
        project_id = project.id
        settings = deps.settings or get_settings()
        gateway = ModelGateway(self.s, settings, deps.provider_factory)
        reader = rd.QuarantinedReader(gateway, project.organization_id, project_id)
        m = await self._map(project_id)
        if m is None:
            m = RequirementsMap(project_id=project_id, created_by=user_id, sources=[], status="draft")
            self.s.add(m)
            await self.s.flush()
        seen = {(i.kind, rd.norm(i.text)) for i in await self._items(m.id)}
        known = {rd.norm(q.text) for q in await self._questions(m.id)}
        try:
            async for doc, last, items, gaps in reader.read_stream(docs):
                for s in rd.merge_items(items, seen):
                    seen.add((s.item.kind, rd.norm(s.item.text)))
                    self.s.add(
                        RequirementItem(
                            project_id=project_id,
                            map_id=m.id,
                            kind=s.item.kind,
                            text=s.item.text,
                            subject=s.item.subject,
                            value=s.item.value,
                            source_doc=s.doc,
                            source_page=s.item.page,
                            source_section=s.item.section,
                            status="out_of_scope" if s.item.kind == "out_of_scope" else "open",
                        )
                    )
                for q in rd.dedupe_questions(gaps, known):
                    known.add(rd.norm(q.text))
                    self._add_question(project_id, m.id, q)
                if last:
                    m.sources = [s for s in m.sources if s["name"] != doc.name] + [
                        {
                            "name": doc.name,
                            "kind": doc.kind,
                            "pages": doc.pages,
                            "chunks": len(doc.chunks),
                            "chars": doc.chars,
                        }
                    ]
                await self.s.flush()
                await self.s.commit()
        except Exception:
            await self._finalize(m, project_id, known)
            raise
        await self._finalize(m, project_id, known)

    def _add_question(self, project_id: uuid.UUID, map_id: uuid.UUID, q: rd.Question) -> None:
        self.s.add(
            RequirementQuestion(
                project_id=project_id, map_id=map_id, text=q.text, assumption=q.assumption, state="open"
            )
        )

    async def _finalize(self, m: RequirementsMap, project_id: uuid.UUID, known: set[str]) -> None:
        """Conflicts across everything read so far, then the map status; always committed."""
        items = await self._items(m.id)
        views = [rd.ItemView(i.kind, i.text, i.subject, i.value, i.source_doc) for i in items]
        for q in rd.dedupe_questions(rd.detect_conflicts(views), known):
            self._add_question(project_id, m.id, q)
        await self.s.flush()
        await self._refresh_status(m)
        await self.s.commit()

    # -- edits -------------------------------------------------------------------------------

    async def answer(
        self, project_id: uuid.UUID, qid: uuid.UUID, answer: str | None, accept: bool
    ) -> RequirementsRead:
        q = (
            await self.s.execute(
                select(RequirementQuestion).where(
                    RequirementQuestion.id == qid, RequirementQuestion.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        if q is None:
            raise AppError("not_found", "question not found", 404)
        if accept:
            q.answer, q.state = None, "assumed"
        else:
            q.answer, q.state = (rd.clean_text(answer, 2000) or "").strip() or None, "answered"
            if q.answer is None:
                raise AppError("invalid_answer", "the answer is empty", 422)
        m = await self.s.get(RequirementsMap, q.map_id)
        assert m is not None
        await self.s.flush()
        await self._refresh_status(m)
        await self.s.commit()
        return await self.get(project_id)

    async def update_item(
        self, project_id: uuid.UUID, item_id: uuid.UUID, body: ItemUpdate
    ) -> RequirementsRead:
        it = (
            await self.s.execute(
                select(RequirementItem).where(
                    RequirementItem.id == item_id, RequirementItem.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        if it is None:
            raise AppError("not_found", "requirement not found", 404)
        fields = body.model_fields_set
        if "text" in fields and body.text is not None:
            text = rd.clean_text(body.text, rd.TEXT_CAP)
            if text is None:
                raise AppError("invalid_text", "the text is empty", 422)
            it.text = text
        if "status" in fields and body.status is not None:
            it.status = body.status
        if "covered_by" in fields:
            it.covered_by = rd.clean_text(body.covered_by, 200) if body.covered_by else None
        await self.s.commit()
        return await self.get(project_id)

    # -- start a run -------------------------------------------------------------------------

    async def start_run(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        accept_assumptions: bool,
        phase: int,
        workspace_id: uuid.UUID | None,
    ) -> AiRun:
        await self._project(project_id)
        m = await self._map(project_id)
        if m is None:
            raise AppError("requirements_empty", "add requirements first", 409)
        items, qs = await self._items(m.id), await self._questions(m.id)
        if not planner.in_scope(items):
            raise AppError("requirements_empty", "there is nothing in scope to build", 409)
        open_qs = [q for q in qs if q.state == "open"]
        if open_qs and not accept_assumptions:
            raise AppError(
                "questions_open",
                f"{len(open_qs)} clarifying question(s) are unanswered; answer them or accept the assumptions",
                409,
                details=[{"question_id": str(q.id), "text": q.text} for q in open_qs],
            )
        if open_qs:
            for q in open_qs:
                q.state = "assumed"
            await self.s.flush()
            await self._refresh_status(m)
        try:
            goal, _ = planner.build_goal(items, qs, phase)
        except ValueError:
            raise AppError("unknown_phase", "that phase does not exist for this map", 422) from None
        # Only the map-derived goal reaches the agent; raw document text is never stored or passed.
        return await RunService(self.s).create(project_id, user_id, goal, workspace_id)
