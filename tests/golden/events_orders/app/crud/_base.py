"""Generic async repository. Entity repositories only declare what is configurable."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.crud.lifecycle import Hook, HookContext, run_stage
from app.models._base import Base


class Repository[ModelT: Base]:
    model: type[ModelT]
    soft_delete: ClassVar[bool] = False
    filterable: ClassVar[tuple[str, ...]] = ()
    sortable: ClassVar[tuple[str, ...]] = ()
    searchable: ClassVar[tuple[str, ...]] = ()
    # relationship attributes loaded with every read (the Read schema exposes their ids)
    eager: ClassVar[tuple[str, ...]] = ()
    # payload key -> model the foreign key must point at
    references: ClassVar[dict[str, type[Base]]] = {}
    # payload key -> model of a many_to_many relationship set from a list of ids
    many_to_many: ClassVar[dict[str, type[Base]]] = {}
    # payload keys that hold the id of an uploaded file, and the check each id must pass
    file_fields: ClassVar[tuple[str, ...]] = ()
    file_check: ClassVar[Callable[..., Awaitable[None]] | None] = None
    # lifecycle hooks: stage (before_save | after_save | after_commit) -> async callables(ctx)
    hooks: ClassVar[dict[str, tuple[Hook, ...]]] = {}

    def __init__(
        self,
        session: AsyncSession,
        *,
        scope: dict[str, Any] | None = None,
        owner_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
        caller_tenant_id: uuid.UUID | None = None,
        caller: Any = None,
        policy: Any = None,
    ) -> None:
        self.session = session
        # column -> value every read and write is restricted to (row-level access rules)
        self.scope = scope or {}
        # recorded as created_by_id on new rows
        self.owner_id = owner_id
        # recorded as tenant_id on new rows
        self.tenant_id = tenant_id
        # the caller's tenant: a reference may only point at rows of this tenant (see _inside_tenant)
        self.caller_tenant_id = caller_tenant_id or tenant_id
        # the signed-in user making the request (file fields are checked against them)
        self.caller = caller
        # abac / pbac: decides which rows are visible and checks what is written
        self.policy = policy

    # --- query building -----------------------------------------------------------

    def _col(self, name: str) -> Any:
        return self.model.__table__.c[name]

    def _alive(self, *, policy: bool = True) -> list[Any]:
        """Conditions every query starts from: not soft-deleted, and inside the access scope."""
        conditions = [self._col("deleted_at").is_(None)] if self.soft_delete else []
        conditions.extend(self._col(name) == value for name, value in self.scope.items())
        if policy and self.policy is not None:
            conditions.extend(self.policy.row_conditions(self._col))
        return conditions

    def _loaders(self) -> list[Any]:
        return [selectinload(getattr(self.model, name)) for name in self.eager]

    def _order_by(self, sort: str | None) -> list[Any]:
        if not sort:
            return [self._col("created_at"), self._col("id")]
        order: list[Any] = []
        for term in (t.strip() for t in sort.split(",") if t.strip()):
            name = term.lstrip("-")
            if name not in self.sortable:
                allowed = ", ".join(self.sortable) or "none"
                raise AppError(
                    "invalid_sort",
                    f"cannot sort by {name!r}; sortable fields: {allowed}",
                    422,
                    [{"field": "sort"}],
                )
            col = self._col(name)
            order.append(col.desc() if term.startswith("-") else col.asc())
        order.append(self._col("id"))  # stable pagination
        return order

    def _conditions(self, filters: dict[str, Any], search: str | None) -> list[Any]:
        conditions = self._alive()
        for name, value in filters.items():
            conditions.append(self._col(name) == value)
        if search and self.searchable:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            conditions.append(
                sa.or_(*[self._col(n).ilike(pattern, escape="\\") for n in self.searchable])
            )
        return conditions

    # --- reads ---------------------------------------------------------------------

    async def list_items(
        self,
        page: PageParams,
        *,
        filters: dict[str, Any] | None = None,
        search: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[ModelT], int]:
        conditions = self._conditions(filters or {}, search)
        total = (
            await self.session.execute(
                sa.select(sa.func.count()).select_from(self.model).where(*conditions)
            )
        ).scalar_one()
        stmt = (
            sa.select(self.model)
            .where(*conditions)
            .order_by(*self._order_by(sort))
            .limit(page.limit)
            .offset(page.offset)
            .options(*self._loaders())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def get(self, item_id: uuid.UUID, *, policy: bool = True) -> ModelT:
        # policy=False: re-read a row this request just wrote. The write was already checked, and the
        # operation's own row filter may no longer match it (an update that closes a ticket).
        stmt = (
            sa.select(self.model)
            .where(self._col("id") == item_id, *self._alive(policy=policy))
            .options(*self._loaders())
            .execution_options(populate_existing=True)
        )
        item = (await self.session.execute(stmt)).scalars().first()
        if item is None:
            raise NotFoundError(f"{self.model.__name__} {item_id} not found")
        return item

    async def exists(self, item_id: uuid.UUID) -> bool:
        stmt = sa.select(self._col("id")).where(self._col("id") == item_id, *self._alive())
        return (await self.session.execute(stmt)).first() is not None

    # --- writes --------------------------------------------------------------------

    async def create(self, data: dict[str, Any]) -> ModelT:
        ctx = self._ctx("create", dict(data))
        await run_stage("before_save", self.hooks, ctx)
        values = ctx.values
        if self.owner_id is not None:
            values["created_by_id"] = self.owner_id
        if self.tenant_id is not None:
            values["tenant_id"] = self.tenant_id
        ctx.trace.append("guards")
        if self.policy is not None:
            self.policy.check_new_row(values)
        ctx.trace.append("validate")
        related = await self._pop_related(values)
        await self._check_references(values)
        ctx.trace.append("write")
        item = self.model(**values, **related)
        self.session.add(item)
        await self._flush()
        ctx.item = item
        await self._finish(ctx)
        return await self.get(item.id, policy=False)  # type: ignore[attr-defined]

    async def replace(self, item_id: uuid.UUID, data: dict[str, Any]) -> ModelT:
        return await self._apply(item_id, data)

    async def update(self, item_id: uuid.UUID, data: dict[str, Any]) -> ModelT:
        return await self._apply(item_id, data)

    async def delete(self, item_id: uuid.UUID) -> None:
        # Loaded without eager relationships on purpose: the database enforces the
        # relation's on_delete rule (cascade / set null / restrict).
        stmt = sa.select(self.model).where(self._col("id") == item_id, *self._alive())
        item = (await self.session.execute(stmt)).scalars().first()
        if item is None:
            raise NotFoundError(f"{self.model.__name__} {item_id} not found")
        ctx = self._ctx("delete", {})
        ctx.item = item
        await run_stage("before_save", self.hooks, ctx)
        ctx.trace.extend(("guards", "validate", "write"))
        if self.soft_delete:
            item.deleted_at = datetime.now(UTC)  # type: ignore[attr-defined]
        else:
            await self.session.delete(item)
        await self._flush()
        await self._finish(ctx)

    async def _apply(self, item_id: uuid.UUID, data: dict[str, Any]) -> ModelT:
        item = await self.get(item_id)
        ctx = self._ctx("update", dict(data))
        ctx.item = item
        await run_stage("before_save", self.hooks, ctx)
        values = ctx.values
        ctx.trace.append("guards")
        if self.policy is not None:
            before = {c.name: getattr(item, c.name) for c in self.model.__table__.columns}
            self.policy.check_changed_row({**before, **values})
        ctx.trace.append("validate")
        related = await self._pop_related(values)
        await self._check_references(values)
        ctx.trace.append("write")
        for key, value in {**values, **related}.items():
            setattr(item, key, value)
        await self._flush()
        await self._finish(ctx)
        return await self.get(item_id, policy=False)

    def _ctx(self, op: str, values: dict[str, Any]) -> HookContext:
        return HookContext(entity=self.model.__name__, op=op, values=values, caller=self.caller)

    async def _finish(self, ctx: HookContext) -> None:
        """after_save (inside the transaction), commit, after_commit (never fails the request)."""
        try:
            await run_stage("after_save", self.hooks, ctx)
        except Exception:
            await self.session.rollback()
            raise
        ctx.trace.append("commit")
        await self._commit()
        await run_stage("after_commit", self.hooks, ctx, fail_closed=False)

    async def _flush(self) -> None:
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "the request conflicts with existing data (duplicate value or referenced record)"
            ) from exc

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "the request conflicts with existing data (duplicate value or referenced record)"
            ) from exc

    def _inside_tenant(self, target: type[Base]) -> list[Any]:
        """Condition that keeps a referenced row inside the caller's tenant.

        A target with a tenant_id column belongs to a tenant, so a parent from another tenant
        (or any parent when the caller has no tenant) is treated as not existing: same error,
        so the response does not reveal that the foreign row exists.
        """
        column = target.__table__.c.get("tenant_id")
        if column is None:
            return []
        if self.caller_tenant_id is None:
            return [sa.false()]
        return [column == self.caller_tenant_id]

    async def _check_files(self, values: dict[str, Any]) -> None:
        for key in self.file_fields:
            value = values.get(key)
            if value is None or self.file_check is None:
                continue
            await self.file_check(self.session, value, self.caller, key)

    async def _check_references(self, values: dict[str, Any]) -> None:
        await self._check_files(values)
        for key, target in self.references.items():
            value = values.get(key)
            if value is None:
                continue
            stmt = sa.select(target.id).where(  # type: ignore[attr-defined]
                target.id == value,  # type: ignore[attr-defined]
                *self._inside_tenant(target),
            )
            if (await self.session.execute(stmt)).first() is None:
                raise AppError(
                    "invalid_reference",
                    f"{key} does not reference an existing record",
                    422,
                    [{"field": key}],
                )

    async def _pop_related(self, values: dict[str, Any]) -> dict[str, list[Any]]:
        """Remove many_to_many id lists from `values` and load the rows they name."""
        related: dict[str, list[Any]] = {}
        for key, target in self.many_to_many.items():
            if key not in values:
                continue
            ids = list(dict.fromkeys(values.pop(key) or []))
            rows: list[Any] = []
            if ids:
                stmt = sa.select(target).where(
                    target.id.in_(ids),  # type: ignore[attr-defined]
                    *self._inside_tenant(target),
                )
                by_id = {row.id: row for row in (await self.session.execute(stmt)).scalars()}
                missing = [str(i) for i in ids if i not in by_id]
                if missing:
                    raise AppError(
                        "invalid_reference",
                        f"{key} references records that do not exist",
                        422,
                        [{"field": key, "ids": missing}],
                    )
                rows = [by_id[i] for i in ids]
            related[key] = rows
        return related
