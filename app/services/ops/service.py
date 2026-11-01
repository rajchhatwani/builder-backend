"""The typed spec operations API: one place that applies, records, undoes and restores.

The dashboard routes and the MCP tools both call this service. Each public method is one
transaction: lock the project, apply through the existing services, prove the result equals the
registry's prediction, validate, append the op-log row, commit. Any failure rolls back, so
nothing is recorded for a change that did not happen, and nothing changes if recording fails.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation import ValidationIssue, validate
from app.exceptions import AppError
from app.models.platform import PlatformUser
from app.models.spec_op import SpecOp
from app.schemas.spec_ops import SpecOpActor, SpecOpInverse, SpecOpRead
from app.services.ops import dbapply
from app.services.ops.canon import canonical_bytes, canonical_hash
from app.services.ops.registry import Planned, dump, parse, plan
from app.services.ops.scope import Actor, OpScope, scope_of


@dataclass
class Applied:
    op: SpecOp
    result: Any  # the row the operation created or changed (an Entity, Field, Relation) or None


def _issue_key(i: ValidationIssue) -> tuple[str, str, str]:
    return (i.path, i.code, i.message)


def _err(code: str, message: str, status: int = 409) -> AppError:
    return AppError(code=code, message=message, status_code=status)


class OpsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- transaction frame ---------------------------------------------------------------

    async def _frame(self, project_id: uuid.UUID, actor: Actor) -> tuple[OpScope, bool]:
        scope = scope_of(self.session)
        owned = scope is None or scope.project_id != project_id
        if scope is not None and not owned:
            return scope, False
        if scope is not None:
            scope.close()
        return OpScope(self.session, project_id, actor), True

    async def _transaction(self, project_id: uuid.UUID, actor: Actor, body: Any) -> Any:
        scope, owned = await self._frame(project_id, actor)
        scope.mode = "explicit"
        try:
            await scope.lock()
            result = await body(scope)
            await scope.real_commit()
            scope.publish()
            return result
        except BaseException:
            await self.session.rollback()
            raise
        finally:
            scope.mode = "legacy"
            if owned:
                scope.close()

    # -- apply ---------------------------------------------------------------------------

    async def apply_op(
        self,
        project_id: uuid.UUID,
        op_type: str,
        payload: dict[str, Any],
        actor: Actor,
        *,
        validate_result: bool = True,
    ) -> Applied:
        """Apply one typed operation. With `validate_result` the operation is rejected (422,
        nothing recorded) when it leaves the spec with a validation issue it did not have."""

        async def body(scope: OpScope) -> Applied:
            return await self._run(scope, op_type, payload, actor, "do", None, validate_result)

        applied: Applied = await self._transaction(project_id, actor, body)
        return applied

    async def _run(
        self,
        scope: OpScope,
        op_type: str,
        payload: dict[str, Any],
        actor: Actor,
        origin: str,
        ref_seq: int | None,
        validate_result: bool,
        expect_before: str | None = None,
        expect_after: str | None = None,
    ) -> Applied:
        before = await scope.assemble()
        h_before = canonical_hash(before)
        if expect_before is not None and h_before != expect_before:
            raise _err(
                "spec_changed",
                "the spec changed outside the op-log since that operation; refusing to guess",
            )
        planned: Planned = plan(before, op_type, payload)
        result = await dbapply.run(self.session, scope.project_id, op_type, planned.payload)
        await self.session.flush()
        after = await scope.assemble()
        if canonical_bytes(after) != canonical_bytes(planned.after):
            raise _err("op_inconsistent", "the operation did not produce the predicted spec", 500)
        h_after = canonical_hash(after)
        if expect_after is not None and h_after != expect_after:
            raise _err("restore_mismatch", "the result does not match the recorded state")
        if validate_result:
            known = {_issue_key(i) for i in validate(before)}
            fresh = [i for i in validate(after) if _issue_key(i) not in known]
            if fresh:
                raise AppError(
                    code="spec_invalid",
                    message=f"the operation leaves {len(fresh)} new validation issue(s)",
                    status_code=422,
                    details=[i.model_dump() for i in fresh],
                )
        row = await scope.append(
            op_type=op_type,
            payload=dump(planned.payload),
            inverse_type=planned.inverse_type,
            inverse_payload=planned.inverse_payload,
            hash_before=h_before,
            hash_after=h_after,
            origin=origin,
            ref_seq=ref_seq,
            actor=actor,
        )
        scope.remember(after)
        return Applied(row, result)

    # -- log -----------------------------------------------------------------------------

    async def _rows(self, project_id: uuid.UUID) -> list[SpecOp]:
        return list(
            (
                await self.session.execute(
                    select(SpecOp).where(SpecOp.project_id == project_id).order_by(SpecOp.seq)
                )
            ).scalars()
        )

    @staticmethod
    def stacks(rows: list[SpecOp]) -> tuple[list[int], list[int]]:
        """(undo stack, redo stack) of op seqs, replayed from the log. A new change clears
        the redo stack, as in any editor."""
        undo: list[int] = []
        redo: list[int] = []
        for r in rows:
            if r.origin == "undo" and undo:
                redo.append(undo.pop())
            elif r.origin == "redo" and redo:
                undo.append(redo.pop())
            else:
                undo.append(r.seq)
                redo.clear()
        return undo, redo

    async def undo(self, project_id: uuid.UUID, actor: Actor) -> Applied:
        async def body(scope: OpScope) -> Applied:
            rows = await self._rows(project_id)
            undo, _ = self.stacks(rows)
            if not undo:
                raise _err("nothing_to_undo", "there is nothing to undo")
            target = next(r for r in rows if r.seq == undo[-1])
            inv = target.inverse
            return await self._run(
                scope, inv["op_type"], inv["payload"], actor, "undo", target.seq, False,
                expect_before=target.spec_hash_after, expect_after=target.spec_hash_before,
            )  # fmt: skip

        applied: Applied = await self._transaction(project_id, actor, body)
        return applied

    async def redo(self, project_id: uuid.UUID, actor: Actor) -> Applied:
        async def body(scope: OpScope) -> Applied:
            rows = await self._rows(project_id)
            _, redo = self.stacks(rows)
            if not redo:
                raise _err("nothing_to_redo", "there is nothing to redo")
            target = next(r for r in rows if r.seq == redo[-1])
            return await self._run(
                scope, target.op_type, target.payload, actor, "redo", target.seq, False,
                expect_before=target.spec_hash_before, expect_after=target.spec_hash_after,
            )  # fmt: skip

        applied: Applied = await self._transaction(project_id, actor, body)
        return applied

    async def restore(self, project_id: uuid.UUID, to_seq: int, actor: Actor) -> Applied:
        """Return the spec to the state right after op `to_seq` (0 = before the first op) by
        applying the recorded inverses newest-first, then check the exact recorded hash. The
        draft-only rule: this codebase has no locked or published spec state (a generation is an
        immutable copy, not a lock), so the only refusal is the organisation's own lock, which
        the request guard answers before this runs."""

        async def body(scope: OpScope) -> Applied:
            rows = await self._rows(project_id)
            if not rows:
                raise _err("nothing_to_restore", "the op-log is empty")
            if to_seq > rows[-1].seq:
                raise AppError(code="not_found", message="no such operation", status_code=404)
            if to_seq == rows[-1].seq:
                raise _err("already_there", "the spec is already at that state")
            target_hash = (
                rows[0].spec_hash_before
                if to_seq == 0
                else next(r for r in rows if r.seq == to_seq).spec_hash_after
            )
            before = await scope.assemble()
            h_before = canonical_hash(before)
            if h_before != rows[-1].spec_hash_after:
                raise _err("spec_changed", "the spec changed outside the op-log; refusing")
            for r in reversed([r for r in rows if r.seq > to_seq]):
                model = parse(r.inverse["op_type"], r.inverse["payload"])
                await dbapply.run(self.session, project_id, r.inverse["op_type"], model)
                await self.session.flush()
            after = await scope.assemble()
            if canonical_hash(after) != target_hash:
                raise _err(
                    "restore_mismatch", "the restored spec does not match the recorded state"
                )
            row = await scope.append(
                op_type="replace_spec",
                payload={"spec": dump(after)},
                inverse_type="replace_spec",
                inverse_payload={"spec": dump(before)},
                hash_before=h_before,
                hash_after=target_hash,
                origin="restore",
                ref_seq=to_seq,
                actor=actor,
            )
            scope.remember(after)
            return Applied(row, None)

        applied: Applied = await self._transaction(project_id, actor, body)
        return applied

    # -- read ----------------------------------------------------------------------------

    async def list_ops(
        self, project_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[SpecOpRead], int]:
        total = (
            await self.session.execute(
                select(func.count()).select_from(SpecOp).where(SpecOp.project_id == project_id)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(SpecOp, PlatformUser.email)
                .outerjoin(PlatformUser, PlatformUser.id == SpecOp.actor_id)
                .where(SpecOp.project_id == project_id)
                .order_by(SpecOp.seq.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [to_read(op, email) for op, email in rows], total


def to_read(op: SpecOp, email: str | None = None) -> SpecOpRead:
    return SpecOpRead(
        id=op.id,
        project_id=op.project_id,
        seq=op.seq,
        op_type=op.op_type,
        origin=op.origin,
        ref_seq=op.ref_seq,
        actor=SpecOpActor(kind=op.actor_kind, user_id=op.actor_id, email=email),
        payload=op.payload,
        inverse=SpecOpInverse(**op.inverse),
        spec_hash_before=op.spec_hash_before,
        spec_hash_after=op.spec_hash_after,
        created_at=op.created_at,
    )
