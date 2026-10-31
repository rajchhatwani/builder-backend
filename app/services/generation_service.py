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
from app.services.auth_secrets_service import AuthSecretsService
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

    async def preview(self, project_id: uuid.UUID) -> PreviewResponse:
        spec, files = await self._render(project_id)
        entries = manifest(files)
        return PreviewResponse(
            spec_hash=spec_hash(spec),
            total_files=len(entries),
            total_size=sum(int(e["size"]) for e in entries),
            files=[FileInfo(path=str(e["path"]), size=int(e["size"])) for e in entries],
        )

    async def download(self, project_id: uuid.UUID) -> tuple[bytes, str, Generation]:
        """Render, record the generation (spec snapshot + manifest) and return the zip."""
        spec, files = await self._render(project_id)
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
