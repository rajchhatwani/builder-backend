"""Declarative behaviour of a project (state machines, runtime settings, sequences, lists), stored
as sections of one `project_behavior` row."""

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
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
SECTIONS = (SECTION, SETTINGS, SEQUENCES, LISTS, HISTORY, HOOKS, SEED)


def sections_to_machines(sections: dict[str, Any]) -> list[SpecStateMachine]:
    return [SpecStateMachine.model_validate(m) for m in sections.get(SECTION, [])]


def apply_section(row: ProjectBehavior, key: str, items: list[Any]) -> None:
    # Assign a new dict: JSONB columns do not notice in-place changes.
    row.sections = {**row.sections, key: [m.model_dump(mode="json") for m in items]}


def apply_machines(row: ProjectBehavior, machines: list[SpecStateMachine]) -> None:
    apply_section(row, SECTION, machines)


class BehaviorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _row(self, project_id: uuid.UUID) -> ProjectBehavior | None:
        return (
            await self.session.execute(
                select(ProjectBehavior).where(ProjectBehavior.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def _project_row(self, project_id: uuid.UUID) -> ProjectBehavior | None:
        if await self.session.get(Project, project_id) is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return await self._row(project_id)

    async def _items(self, project_id: uuid.UUID, key: str, model: type[BaseModel]) -> list[Any]:
        row = await self._row(project_id)
        return [model.model_validate(m) for m in (row.sections.get(key, []) if row else [])]

    async def _save(
        self,
        project_id: uuid.UUID,
        key: str,
        what: str,
        expected_version: int | None,
        items: list[Any],
    ) -> None:
        row = await self._project_row(project_id)
        current = row.version if row is not None else 0
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
            row.version = current + 1
        apply_section(row, key, items)
        await self.session.commit()

    # --- state machines ---------------------------------------------------------------

    async def machines(self, project_id: uuid.UUID) -> list[SpecStateMachine]:
        row = await self._row(project_id)
        return sections_to_machines(row.sections) if row is not None else []

    async def get_state_machines(self, project_id: uuid.UUID) -> StateMachinesRead:
        row = await self._project_row(project_id)
        machines = sections_to_machines(row.sections) if row is not None else []
        return StateMachinesRead(
            project_id=project_id,
            version=row.version if row is not None else 0,
            updated_at=row.updated_at if row is not None else None,
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
        row = await self._project_row(project_id)
        return SettingsRead(
            project_id=project_id,
            version=row.version if row is not None else 0,
            updated_at=row.updated_at if row is not None else None,
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
        row = await self._project_row(project_id)
        return SequencesRead(
            project_id=project_id,
            version=row.version if row is not None else 0,
            updated_at=row.updated_at if row is not None else None,
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
        row = await self._project_row(project_id)
        return ListsRead(
            project_id=project_id,
            version=row.version if row is not None else 0,
            updated_at=row.updated_at if row is not None else None,
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
        row = await self._project_row(project_id)
        return HistoryRead(
            project_id=project_id,
            version=row.version if row is not None else 0,
            updated_at=row.updated_at if row is not None else None,
            history=[m.model_dump() for m in await self.history(project_id)],  # type: ignore[misc]
        )

    async def put_history(self, project_id: uuid.UUID, data: HistoryWrite) -> HistoryRead:
        items = [SpecHistory.model_validate(m.model_dump()) for m in data.history]
        await self._save(project_id, HISTORY, "change history settings", data.expected_version, items)
        return await self.get_history(project_id)

    # --- custom hooks -----------------------------------------------------------------

    async def hooks(self, project_id: uuid.UUID) -> list[SpecHook]:
        return await self._items(project_id, HOOKS, SpecHook)

    async def get_hooks(self, project_id: uuid.UUID) -> HooksRead:
        row = await self._project_row(project_id)
        return HooksRead(
            project_id=project_id,
            version=row.version if row is not None else 0,
            updated_at=row.updated_at if row is not None else None,
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
        row = await self._project_row(project_id)
        return SeedRead(
            project_id=project_id,
            version=row.version if row is not None else 0,
            updated_at=row.updated_at if row is not None else None,
            seed=[m.model_dump() for m in await self.seed(project_id)],  # type: ignore[misc]
        )

    async def put_seed(self, project_id: uuid.UUID, data: SeedWrite) -> SeedRead:
        items = [SpecSeedProfile.model_validate(m.model_dump()) for m in data.seed]
        await self._save(project_id, SEED, "seed profiles", data.expected_version, items)
        return await self.get_seed(project_id)
