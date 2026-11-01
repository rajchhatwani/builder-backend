import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generator import InvalidSpecError, generate
from app.core.generator.archive import build_zip, manifest
from app.core.generator.base import FileTree
from app.core.spec_models import Spec, SpecAuthSecrets, spec_hash
from app.exceptions import AppError
from app.models.generation import Generation
from app.schemas.generation import (
    FileInfo,
    GenerationDetail,
    GenerationSummary,
    PreviewResponse,
)
from app.schemas.migration_plan import (
    MigrationPlanBody,
    MigrationPlanRequest,
    MigrationPlanResponse,
    plan_response_dict,
)
from app.services.auth_secrets_service import AuthSecretsService
from app.services.migration_planner import (
    MigrationPlan,
    MigrationPlanError,
    plan_migration,
    render_text,
)
from app.services.spec_service import SpecService


def _summary(generation: Generation) -> GenerationSummary:
    return GenerationSummary(
        id=generation.id,
        project_id=generation.project_id,
        spec_hash=generation.spec_hash,
        file_count=len(generation.file_manifest),
        total_size=sum(int(f["size"]) for f in generation.file_manifest),
        created_at=generation.created_at,
    )


class GenerationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _render(self, project_id: uuid.UUID) -> tuple[Spec, FileTree]:
        spec = await SpecService(self.session).assemble(project_id)

        # Inject decrypted secrets into the spec before generation.
        # spec.auth.secrets has exclude=True so they never reach the DB
        # snapshot or any HTTP response body.
        if spec.auth is not None:
            raw_secrets = await AuthSecretsService(self.session).get_for_generator(project_id)
            spec.auth.secrets = SpecAuthSecrets(**raw_secrets)

        try:
            return spec, generate(spec)
        except InvalidSpecError as exc:
            raise AppError(
                code="spec_invalid",
                message=f"spec has {len(exc.issues)} validation issue(s); fix them to generate",
                status_code=422,
                details=[issue.model_dump() for issue in exc.issues],
            ) from exc

    async def _old_spec(
        self,
        project_id: uuid.UUID,
        new: Spec,
        against: uuid.UUID | None,
        accept_unreadable: bool | None = False,
    ) -> tuple[Spec | None, Generation | None, bool]:
        """(old spec, generation it came from, snapshot unusable). None spec = first generation.

        A generation whose snapshot cannot be read is NOT a first generation: it fails closed
        (409 `migration_baseline_unreadable`) unless the caller explicitly accepts it. Passing
        `accept_unreadable=None` returns it as unusable without raising (preview only)."""
        if against is not None:
            gen = await self.session.get(Generation, against)
            if gen is None or gen.project_id != project_id:
                raise AppError(code="not_found", message="generation not found", status_code=404)
        else:
            gen = (
                await self.session.execute(
                    select(Generation)
                    .where(Generation.project_id == project_id)
                    .order_by(Generation.created_at.desc(), Generation.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
        if gen is None:
            return None, None, False
        try:
            return Spec.model_validate(gen.spec_snapshot), gen, False
        except Exception:  # noqa: BLE001 - any unreadable shape (corrupt, null, old schema)
            if accept_unreadable is False:
                raise AppError(
                    code="migration_baseline_unreadable",
                    message=(
                        "the previous generation's spec snapshot cannot be read, so the "
                        "destructive-change check cannot run; repeat with "
                        "accept_unreadable_baseline=true (editor or owner) to treat this as a "
                        "first generation"
                    ),
                    status_code=409,
                    details=[{"generation_id": str(gen.id)}],
                ) from None
            return None, gen, True

    def _plan(
        self,
        old: Spec | None,
        new: Spec,
        renames: list[dict[str, object]],
    ) -> tuple[MigrationPlan, bool]:
        base = old
        first = old is None
        if base is None:
            base = Spec(project=new.project)
        try:
            return plan_migration(base, new, renames or None), first
        except MigrationPlanError as exc:
            raise AppError(
                code="migration_plan_invalid", message=str(exc), status_code=422
            ) from exc

    def _response(
        self,
        plan: MigrationPlan,
        old: Spec | None,
        new: Spec,
        gen: Generation | None,
        unusable: bool,
    ) -> MigrationPlanResponse:
        return MigrationPlanResponse(
            plan=MigrationPlanBody(**plan.to_dict()),
            text=render_text(plan),
            old_spec_hash=spec_hash(old) if old is not None else None,
            new_spec_hash=spec_hash(new),
            against_generation_id=gen.id if gen is not None and old is not None else None,
            first_generation=old is None and not unusable,
            old_snapshot_unusable=unusable,
            allow_destructive_required=plan.requires_confirmation,
        )

    async def migration_plan(
        self,
        project_id: uuid.UUID,
        body: MigrationPlanRequest,
        accept_unreadable_baseline: bool = False,
    ) -> MigrationPlanResponse:
        new = await SpecService(self.session).assemble(project_id)
        old, gen, unusable = await self._old_spec(
            project_id, new, body.against_generation_id, accept_unreadable_baseline
        )
        renames = [r.model_dump(by_alias=True, exclude_none=True) for r in body.renames]
        plan, _ = self._plan(old, new, renames)
        return self._response(plan, old, new, gen, unusable)

    async def preview(self, project_id: uuid.UUID) -> PreviewResponse:
        spec, files = await self._render(project_id)
        old, gen, unusable = await self._old_spec(project_id, spec, None, None)
        plan, _ = self._plan(old, spec, [])
        entries = manifest(files)
        return PreviewResponse(
            spec_hash=spec_hash(spec),
            total_files=len(entries),
            total_size=sum(int(e["size"]) for e in entries),
            files=[FileInfo(path=str(e["path"]), size=int(e["size"])) for e in entries],
            migration=self._response(plan, old, spec, gen, unusable),
        )

    async def download(
        self,
        project_id: uuid.UUID,
        allow_destructive: bool = False,
        accept_unreadable_baseline: bool = False,
    ) -> tuple[bytes, str, Generation]:
        """Render, record the generation (spec snapshot + manifest) and return the zip.

        A plan with a destructive step against the last generation is refused (409, with the plan)
        unless the caller explicitly passes `allow_destructive`."""
        spec, files = await self._render(project_id)
        old, gen, unusable = await self._old_spec(
            project_id, spec, None, accept_unreadable_baseline
        )
        plan, _ = self._plan(old, spec, [])
        if not plan.apply_allowed(allow_destructive):
            resp = self._response(plan, old, spec, gen, unusable)
            raise AppError(
                code="destructive_migration",
                message=(
                    "this change drops data; review the migration plan and repeat the request "
                    "with allow_destructive=true to generate anyway"
                ),
                status_code=409,
                details=[plan_response_dict(resp)],
            )
        generation = Generation(
            project_id=project_id,
            spec_snapshot=spec.model_dump(mode="json"),
            spec_hash=spec_hash(spec),
            file_manifest=manifest(files),
        )
        self.session.add(generation)
        await self.session.commit()
        return build_zip(spec.project.slug, files), f"{spec.project.slug}.zip", generation

    async def list(
        self, project_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[GenerationSummary], int]:
        await SpecService(self.session)._get_project_or_404(project_id)
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(Generation)
                .where(Generation.project_id == project_id)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(Generation)
                .where(Generation.project_id == project_id)
                .order_by(Generation.created_at.desc(), Generation.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return [_summary(g) for g in rows], total

    async def get(self, generation_id: uuid.UUID) -> GenerationDetail:
        generation = await self.session.get(Generation, generation_id)
        if generation is None:
            raise AppError(code="not_found", message="generation not found", status_code=404)
        return GenerationDetail(
            **_summary(generation).model_dump(),
            spec_snapshot=generation.spec_snapshot,
            file_manifest=generation.file_manifest,
        )
