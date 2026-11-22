"""Suite identity, path (b), builder side: the join impact report and the migration state.

Spec level only: the builder never reads end-user identities. The migration lives inside the
project's auth config (`project_auth_configs.suite`), so it is written through AuthConfigService
and reaches the generated app through the spec."""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.spec_models import SpecSuiteMigration, SpecSuiteRef
from app.core.suite_migration import impact_report, migration_change_problem
from app.core.validation import validate
from app.exceptions import AppError
from app.schemas.auth_config import AuthConfigUpdate
from app.schemas.suite import SuiteJoinImpact, SuiteMigrationRead, SuiteMigrationWrite
from app.services.auth_config_service import AuthConfigService
from app.services.spec_service import SpecService
from app.services.workspace_files import WorkspaceFileService

_SCAN_SUFFIXES = (".py",)
_SCAN_ZONES = ("custom",)
_MAX_FILES = 200


class SuiteMigrationService:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def _load_sources(
        self, project_id: uuid.UUID, workspace_id: uuid.UUID | None
    ) -> dict[str, str] | None:
        """Hook / custom code of a workspace (the editable zone), or None when not asked for."""
        if workspace_id is None:
            return None
        files = WorkspaceFileService(self.session)
        entries = await files.list_files(project_id, workspace_id)
        sources: dict[str, str] = {}
        for entry in entries:
            if entry.zone in _SCAN_ZONES and entry.path.endswith(_SCAN_SUFFIXES):
                sources[entry.path] = (await files.read(project_id, workspace_id, entry.path)).content
                if len(sources) >= _MAX_FILES:
                    break
        return sources

    async def impact(
        self, project_id: uuid.UUID, workspace_id: uuid.UUID | None = None
    ) -> SuiteJoinImpact:
        spec = await SpecService(self.session).assemble(project_id)
        issues = [
            f"{i.path}: {i.message}"
            for i in validate(spec)
            if i.path.startswith("auth.suite") or i.path.startswith("auth.keycloak.realm")
        ]
        sources = await self._load_sources(project_id, workspace_id)
        return SuiteJoinImpact.model_validate(impact_report(spec, sources=sources, problems=issues))

    async def put_migration(
        self, project_id: uuid.UUID, body: SuiteMigrationWrite
    ) -> SuiteMigrationRead:
        service = AuthConfigService(self.session)
        config = await service.get(project_id)  # 404 when there is no auth config
        if not config.suite:
            raise AppError(
                "conflict", "set auth.suite (a suite id) before opening a migration", 409
            )
        suite = SpecSuiteRef.model_validate(config.suite)
        requested = SpecSuiteMigration(**body.model_dump())
        problem = migration_change_problem(suite.migration, requested, datetime.now(UTC))
        if problem is not None:
            raise AppError("invalid_transition", problem, 409)
        join_state = "joined" if requested.state in ("dual", "hub_only") else "planned"
        updated = suite.model_copy(update={"migration": requested, "join_state": join_state})
        # Validate the merged spec BEFORE writing: a refused move changes nothing.
        spec = await SpecService(self.session).assemble(project_id)
        if spec.auth is None:
            raise AppError("conflict", "the project has no auth configuration", 409)
        candidate = spec.model_copy(
            update={"auth": spec.auth.model_copy(update={"suite": updated})}
        )
        blocking = [i for i in validate(candidate) if i.path.startswith("auth.suite")]
        if blocking:
            raise AppError("validation_error", blocking[0].path + ": " + blocking[0].message, 422)
        await service.update(project_id, AuthConfigUpdate(suite=updated))
        return SuiteMigrationRead(
            suite_id=updated.suite_id,
            join_state=join_state,
            state=requested.state,
            legacy_issuer=requested.legacy_issuer,
            dual_until=requested.dual_until,
            window_started_at=requested.window_started_at,
        )
