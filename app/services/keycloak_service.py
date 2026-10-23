"""Keycloak settings of a project, and the guarded switch between built-in auth and Keycloak.

Switching the provider is the one dangerous operation here: users live in Keycloak and cannot
be moved into the built-in auth (their passwords are not exportable), and other builder
projects may trust this project's Keycloak realm. So switching needs an explicit confirmation,
reports its impact first, and is refused while dependents exist. The settings row is never
deleted by a switch, so enabling again restores everything.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AuthProvider, KeycloakMode
from app.exceptions import AppError
from app.models.auth_config import ProjectAuthConfig
from app.models.keycloak_config import ProjectKeycloakConfig
from app.models.project import Project
from app.schemas.keycloak import Dependent, KeycloakConfigWrite, KeycloakImpact

_DEPLOYED_NOTE = (
    "Anything already deployed keeps working until you regenerate. A regenerated build refuses "
    "to start on a database used by the other provider unless AUTH_ALLOW_PROVIDER_SWITCH=true "
    "is set."
)


def _not_found(what: str) -> AppError:
    return AppError(code="not_found", message=f"{what} not found", status_code=404)


def _conflict(code: str, message: str) -> AppError:
    return AppError(code=code, message=message, status_code=409)


def _invalid(message: str) -> AppError:
    return AppError(code="validation_error", message=message, status_code=422)


class KeycloakService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- lookups --------------------------------------------------------------------

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise _not_found("project")
        return project

    async def _auth(self, project_id: uuid.UUID) -> ProjectAuthConfig | None:
        return (
            await self.session.execute(
                select(ProjectAuthConfig).where(ProjectAuthConfig.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def _config(self, project_id: uuid.UUID) -> ProjectKeycloakConfig | None:
        return (
            await self.session.execute(
                select(ProjectKeycloakConfig).where(ProjectKeycloakConfig.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def is_active(self, project_id: uuid.UUID) -> bool:
        auth = await self._auth(project_id)
        return auth is not None and auth.provider == AuthProvider.keycloak

    async def dependents(self, project_id: uuid.UUID) -> list[Dependent]:
        """Projects that currently use Keycloak and trust this project's realm."""
        rows = (
            await self.session.execute(
                select(Project)
                .join(ProjectKeycloakConfig, ProjectKeycloakConfig.project_id == Project.id)
                .join(ProjectAuthConfig, ProjectAuthConfig.project_id == Project.id)
                .where(
                    ProjectKeycloakConfig.source_project_id == project_id,
                    ProjectKeycloakConfig.mode == KeycloakMode.shared,
                    ProjectAuthConfig.provider == AuthProvider.keycloak,
                )
                .order_by(Project.name)
            )
        ).scalars()
        return [Dependent(id=p.id, name=p.name) for p in rows]

    # --- settings -------------------------------------------------------------------

    async def get(self, project_id: uuid.UUID) -> ProjectKeycloakConfig:
        await self._project(project_id)
        config = await self._config(project_id)
        if config is None:
            raise _not_found("keycloak settings")
        return config

    async def put(self, project_id: uuid.UUID, data: KeycloakConfigWrite) -> ProjectKeycloakConfig:
        project = await self._project(project_id)
        slug = project.slug.replace("_", "-")
        config = await self._config(project_id)

        source = await self._check_source(project_id, data)
        realm = data.realm or (source.realm if source is not None else slug)

        # Other projects point at this realm; changing what it is would break them.
        redefines_realm = (
            config is not None
            and config.mode == KeycloakMode.own
            and (data.mode != KeycloakMode.own or realm != config.realm)
        )
        if redefines_realm:
            dependents = await self.dependents(project_id)
            if dependents:
                names = ", ".join(d.name for d in dependents)
                raise _conflict(
                    "has_dependents",
                    f"these projects use this Keycloak realm, so its realm and mode cannot "
                    f"change: {names}",
                )

        if config is None:
            config = ProjectKeycloakConfig(project_id=project_id)
            self.session.add(config)
        config.mode = data.mode
        config.realm = realm
        config.api_client_id = data.api_client_id or f"{slug}-api"
        config.web_client_id = data.web_client_id or f"{slug}-web"
        config.redirect_uris = list(data.redirect_uris)
        config.password_min_length = data.password_min_length
        config.mfa = data.mfa
        config.session_idle_minutes = data.session_idle_minutes
        config.session_max_hours = data.session_max_hours
        config.audit_retention_days = data.audit_retention_days
        config.identity_providers = [p.model_dump(mode="json") for p in data.identity_providers]
        config.source_project_id = source.project_id if source is not None else None
        await self.session.commit()
        return config

    async def _check_source(
        self, project_id: uuid.UUID, data: KeycloakConfigWrite
    ) -> ProjectKeycloakConfig | None:
        if data.source_project_id is None:
            return None
        if data.mode != KeycloakMode.shared:
            raise _invalid("source_project_id is only for shared mode")
        if data.source_project_id == project_id:
            raise _invalid("a project cannot trust its own Keycloak as a shared one")
        source = await self._config(data.source_project_id)
        if source is None or source.mode != KeycloakMode.own:
            raise _invalid("source_project_id must be a project that runs its own Keycloak")
        return source

    # --- switching ------------------------------------------------------------------

    async def impact(self, project_id: uuid.UUID, action: str) -> KeycloakImpact:
        await self._project(project_id)
        auth = await self._auth(project_id)
        provider = auth.provider if auth is not None else AuthProvider.builtin
        config = await self._config(project_id)
        blockers: list[str] = []
        warnings: list[str] = []
        dependents: list[Dependent] = []

        if action == "enable":
            if provider == AuthProvider.keycloak:
                blockers.append("Keycloak is already on for this project.")
            if config is None:
                blockers.append("Save the Keycloak settings first.")
            warnings.append(
                "Users are managed in Keycloak. Accounts created with built-in sign-in are not "
                "moved over; people sign up or sign in again through Keycloak."
            )
        elif action == "disable":
            if provider != AuthProvider.keycloak:
                blockers.append("Keycloak is not on for this project.")
            if config is not None and config.mode == KeycloakMode.own:
                dependents = await self.dependents(project_id)
                if dependents:
                    blockers.append(
                        "Other projects sign in through this project's Keycloak: "
                        + ", ".join(d.name for d in dependents)
                        + ". Switch them to another provider first."
                    )
            warnings.append(
                "Users and passwords live in Keycloak and cannot be moved into built-in sign-in. "
                "People will need to register again after you regenerate."
            )
            warnings.append(
                "Your Keycloak settings are kept, so you can turn it back on later. What your "
                "backend stored about users (their ids and the data they own) is kept too."
            )
        else:
            raise _invalid("action must be enable or disable")
        warnings.append(_DEPLOYED_NOTE)

        return KeycloakImpact(
            action=action,
            provider=provider,
            can_proceed=not blockers,
            blockers=blockers,
            warnings=warnings,
            dependents=dependents,
        )

    async def switch(
        self, project_id: uuid.UUID, action: str, *, confirm: bool
    ) -> ProjectKeycloakConfig:
        if not confirm:
            raise AppError(
                code="confirmation_required",
                message="switching the identity provider needs confirm=true; read "
                "/keycloak/impact first to see what it changes",
                status_code=422,
            )
        impact = await self.impact(project_id, action)
        if not impact.can_proceed:
            code = "has_dependents" if impact.dependents else "invalid_state"
            raise _conflict(code, " ".join(impact.blockers))

        auth = await self._auth(project_id)
        if auth is None:
            # Keycloak needs an auth block to hang the provider on. Email verification starts
            # off so a new project is valid before SMTP is set up; the dashboard says so.
            auth = ProjectAuthConfig(
                project_id=project_id,
                enabled=True,
                email_magic_link_enabled=False,
                email_verification_required=False,
            )
            self.session.add(auth)
        auth.provider = AuthProvider.keycloak if action == "enable" else AuthProvider.builtin
        if action == "enable":
            auth.enabled = True
        await self.session.commit()
        return await self.get(project_id)
