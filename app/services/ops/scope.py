"""The recording scope of one database session.

While a scope is installed on a session, the session's `commit()` is the recording point, so a
spec write and its op-log row are one transaction and a failure to record fails the write:

* `legacy` mode (installed by the request guard for every mutating project request): the
  existing endpoints and services call `commit()` as before. Installing costs nothing: session
  events only note whether this transaction wrote a spec table (`dirty`). A commit of a clean
  transaction is a plain commit (read-only POSTs, generate, export never lock or record). A
  commit of a dirty one takes the project row lock at that moment, reads the committed spec
  (the "before": a cache hit when it equals the last op's hash, else assembled on a separate
  connection), assembles the transaction's own view from fresh database reads (the "after"; rows another
  writer committed before our lock replace stale copies in the session, and a write to data
  another writer changed meanwhile fails with 409 `spec_conflict`), and, when they differ,
  appends one op (a recognised typed op, else `replace_spec`) just before the real commit.
* `explicit` mode (the op service applying a typed op, undo, redo or restore): `commit()` only
  flushes; the op service locks first, records the row itself and then commits for real.

Writers to one project are serialised by the project row lock (`FOR NO KEY UPDATE`, which does
not conflict with the `KEY SHARE` lock a child-row insert takes, so two writers cannot
deadlock on it) for as long as the lock is needed: from the first lock request to the commit.
`seq` is allocated under that lock, so it is dense and monotonic.
"""

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import event, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import ORMExecuteState

from app.core.spec_models import Spec
from app.exceptions import AppError
from app.models.auth_config import ProjectAuthConfig
from app.models.auth_custom_field import AuthCustomField
from app.models.authorization_config import ProjectAuthorization
from app.models.behavior_config import ProjectBehavior
from app.models.deployment_config import ProjectDeployment
from app.models.documents_config import ProjectDocuments
from app.models.entity import Entity
from app.models.field import Field
from app.models.keycloak_config import ProjectKeycloakConfig
from app.models.observability_config import ProjectObservability
from app.models.payments_config import ProjectPaymentsConfig
from app.models.project import Project
from app.models.project_permission import ProjectPermission
from app.models.project_role import ProjectRole
from app.models.relation import Relation
from app.models.spec_op import SpecOp
from app.models.storage_config import ProjectStorageConfig
from app.services.ops.canon import canonical_hash
from app.services.ops.registry import recognise

# Every model SpecService.assemble reads. A write to one of these may change the spec.
SPEC_MODELS: tuple[type, ...] = (
    Project,
    Entity,
    Field,
    Relation,
    ProjectBehavior,
    ProjectAuthConfig,
    ProjectRole,
    ProjectPermission,
    AuthCustomField,
    ProjectKeycloakConfig,
    ProjectPaymentsConfig,
    ProjectStorageConfig,
    ProjectAuthorization,
    ProjectObservability,
    ProjectDeployment,
    ProjectDocuments,
)

# The spec each project had after its last recorded op, keyed by that op's hash. A commit uses
# it as the "before" only when the hash equals the log's latest `spec_hash_after`, so a change
# made by anything else (another process) misses the cache and is read from the database.
_LAST_SPEC: "OrderedDict[uuid.UUID, tuple[str, Spec]]" = OrderedDict()
_LAST_SPEC_MAX = 64


def _cache_put(project_id: uuid.UUID, spec_hash: str, spec: Spec) -> None:
    _LAST_SPEC[project_id] = (spec_hash, spec)
    _LAST_SPEC.move_to_end(project_id)
    while len(_LAST_SPEC) > _LAST_SPEC_MAX:
        _LAST_SPEC.popitem(last=False)


def forget(project_id: uuid.UUID) -> None:
    _LAST_SPEC.pop(project_id, None)


SESSION_KEY = "ops_scope"


@dataclass(frozen=True)
class Actor:
    kind: Literal["user", "mcp", "system"]
    user_id: uuid.UUID | None = None


SYSTEM = Actor("system")


