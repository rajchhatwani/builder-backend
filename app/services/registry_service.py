"""Registry: block versions, hooks ledger, dependency lock. Append-only: rows are never edited
or deleted (the one exception is a hook's `approved_by`, set once by an owner)."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.project import Project
from app.models.registry import RegistryBlockVersion, RegistryDepLock, RegistryHookEntry
from app.schemas.ai_registry import (
    BlockVersionWrite,
    DepLockWrite,
    HookEntryWrite,
    RegistryProjectRead,
)


class RegistryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- block versions ----------------------------------------------------------------------
    async def list_blocks(self, project_id: uuid.UUID) -> list[RegistryBlockVersion]:
        q = select(RegistryBlockVersion).where(RegistryBlockVersion.project_id == project_id)
        rows = await self.session.execute(
            q.order_by(RegistryBlockVersion.name, RegistryBlockVersion.created_at)
        )
        return list(rows.scalars())

    async def add_block(
        self, project_id: uuid.UUID, body: BlockVersionWrite
    ) -> tuple[RegistryBlockVersion, bool]:
        existing = (
            await self.session.execute(
                select(RegistryBlockVersion).where(
                    RegistryBlockVersion.project_id == project_id,
                    RegistryBlockVersion.name == body.name,
                    RegistryBlockVersion.version == body.version,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.content_hash != body.content_hash:
                raise AppError(
                    "block_version_immutable",
                    "this block version is already recorded with a different content hash",
                    409,
                )
            return existing, False
        row = RegistryBlockVersion(project_id=project_id, **body.model_dump())
        self.session.add(row)
        await self.session.flush()
        return row, True

    # -- hooks ledger ------------------------------------------------------------------------
    async def list_hooks(self, project_id: uuid.UUID) -> list[RegistryHookEntry]:
        q = select(RegistryHookEntry).where(RegistryHookEntry.project_id == project_id)
        rows = await self.session.execute(
            q.order_by(RegistryHookEntry.hook_name, RegistryHookEntry.created_at)
        )
        return list(rows.scalars())

    async def add_hook(
        self, project_id: uuid.UUID, body: HookEntryWrite
    ) -> tuple[RegistryHookEntry, bool]:
        existing = (
            await self.session.execute(
                select(RegistryHookEntry).where(
                    RegistryHookEntry.project_id == project_id,
                    RegistryHookEntry.hook_name == body.hook_name,
                    RegistryHookEntry.content_hash == body.content_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
        row = RegistryHookEntry(project_id=project_id, **body.model_dump())
        self.session.add(row)
        await self.session.flush()
        return row, True

    async def approve_hook(
        self, project_id: uuid.UUID, entry_id: uuid.UUID, approver: uuid.UUID
    ) -> RegistryHookEntry:
        row = (
            await self.session.execute(
                select(RegistryHookEntry)
                .where(RegistryHookEntry.id == entry_id, RegistryHookEntry.project_id == project_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise AppError("not_found", "not found", 404)
        if row.approved_by is not None:
            raise AppError("hook_already_approved", "this hook entry is already approved", 409)
        row.approved_by = approver
        await self.session.flush()
        return row

    # -- dependency lock ---------------------------------------------------------------------
    async def list_deps(self, project_id: uuid.UUID) -> list[RegistryDepLock]:
        q = select(RegistryDepLock).where(RegistryDepLock.project_id == project_id)
        rows = await self.session.execute(q.order_by(RegistryDepLock.package, RegistryDepLock.version))
        return list(rows.scalars())

    async def add_dep(
        self, project_id: uuid.UUID, body: DepLockWrite
    ) -> tuple[RegistryDepLock, bool]:
        existing = (
            await self.session.execute(
                select(RegistryDepLock).where(
                    RegistryDepLock.project_id == project_id,
                    RegistryDepLock.package == body.package,
                    RegistryDepLock.version == body.version,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.hash != body.hash:
                raise AppError(
                    "dependency_hash_mismatch",
                    "this package version is locked with a different hash",
                    409,
                )
            return existing, False
        row = RegistryDepLock(project_id=project_id, **body.model_dump())
        self.session.add(row)
        await self.session.flush()
        return row, True

    # -- projects registry view --------------------------------------------------------------
    async def projects_view(self, org_id: uuid.UUID) -> list[RegistryProjectRead]:
        def count(model: Any, extra: Any = None) -> Any:
            q = select(func.count()).where(model.project_id == Project.id)
            if extra is not None:
                q = q.where(extra)
            return q.scalar_subquery()

        stmt = (
            select(
                Project.id,
                Project.name,
                Project.slug,
                Project.version,
                count(RegistryBlockVersion),
                count(RegistryHookEntry),
                count(RegistryHookEntry, RegistryHookEntry.approved_by.is_(None)),
                count(RegistryDepLock),
            )
            .where(Project.organization_id == org_id)
            .order_by(Project.name)
        )
        return [
            RegistryProjectRead(
                project_id=r[0],
                name=r[1],
                slug=r[2],
                spec_version=r[3],
                block_versions=r[4],
                hooks=r[5],
                hooks_unapproved=r[6],
                dependencies=r[7],
            )
            for r in (await self.session.execute(stmt)).all()
        ]
