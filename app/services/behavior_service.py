"""Declarative behaviour of a project (state machines, runtime settings, sequences, lists), stored
as sections of one `project_behavior` row.

Concurrency contract: every section has its OWN version, kept in the row's JSON under the reserved
key `_versions` (no migration). A save checks and bumps only the version of the section it writes,
so a stale write to one section never conflicts with a change to another. The row is locked
(`SELECT ... FOR UPDATE`) while a section is saved, so two saves to different sections cannot lose
each other's data. `row_version` (the old whole-row counter) is still bumped on every save and
returned for compatibility, but it is no longer what `expected_version` is compared with."""

import uuid
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.spec_models import (
    SpecHistory,
    SpecHook,
    SpecList,
    SpecSeedProfile,
    SpecSequence,
    SpecSetting,
    SpecStateMachine,
)
from app.exceptions import AppError
from app.models.behavior_config import ProjectBehavior
from app.models.project import Project
from app.schemas.behavior import (
    HistoryRead,
    HistoryWrite,
    HooksRead,
    HooksWrite,
    ListsRead,
    ListsWrite,
    RoleOption,
    RolesRead,
    SeedRead,
    SeedWrite,
    SequencesRead,
    SequencesWrite,
    SettingsRead,
    SettingsWrite,
    StateMachinesRead,
    StateMachinesWrite,
)

SECTION = "state_machines"
SETTINGS = "settings"
SEQUENCES = "sequences"
LISTS = "lists"
HISTORY = "history"
HOOKS = "hooks"
SEED = "seed"
# Every section a path in `/behavior/issues` may belong to.
# Single-object blocks (B2-11), stored in the same row and versioned the same way as the lists
# above; an absent block is stored as null. Order is the order of the Spec fields.
BLOCKS = (
    "events",
    "providers",
    "notifications",
    "jobs",
    "workflows",
    "api_edge",
    "webhooks",
    "hook_effects",
)
SECTIONS = (SECTION, SETTINGS, SEQUENCES, LISTS, HISTORY, HOOKS, SEED, *BLOCKS)
# Issue codes a block save is refused for: a secret must never be written to the spec.
SECRET_CODES = frozenset({"secret_in_spec", "secret_name"})
# Reserved (non-section) keys in the row's JSON.
VERSIONS_KEY = "_versions"
DISMISSED_KEY = "_dismissed_steps"


def sections_to_machines(sections: dict[str, Any]) -> list[SpecStateMachine]:
    return [SpecStateMachine.model_validate(m) for m in sections.get(SECTION, [])]


def section_version(row: ProjectBehavior | None, key: str) -> int:
    """Version of one section; 0 = never saved (also for sections of rows written before
    per-section versions existed)."""
    if row is None:
        return 0
    raw = (row.sections.get(VERSIONS_KEY) or {}).get(key, 0)
    return raw if isinstance(raw, int) and raw >= 0 else 0


# Project role of whoever is making this request (set by the request guard / MCP); None outside a
# request (CLI, tests), where nothing is restricted.
ACTOR_ROLE: ContextVar[str | None] = ContextVar("actor_role", default=None)


def _effects_of(raw: Any) -> list[tuple[str, tuple[str, ...]]]:
    return sorted(
        (h.get("name", ""), tuple(h["effects"]))
        for h in (raw or [])
        if isinstance(h, dict) and h.get("effects")
    )


def _guard_effects(row: ProjectBehavior, key: str, new: Any) -> None:
    """CO-3: switching effectful hooks on, or changing a hook's `effects`, is owner-only, on every
    path (PUT /spec, typed ops, undo/redo/restore, MCP, the section routes)."""
    role = ACTOR_ROLE.get()
    if role is None or role == "owner" or key not in ("hooks", "hook_effects"):
        return
    old = row.sections.get(key)
    if key == "hook_effects":
        changed = old != new
    else:
        changed = _effects_of(old) != _effects_of(new)
    if changed:
        raise AppError(
            code="forbidden",
            message="only a project owner may change effectful hooks (hook_effects, hook effects)",
            status_code=403,
        )


