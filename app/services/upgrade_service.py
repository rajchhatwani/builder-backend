"""Upgrade proposals (P3) and project scorecards (P4)."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core import scorecard as sc
from app.core import upgrade_engine as ue
from app.core.generator import InvalidSpecError, generate
from app.core.generator.base import FileTree
from app.core.generator.engine import module_registry
from app.core.spec_models import Spec, spec_hash
from app.core.validation import validate
from app.exceptions import AppError
from app.models.enums import AuditResult
from app.models.generation import Generation
from app.models.mixins import _utcnow
from app.models.registry import RegistryHookEntry
from app.models.upgrade import UpgradeProposal
from app.schemas.upgrade import UpgradeProposalDetail, UpgradeProposalSummary
from app.services import audit_service
from app.services.access_service import Principal
from app.services.spec_service import SpecService


def current_block_versions() -> dict[str, str]:
    return {bid: m.version for bid, m in module_registry().items()}


def summary(p: UpgradeProposal) -> UpgradeProposalSummary:
    return UpgradeProposalSummary(
        id=p.id,
        project_id=p.project_id,
        base_generation_id=p.base_generation_id,
        status=p.status,  # type: ignore[arg-type]
        from_generator_version=p.from_generator_version,
        to_generator_version=p.to_generator_version,
        block_changes=p.block_changes,
        file_count=len(p.files),
        auto_apply_eligible=p.auto_apply_eligible,
        created_at=p.created_at,
        decided_at=p.decided_at,
    )


def detail(p: UpgradeProposal) -> UpgradeProposalDetail:
    return UpgradeProposalDetail(
        **summary(p).model_dump(),
        created_by=p.created_by,
        files=p.files,
        kept=list(p.scorecard.get("kept", [])),
        patch_size=len(p.patch_text.encode("utf-8")),
        sbom_diff=p.sbom_diff,
        migrations=p.migrations,
        scorecard=p.scorecard,
    )


class UpgradeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _project(self, project_id: uuid.UUID) -> None:
        await SpecService(self.session)._get_project_or_404(project_id)

    async def _latest(self, project_id: uuid.UUID) -> Generation | None:
        return (
            await self.session.execute(
                select(Generation)
                .options(undefer(Generation.file_blob))
                .where(Generation.project_id == project_id)
                .order_by(Generation.created_at.desc(), Generation.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    def _trees(self, gen: Generation) -> tuple[FileTree, FileTree]:
        """(base tree, tree the current generator renders from the same spec snapshot)."""
        if not gen.file_blob:
            raise AppError(
                "baseline_unavailable",
                "this generation stored no file tree; download the project once more to create a baseline",
                409,
            )
        try:
            base = ue.decode_blob(gen.file_blob)
            spec = Spec.model_validate(gen.spec_snapshot)
            new = generate(spec)  # plan_upgrade lists its custom paths as kept and drops them from the diff
        except ue.UpgradeError as exc:
            raise AppError(exc.code, exc.message, 409) from exc
        except InvalidSpecError as exc:
            raise AppError(
                "spec_invalid",
                f"the baseline spec has {len(exc.issues)} validation issue(s) under the current generator",
                422,
                details=[i.model_dump() for i in exc.issues],
            ) from exc
        except ValueError as exc:
            raise AppError("baseline_unreadable", "the baseline spec snapshot cannot be read", 409) from exc
        return base, new

    # -- scorecard -----------------------------------------------------------------------------
    async def scorecard(self, project_id: uuid.UUID) -> dict[str, Any]:
        await self._project(project_id)
        spec = await SpecService(self.session).assemble(project_id)
        gen = await self._latest(project_id)
        base: FileTree | None = None
        regen: FileTree | None = None
        if gen is not None and gen.file_blob:
            try:
                base, regen = self._trees(gen)
            except AppError:
                base = regen = None
        ledger = (
            await self.session.execute(select(RegistryHookEntry).where(RegistryHookEntry.project_id == project_id))
        ).scalars()
        inp = sc.ScorecardInput(
            project_id=str(project_id),
            spec=spec,
            validation_issues=len(validate(spec)),
            latest_spec_hash=gen.spec_hash if gen is not None else None,
            current_spec_hash=spec_hash(spec),
            recorded_blocks=dict(gen.block_versions or {}) if gen is not None and gen.block_versions else None,
            current_blocks=current_block_versions(),
            base_tree=base,
            regenerated_tree=regen,
            hook_entries=[{"hook_name": e.hook_name, "approved_by": e.approved_by} for e in ledger],
        )
        return sc.compute_scorecard(inp)

    # -- proposals -----------------------------------------------------------------------------
    async def create(self, project_id: uuid.UUID, principal: Principal, organization_id: uuid.UUID | None, request_id: str | None) -> UpgradeProposal:
        await self._project(project_id)
        gen = await self._latest(project_id)
        if gen is None:
            raise AppError("no_baseline", "generate the project once before asking for an upgrade", 409)
        open_one = (
            await self.session.execute(
                select(UpgradeProposal).where(
                    UpgradeProposal.project_id == project_id,
                    UpgradeProposal.base_generation_id == gen.id,
                    UpgradeProposal.status == "open",
                )
            )
        ).scalar_one_or_none()
        if open_one is not None:
            raise AppError(
                "proposal_open",
                "an upgrade proposal for this generation is already open",
                409,
                details=[{"proposal_id": str(open_one.id)}],
            )
        base, new = self._trees(gen)
        plan = ue.plan_upgrade(base, new)
        changes = ue.block_changes(dict(gen.block_versions or {}), current_block_versions())
        if plan.empty and not changes:
            raise AppError("up_to_date", "the project already matches the current generator", 409)
        card = await self.scorecard(project_id)
        card["kept"] = plan.kept
        proposal = UpgradeProposal(
            project_id=project_id,
            created_by=principal.user.id,
            base_generation_id=gen.id,
            status="open",
            from_generator_version=gen.generator_version,
            to_generator_version=ue.GENERATOR_VERSION,
            block_changes=changes,
            files=plan.files,
            patch_text=plan.patch_text,
            sbom_diff=plan.sbom,
            migrations=plan.migrations,
            scorecard=card,
            auto_apply_eligible=ue.auto_apply_eligible(
                changes,
                plan.files,
                plan.migrations,
                bool(card["passing"]),
                sbom=plan.sbom,
                generator_bump=ue.classify_bump(gen.generator_version, ue.GENERATOR_VERSION),
            ),
        )
        self.session.add(proposal)
        await audit_service.record(
            self.session, action="upgrade.proposal_create", actor_id=principal.user.id,
            actor_email=principal.user.email, via=principal.via, project_id=project_id,
            organization_id=organization_id, target_type="upgrade_proposal", target_id=proposal.id,
            request_id=request_id,
            detail={"files": len(plan.files), "blocks": len(changes), "auto": proposal.auto_apply_eligible},
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:  # a parallel request opened one between our check and insert
            await self.session.rollback()
            raise AppError("proposal_open", "an upgrade proposal for this generation is already open", 409) from exc
        return proposal

    async def list(self, project_id: uuid.UUID, limit: int, offset: int) -> tuple[list[UpgradeProposal], int]:
        await self._project(project_id)
        total = (
            await self.session.execute(
                select(func.count()).select_from(UpgradeProposal).where(UpgradeProposal.project_id == project_id)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(UpgradeProposal)
                .where(UpgradeProposal.project_id == project_id)
                .order_by(UpgradeProposal.created_at.desc(), UpgradeProposal.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), total

    async def get(self, project_id: uuid.UUID, proposal_id: uuid.UUID, lock: bool = False) -> UpgradeProposal:
        await self._project(project_id)
        q = select(UpgradeProposal).where(UpgradeProposal.id == proposal_id, UpgradeProposal.project_id == project_id)
        if lock:
            q = q.with_for_update()
        row = (await self.session.execute(q)).scalar_one_or_none()
        if row is None:
            raise AppError("not_found", "upgrade proposal not found", 404)
        return row

    async def decide(
        self, project_id: uuid.UUID, proposal_id: uuid.UUID, status: str, principal: Principal,
        organization_id: uuid.UUID | None, request_id: str | None,
    ) -> UpgradeProposal:
        row = await self.get(project_id, proposal_id, lock=True)
        if row.status != "open":
            raise AppError("proposal_closed", f"this proposal is already {row.status}", 409)
        row.status = status
        row.decided_at = _utcnow()
        await audit_service.record(
            self.session, action=f"upgrade.proposal_{status}", result=AuditResult.ok,
            actor_id=principal.user.id, actor_email=principal.user.email, via=principal.via,
            project_id=project_id, organization_id=organization_id, target_type="upgrade_proposal",
            target_id=row.id, request_id=request_id,
        )
        await self.session.commit()
        return row
