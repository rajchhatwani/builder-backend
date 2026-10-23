"""Payments settings of a project, and the guarded switch that turns the feature on or off.

Turning payments off does not drop anything: the settings row is kept, and tables a generated
project already created are never removed by regenerating (history must survive for audits). The
switch needs an explicit confirmation and reports its impact first.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PaymentProvider
from app.core.payments_sizing import PaymentsSizing, size
from app.core.spec_models import (
    SpecPayments,
    SpecPaymentsPayable,
    SpecPaymentsRoles,
    SpecPaymentsScale,
    SpecPaymentsSecurity,
)
from app.exceptions import AppError
from app.models.auth_config import ProjectAuthConfig
from app.models.payments_config import ProjectPaymentsConfig
from app.models.project import Project
from app.schemas.payments import PaymentsConfigWrite, PaymentsImpact

_DEPLOYED_NOTE = (
    "Anything already deployed keeps working until you regenerate. Payment, refund, dispute and "
    "audit tables are never dropped by a regenerated build, so history stays available."
)


def _not_found(what: str) -> AppError:
    return AppError(code="not_found", message=f"{what} not found", status_code=404)


def _invalid(message: str) -> AppError:
    return AppError(code="validation_error", message=message, status_code=422)


def config_to_spec(row: ProjectPaymentsConfig) -> SpecPayments:
    return SpecPayments(
        enabled=row.enabled,
        provider=row.provider.value,
        payable=SpecPaymentsPayable.model_validate(row.payable) if row.payable else None,
        currencies=list(row.currencies),
        max_amount_minor=row.max_amount_minor,
        success_urls=list(row.success_urls),
        cancel_urls=list(row.cancel_urls),
        roles=SpecPaymentsRoles.model_validate(row.roles),
        refund_approval_threshold_minor=row.refund_approval_threshold_minor,
        scale=SpecPaymentsScale.model_validate(row.scale),
        security=SpecPaymentsSecurity.model_validate(row.security),
    )


def apply_spec(row: ProjectPaymentsConfig, spec: SpecPayments) -> None:
    row.enabled = spec.enabled
    row.provider = PaymentProvider(spec.provider)
    row.payable = spec.payable.model_dump() if spec.payable is not None else None
    row.currencies = list(spec.currencies)
    row.max_amount_minor = spec.max_amount_minor
    row.success_urls = list(spec.success_urls)
    row.cancel_urls = list(spec.cancel_urls)
    row.roles = spec.roles.model_dump()
    row.refund_approval_threshold_minor = spec.refund_approval_threshold_minor
    row.scale = spec.scale.model_dump()
    row.security = spec.security.model_dump()


class PaymentsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise _not_found("project")
        return project

    async def _config(self, project_id: uuid.UUID) -> ProjectPaymentsConfig | None:
        return (
            await self.session.execute(
                select(ProjectPaymentsConfig).where(ProjectPaymentsConfig.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def _auth(self, project_id: uuid.UUID) -> ProjectAuthConfig | None:
        return (
            await self.session.execute(
                select(ProjectAuthConfig).where(ProjectAuthConfig.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def get(self, project_id: uuid.UUID) -> ProjectPaymentsConfig:
        await self._project(project_id)
        config = await self._config(project_id)
        if config is None:
            raise _not_found("payments settings")
        return config

    async def put(self, project_id: uuid.UUID, data: PaymentsConfigWrite) -> ProjectPaymentsConfig:
        await self._project(project_id)
        config = await self._config(project_id)
        if config is None:
            config = ProjectPaymentsConfig(project_id=project_id, enabled=False)
            self.session.add(config)
        enabled = config.enabled  # saving settings never switches the feature
        body = {**data.model_dump(mode="json"), "enabled": enabled}
        apply_spec(config, SpecPayments.model_validate(body))
        await self.session.commit()
        return config

    async def sizing(self, project_id: uuid.UUID) -> PaymentsSizing:
        config = await self.get(project_id)
        return size(SpecPaymentsScale.model_validate(config.scale))

    # --- switching ------------------------------------------------------------------

    async def impact(self, project_id: uuid.UUID, action: str) -> PaymentsImpact:
        await self._project(project_id)
        config = await self._config(project_id)
        enabled = config is not None and config.enabled
        blockers: list[str] = []
        warnings: list[str] = []

        if action == "enable":
            if enabled:
                blockers.append("Payments are already on for this project.")
            if config is None:
                blockers.append("Save the payments settings first.")
            auth = await self._auth(project_id)
            if auth is None or not auth.enabled:
                blockers.append("Payments need authentication: turn it on first.")
            warnings.append(
                "The next generated project gets payment tables (a migration), a webhook endpoint, "
                "a worker process and deployment files. Provider keys are never stored here; you "
                "set them as environment variables of the generated project."
            )
        elif action == "disable":
            if not enabled:
                blockers.append("Payments are not on for this project.")
            warnings.append(
                "Payments disappear from the next generated project. Money already taken can only "
                "be refunded through your provider's dashboard until you turn payments back on, "
                "and the provider's webhooks to this backend will fail until you remove them there."
            )
            warnings.append("Your payments settings are kept, so you can turn payments back on.")
        else:
            raise _invalid("action must be enable or disable")
        warnings.append(_DEPLOYED_NOTE)
        return PaymentsImpact(
            action=action,
            enabled=enabled,
            can_proceed=not blockers,
            blockers=blockers,
            warnings=warnings,
        )

    async def switch(
        self, project_id: uuid.UUID, action: str, *, confirm: bool
    ) -> ProjectPaymentsConfig:
        if not confirm:
            raise AppError(
                code="confirmation_required",
                message="switching payments needs confirm=true; read /payments/impact first to "
                "see what it changes",
                status_code=422,
            )
        impact = await self.impact(project_id, action)
        if not impact.can_proceed:
            raise AppError(code="invalid_state", message=" ".join(impact.blockers), status_code=409)
        config = await self.get(project_id)
        config.enabled = action == "enable"
        await self.session.commit()
        return config


def sizing_payload(sizing: PaymentsSizing) -> dict[str, Any]:
    return sizing.to_dict()