def apply_section(row: ProjectBehavior, key: str, items: list[Any] | BaseModel | None) -> None:
    """Replace one section and bump that section's version (and only that one). A list section
    takes a list; a block (see BLOCKS) takes its model, or None to remove it."""
    # Assign a new dict: JSONB columns do not notice in-place changes.
    versions = {**(row.sections.get(VERSIONS_KEY) or {}), key: section_version(row, key) + 1}
    new = (
        [m.model_dump(mode="json") for m in items]
        if isinstance(items, list)
        else (items.model_dump(mode="json") if items is not None else None)
    )
    _guard_effects(row, key, new)
    row.sections = {
        **row.sections,
        key: new,
        VERSIONS_KEY: versions,
    }


def apply_machines(row: ProjectBehavior, machines: list[SpecStateMachine]) -> None:
    apply_section(row, SECTION, machines)


class BehaviorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _row(self, project_id: uuid.UUID, lock: bool = False) -> ProjectBehavior | None:
        query = select(ProjectBehavior).where(ProjectBehavior.project_id == project_id)
        if lock:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def _project_row(
        self, project_id: uuid.UUID, lock: bool = False
    ) -> ProjectBehavior | None:
        if await self.session.get(Project, project_id) is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return await self._row(project_id, lock)

    async def _meta(self, project_id: uuid.UUID, key: str) -> dict[str, Any]:
        """`project_id`, `version` (of section `key`), `updated_at`, `row_version` for a Read."""
        row = await self._project_row(project_id)
        return {
            "project_id": project_id,
            "version": section_version(row, key),
            "updated_at": row.updated_at if row is not None else None,
            "row_version": row.version if row is not None else 0,
        }

    async def _items(self, project_id: uuid.UUID, key: str, model: type[BaseModel]) -> list[Any]:
        row = await self._row(project_id)
        return [model.model_validate(m) for m in (row.sections.get(key, []) if row else [])]

    async def _save(
        self,
        project_id: uuid.UUID,
        key: str,
        what: str,
        expected_version: int | None,
        items: list[Any] | BaseModel | None,
    ) -> None:
        row = await self._project_row(project_id, lock=True)
        current = section_version(row, key)
        if expected_version is not None and expected_version != current:
            raise AppError(
                code="conflict",
                message=f"the {what} changed since you opened them; reload and apply "
                "your edit again",
                status_code=409,
            )
        if row is None:
            row = ProjectBehavior(project_id=project_id, version=1, sections={})
            self.session.add(row)
        else:
            row.version += 1
        apply_section(row, key, items)
        try:
            await self.session.commit()
        except IntegrityError as exc:  # two first saves raced: only one row per project
            await self.session.rollback()
            raise AppError(
                code="conflict",
                message=f"the {what} changed since you opened them; reload and apply "
                "your edit again",
                status_code=409,
            ) from exc

    # --- state machines ---------------------------------------------------------------

    async def machines(self, project_id: uuid.UUID) -> list[SpecStateMachine]:
        row = await self._row(project_id)
        return sections_to_machines(row.sections) if row is not None else []

    async def get_state_machines(self, project_id: uuid.UUID) -> StateMachinesRead:
        row = await self._project_row(project_id)
        machines = sections_to_machines(row.sections) if row is not None else []
        return StateMachinesRead(
            **await self._meta(project_id, SECTION),
            state_machines=[m.model_dump() for m in machines],  # type: ignore[misc]
        )

    async def put_state_machines(
        self, project_id: uuid.UUID, data: StateMachinesWrite
    ) -> StateMachinesRead:
        machines = [SpecStateMachine.model_validate(m.model_dump()) for m in data.state_machines]
        await self._save(project_id, SECTION, "state machines", data.expected_version, machines)
        return await self.get_state_machines(project_id)

    # --- runtime settings -------------------------------------------------------------

    async def settings(self, project_id: uuid.UUID) -> list[SpecSetting]:
        return await self._items(project_id, SETTINGS, SpecSetting)

    async def get_settings(self, project_id: uuid.UUID) -> SettingsRead:
        return SettingsRead(
            **await self._meta(project_id, SETTINGS),
            settings=[m.model_dump() for m in await self.settings(project_id)],  # type: ignore[misc]
        )

    async def put_settings(self, project_id: uuid.UUID, data: SettingsWrite) -> SettingsRead:
        items = [SpecSetting.model_validate(m.model_dump()) for m in data.settings]
        await self._save(project_id, SETTINGS, "settings", data.expected_version, items)
        return await self.get_settings(project_id)

    # --- sequences --------------------------------------------------------------------

    async def sequences(self, project_id: uuid.UUID) -> list[SpecSequence]:
        return await self._items(project_id, SEQUENCES, SpecSequence)

    async def get_sequences(self, project_id: uuid.UUID) -> SequencesRead:
        return SequencesRead(
            **await self._meta(project_id, SEQUENCES),
            sequences=[m.model_dump() for m in await self.sequences(project_id)],  # type: ignore[misc]
        )

    async def put_sequences(self, project_id: uuid.UUID, data: SequencesWrite) -> SequencesRead:
        items = [SpecSequence.model_validate(m.model_dump()) for m in data.sequences]
        await self._save(project_id, SEQUENCES, "sequences", data.expected_version, items)
        return await self.get_sequences(project_id)

    # --- lists ------------------------------------------------------------------------

    async def lists(self, project_id: uuid.UUID) -> list[SpecList]:
        return await self._items(project_id, LISTS, SpecList)

    async def get_lists(self, project_id: uuid.UUID) -> ListsRead:
        return ListsRead(
            **await self._meta(project_id, LISTS),
            lists=[m.model_dump() for m in await self.lists(project_id)],  # type: ignore[misc]
        )

    async def put_lists(self, project_id: uuid.UUID, data: ListsWrite) -> ListsRead:
        items = [SpecList.model_validate(m.model_dump()) for m in data.lists]
        await self._save(project_id, LISTS, "lists", data.expected_version, items)
        return await self.get_lists(project_id)

    # --- change history ---------------------------------------------------------------

    async def history(self, project_id: uuid.UUID) -> list[SpecHistory]:
        return await self._items(project_id, HISTORY, SpecHistory)

    async def get_history(self, project_id: uuid.UUID) -> HistoryRead:
        return HistoryRead(
            **await self._meta(project_id, HISTORY),
            history=[m.model_dump() for m in await self.history(project_id)],  # type: ignore[misc]
        )

    async def put_history(self, project_id: uuid.UUID, data: HistoryWrite) -> HistoryRead:
        items = [SpecHistory.model_validate(m.model_dump()) for m in data.history]
        await self._save(
            project_id, HISTORY, "change history settings", data.expected_version, items
        )
        return await self.get_history(project_id)

    # --- custom hooks -----------------------------------------------------------------

    async def hooks(self, project_id: uuid.UUID) -> list[SpecHook]:
        return await self._items(project_id, HOOKS, SpecHook)

    async def get_hooks(self, project_id: uuid.UUID) -> HooksRead:
        return HooksRead(
            **await self._meta(project_id, HOOKS),
            hooks=[m.model_dump() for m in await self.hooks(project_id)],  # type: ignore[misc]
        )

    async def put_hooks(self, project_id: uuid.UUID, data: HooksWrite) -> HooksRead:
        items = [SpecHook.model_validate(m.model_dump()) for m in data.hooks]
        await self._save(project_id, HOOKS, "hooks", data.expected_version, items)
        return await self.get_hooks(project_id)

    # --- seed profiles ----------------------------------------------------------------

    async def seed(self, project_id: uuid.UUID) -> list[SpecSeedProfile]:
        return await self._items(project_id, SEED, SpecSeedProfile)

    async def get_seed(self, project_id: uuid.UUID) -> SeedRead:
        return SeedRead(
            **await self._meta(project_id, SEED),
            seed=[m.model_dump() for m in await self.seed(project_id)],  # type: ignore[misc]
        )

    async def put_seed(self, project_id: uuid.UUID, data: SeedWrite) -> SeedRead:
        items = [SpecSeedProfile.model_validate(m.model_dump()) for m in data.seed]
        await self._save(project_id, SEED, "seed profiles", data.expected_version, items)
        return await self.get_seed(project_id)

    # --- single-object blocks (events, providers, notifications, jobs, ...) -------------

    async def block(self, project_id: uuid.UUID, key: str) -> Any:
        row = await self._row(project_id)
        raw = row.sections.get(key) if row is not None else None
        return _BLOCK_MODELS[key].model_validate(raw) if raw is not None else None

    async def get_block(self, project_id: uuid.UUID, key: str) -> dict[str, Any]:
        value = await self.block(project_id, key)
        return {**await self._meta(project_id, key), key: value}

    async def put_block(
        self, project_id: uuid.UUID, key: str, value: Any, expected_version: int | None
    ) -> dict[str, Any]:
        """Save one block. Work in progress is accepted (problems are read from /behavior/issues),
        except a secret, which is refused so it is never stored."""
        from app.core.validation import validate
        from app.services.spec_service import SpecService  # spec_service imports this module

        spec = await SpecService(self.session).assemble(project_id)  # 404 for an unknown project
        setattr(spec, key, value)
        leaked = [
            i
            for i in validate(spec)
            if i.code in SECRET_CODES and (i.path == key or i.path.startswith((key + ".", key + "[")))
        ]
        if leaked:
            raise AppError(
                code="secret_in_spec",
                message="a secret cannot be stored in the spec; keep it in the provider vault",
                status_code=422,
                details=[i.model_dump() for i in leaked],
            )
        await self._save(project_id, key, key.replace("_", " "), expected_version, value)
        return await self.get_block(project_id, key)

    # --- roles for the dashboard pickers ---------------------------------------------

    async def get_roles(self, project_id: uuid.UUID) -> RolesRead:
        """The role names the project's auth config declares (name and label only). Read from the
        same assembled spec as GET /spec, so it needs the same permission and shows nothing more."""
        from app.services.spec_service import SpecService  # spec_service imports this module

        spec = await SpecService(self.session).assemble(project_id)  # 404 for an unknown project
        roles = spec.auth.roles if spec.auth is not None else []
        return RolesRead(
            project_id=project_id, roles=[RoleOption(name=r.name, label=r.label) for r in roles]
        )

    # --- status: dismissed next steps ---------------------------------------------------

    async def dismissed_steps(self, project_id: uuid.UUID) -> list[str]:
        row = await self._row(project_id)
        return _dismissed(row)

    async def set_dismissed(self, project_id: uuid.UUID, step: str, dismissed: bool) -> list[str]:
        """Add or remove `step` in the project's dismissed list (idempotent). The caller has
        already checked `step` is dismissable. Does not touch any section or section version."""
        row = await self._project_row(project_id, lock=True)  # 404 for an unknown project
        current = _dismissed(row)
        wanted = sorted({*current, step} if dismissed else set(current) - {step})
        if wanted == current:
            return current
        if row is None:
            row = ProjectBehavior(project_id=project_id, version=1, sections={})
            self.session.add(row)
        row.sections = {**row.sections, DISMISSED_KEY: wanted}
        await self.session.commit()
        return wanted


def _block_models() -> dict[str, type[BaseModel]]:
    from app.core import spec_models

    return {
        "events": spec_models.SpecEvents,
        "providers": spec_models.SpecProviders,
        "notifications": spec_models.SpecNotifications,
        "jobs": spec_models.SpecJobs,
        "workflows": spec_models.SpecWorkflows,
        "api_edge": spec_models.SpecApiEdge,
        "webhooks": spec_models.SpecWebhooks,
        "hook_effects": spec_models.SpecHookEffects,
    }


_BLOCK_MODELS = _block_models()


def _dismissed(row: ProjectBehavior | None) -> list[str]:
    raw = row.sections.get(DISMISSED_KEY) if row is not None else None
    return sorted({x for x in raw if isinstance(x, str)}) if isinstance(raw, list) else []