class OpScope:
    def __init__(self, session: AsyncSession, project_id: uuid.UUID, actor: Actor) -> None:
        self.session = session
        self.project_id = project_id
        self.actor = actor
        self.mode: Literal["legacy", "explicit"] = "legacy"
        self.dirty = False  # this transaction has written a spec table (or something unknown)
        self.real_commit: Any = session.commit
        self._locked = False
        self._remembered: tuple[str, Spec] | None = None
        # (model, pk) -> {attribute: value this transaction read before changing it}; used to
        # tell, after the lock, whether another writer changed the same data meanwhile.
        self._preimages: dict[tuple[type, Any], dict[str, Any]] = {}
        session.commit = self._commit  # type: ignore[method-assign]
        session.info[SESSION_KEY] = self
        sync = session.sync_session
        self._listeners = (
            ("before_flush", self._on_flush),
            ("do_orm_execute", self._on_execute),
            ("after_commit", self._on_end),
            ("after_soft_rollback", self._on_rollback),
        )
        for name, fn in self._listeners:
            event.listen(sync, name, fn)

    # -- session events: cheap, no queries ---------------------------------------------

    def _note_preimages(self, session: Any) -> None:
        for obj in (*session.dirty, *session.deleted):
            if not isinstance(obj, SPEC_MODELS):
                continue
            state: Any = inspect(obj)
            if state.key is None:
                continue
            seen = self._preimages.setdefault((type(obj), state.key[1]), {})
            deleted = obj in session.deleted
            for attr in state.mapper.column_attrs:
                hist = state.attrs[attr.key].history
                if hist.deleted:
                    seen.setdefault(attr.key, hist.deleted[0])
                elif deleted and attr.key in state.dict:
                    seen.setdefault(attr.key, state.dict[attr.key])

    def _on_flush(self, session: Any, _ctx: Any, _instances: Any) -> None:
        self._note_preimages(session)
        for group in (session.new, session.dirty, session.deleted):
            if any(isinstance(o, SPEC_MODELS) for o in group):
                self.dirty = True
                return

    def _on_execute(self, state: ORMExecuteState) -> None:
        if not (state.is_insert or state.is_update or state.is_delete):
            return
        mapper = state.bind_arguments.get("mapper") if state.bind_arguments else None
        # A bulk write we cannot attribute to a table counts as a spec write (fail closed).
        if mapper is None or issubclass(mapper.class_, SPEC_MODELS):
            self.dirty = True

    def _on_end(self, _session: Any) -> None:
        self.dirty = False
        self._preimages = {}
        self._locked = False

    def _on_rollback(self, _session: Any, previous: Any) -> None:
        if previous.nested:
            return  # a savepoint: the outer transaction (and what it wrote) goes on
        self.dirty = False
        self._locked = False
        self._remembered = None
        self._preimages = {}

    def close(self) -> None:
        sync = self.session.sync_session
        for name, fn in self._listeners:
            if event.contains(sync, name, fn):
                event.remove(sync, name, fn)
        self.session.__dict__.pop("commit", None)
        self.session.info.pop(SESSION_KEY, None)

    # -- locking and reading -------------------------------------------------------------

    async def lock(self) -> None:
        if not await self._try_lock():
            raise AppError(code="not_found", message="project not found", status_code=404)

    async def _try_lock(self) -> bool:
        found = (
            await self.session.execute(
                select(Project.id)
                .where(Project.id == self.project_id)
                .with_for_update(key_share=True)  # FOR NO KEY UPDATE
            )
        ).scalar_one_or_none()
        self._locked = found is not None
        return found is not None

    async def assemble(self) -> Spec:
        from app.services.spec_service import SpecService

        return await SpecService(self.session).assemble(self.project_id)

    async def _assemble_committed(self) -> Spec:
        """The spec as committed, ignoring this transaction's own writes: read on another
        connection. Called with the lock held, so no recorded writer commits meanwhile."""
        from app.services.spec_service import SpecService

        bind = self.session.bind
        if isinstance(bind, AsyncEngine):
            engine = bind
        elif bind is not None and hasattr(bind, "engine"):
            engine = bind.engine
        else:
            raise AppError(code="internal", message="cannot record the spec change", status_code=500)
        async with AsyncSession(engine, expire_on_commit=False) as other:
            return await SpecService(other).assemble(self.project_id)

    async def _assemble_fresh(self) -> Spec:
        """This transaction's view of the spec read from the database, not from the session's
        identity map: rows another writer committed before our lock replace the copies this
        session loaded earlier, and our own flushed writes are part of it."""
        await self.session.execute(
            select(Project)
            .where(Project.id == self.project_id)
            .execution_options(populate_existing=True)
        )
        sync = self.session.sync_session

        def refresh(state: ORMExecuteState) -> None:
            if state.is_select:
                state.update_execution_options(populate_existing=True)

        event.listen(sync, "do_orm_execute", refresh)
        try:
            return await self.assemble()
        finally:
            event.remove(sync, "do_orm_execute", refresh)

    async def _check_no_lost_update(self) -> None:
        """Fail closed when another writer committed a change to data this transaction also
        changed (its pre-image no longer matches the committed row): the flushed write would
        silently overwrite it."""
        if not self._preimages:
            return
        bind = self.session.bind
        engine = bind if isinstance(bind, AsyncEngine) else getattr(bind, "engine", None)
        if engine is None:
            raise AppError(code="internal", message="cannot record the spec change", status_code=500)
        conflict = False
        async with AsyncSession(engine, expire_on_commit=False) as other:
            for (cls, pk), old in self._preimages.items():
                committed: Any = await other.get(cls, pk)
                if committed is None:
                    continue  # removed by someone else: our write would have failed to match
                if any(getattr(committed, k) != v for k, v in old.items()):
                    conflict = True
                    break
        if conflict:
            await self.session.rollback()
            raise AppError(
                code="spec_conflict",
                message="the spec was changed by someone else while this request was running; "
                "reload and try again",
                status_code=409,
            )

    async def _last_hash(self) -> str | None:
        return (
            await self.session.execute(
                select(SpecOp.spec_hash_after)
                .where(SpecOp.project_id == self.project_id)
                .order_by(SpecOp.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _committed_before(self) -> Spec:
        last = await self._last_hash()
        cached = _LAST_SPEC.get(self.project_id)
        if last is not None and cached is not None and cached[0] == last:
            return cached[1]
        return await self._assemble_committed()

    def remember(self, spec: Spec) -> None:
        """Offer the spec this transaction produced; `publish` caches it after the commit."""
        self._remembered = (canonical_hash(spec), spec)

    def publish(self) -> None:
        """Called right after a real commit that recorded an op."""
        if self._remembered is not None:
            _cache_put(self.project_id, *self._remembered)
        self._remembered = None

    async def append(
        self,
        *,
        op_type: str,
        payload: dict[str, Any],
        inverse_type: str,
        inverse_payload: dict[str, Any],
        hash_before: str,
        hash_after: str,
        origin: str = "do",
        ref_seq: int | None = None,
        actor: Actor | None = None,
    ) -> SpecOp:
        who = actor or self.actor
        seq = (
            await self.session.execute(
                select(func.coalesce(func.max(SpecOp.seq), 0)).where(
                    SpecOp.project_id == self.project_id
                )
            )
        ).scalar_one() + 1
        row = SpecOp(
            project_id=self.project_id,
            seq=seq,
            actor_kind=who.kind,
            actor_id=who.user_id,
            op_type=op_type,
            origin=origin,
            ref_seq=ref_seq,
            payload=payload,
            inverse={"op_type": inverse_type, "payload": inverse_payload},
            spec_hash_before=hash_before,
            spec_hash_after=hash_after,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _record_legacy(self) -> None:
        await self.session.flush()
        if not self.dirty:
            return
        if not await self._try_lock():
            return  # the project itself was removed: its log goes with it
        await self._check_no_lost_update()
        before = await self._committed_before()
        after = await self._assemble_fresh()
        h_before, h_after = canonical_hash(before), canonical_hash(after)
        if h_before == h_after:
            return
        planned = recognise(before, after)
        await self.append(
            op_type=planned.op_type,
            payload=planned.payload.model_dump(mode="json"),
            inverse_type=planned.inverse_type,
            inverse_payload=planned.inverse_payload,
            hash_before=h_before,
            hash_after=h_after,
        )
        self._remembered = (h_after, after)

    async def _commit(self) -> None:
        if self.mode == "explicit":
            await self.session.flush()
            return
        self._remembered = None
        await self._record_legacy()
        await self.real_commit()
        self.publish()


def scope_of(session: AsyncSession) -> OpScope | None:
    found = session.info.get(SESSION_KEY)
    return found if isinstance(found, OpScope) else None


async def install(session: AsyncSession, project_id: uuid.UUID, actor: Actor) -> OpScope:
    """Start recording for this session (the guard calls it for mutating project requests)."""
    existing = scope_of(session)
    if existing is not None:
        existing.close()
    return OpScope(session, project_id, actor)
