"""MCP-M4: non-secret settings of payments/storage/documents/observability/deployment, plus the
metrics layer and scheduled reports.

Thin wrappers over the SAME services as the dashboard routes, so validation, versioning
(`expected_version`) and "saving settings never switches payments/storage on" are identical.
Added rules: scope mcp:write + editor role + pin/MCP grant like every write tool, and a SECRET
REFUSAL: a value whose key names or string shapes look like a credential is refused with code
`secret_not_allowed` BEFORE any validation, and the offending value is never echoed (only its path).
"""

import re
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.exceptions import AppError
from app.schemas.deployment import DeploymentWrite
from app.schemas.documents import DocumentsWrite
from app.schemas.metrics import ReportBody
from app.schemas.observability import ObservabilityWrite
from app.schemas.payments import PaymentsConfigRead, PaymentsConfigWrite
from app.schemas.storage import StorageConfigRead, StorageConfigWrite
from app.services import mcp_secrets
from app.services.access_service import Principal
from app.services.deployment_service import DeploymentService
from app.services.documents_service import DocumentsService
from app.services.mcp_extra import _bad, _validation_error
from app.services.mcp_service import McpService, _cap_dict
from app.services.metrics_service import MetricsService
from app.services.observability_service import ObservabilityService
from app.services.payments_service import PaymentsService
from app.services.storage_service import StorageService

SECTIONS = ("payments", "storage", "documents", "observability", "deployment")

_SECRET_KEY = re.compile(
    r"secret|password|passwd|api_?key|private_?key|access_?key|credential|bearer|auth_?token",
    re.IGNORECASE,
)
_ALLOWED_KEYS = frozenset({"secrets_from_files"})  # a legit boolean toggle, not a secret
_SECRET_VALUE = re.compile(
    r"sk_live_|sk_test_|rk_live_|whsec_|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|"
    r"xox[bp]-|gh[pousr]_[A-Za-z0-9]{10,}"
)
_HINT = {
    "payments": mcp_secrets._PAYMENTS,
    "storage": mcp_secrets._STORAGE,
    "deployment": mcp_secrets._DEPLOY,
}


def find_secret(value: Any, path: str = "") -> str | None:
    """Path of the first secret-looking key name or string value, or None. Never the value."""
    if isinstance(value, dict):
        for k, v in value.items():
            here = f"{path}.{k}" if path else str(k)
            if str(k) not in _ALLOWED_KEYS and _SECRET_KEY.search(str(k)):
                return here[:120]
            found = find_secret(v, here)
            if found:
                return found
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found = find_secret(v, f"{path}[{i}]")
            if found:
                return found
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        return (path or "<value>")[:120]
    return None


def _models() -> dict[str, type[BaseModel]]:
    return {
        "payments": PaymentsConfigWrite,
        "storage": StorageConfigWrite,
        "documents": DocumentsWrite,
        "observability": ObservabilityWrite,
        "deployment": DeploymentWrite,
    }


class McpConfigService(McpService):
    async def _write_member(self, principal: Principal, project_id: uuid.UUID) -> Any:
        member = await self._resolve_membership(principal, project_id)
        await self._require_editor(member)
        return member

    @staticmethod
    def _section(section: str) -> str:
        if section not in SECTIONS:
            raise _bad(
                "unknown_section", f"unknown section {section!r}; valid sections: {list(SECTIONS)}"
            )
        return section

    async def _read(self, section: str, project_id: uuid.UUID) -> dict[str, Any] | None:
        """The Read schema as json, or None while payments/storage were never saved (REST: 404)."""
        try:
            if section == "payments":
                row = await PaymentsService(self.db).get(project_id)
                return PaymentsConfigRead.model_validate(row).model_dump(mode="json")
            if section == "storage":
                srow = await StorageService(self.db).get(project_id)
                return StorageConfigRead.model_validate(srow).model_dump(mode="json")
            getters: dict[str, Callable[[], Any]] = {
                "documents": lambda: DocumentsService(self.db).get(project_id),
                "observability": lambda: ObservabilityService(self.db).get(project_id),
                "deployment": lambda: DeploymentService(self.db).get(project_id),
            }
            return dict((await getters[section]()).model_dump(mode="json"))
        except AppError as exc:
            if (
                exc.status_code == 404
                and section in ("payments", "storage")
                and "settings" in exc.message
            ):
                return None
            raise

    async def get_config_section(
        self, principal: Principal, project_id: uuid.UUID, section: str
    ) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        self._section(section)
        value = await self._read(section, project_id)
        await self._audit(principal, "get_config_section", project_id, extra={"section": section})
        if value is None:
            return {
                "section": section,
                "saved": False,
                "value": None,
                "next": f"nothing saved yet: send set_config_section(section={section!r}, value={{...}})",
            }
        return _cap_dict({"section": section, "saved": True, "value": value})

    async def set_config_section(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        section: str,
        value: dict[str, Any],
        expected_version: int | None = None,
    ) -> dict[str, object]:
        await self._write_member(principal, project_id)
        self._section(section)
        if not isinstance(value, dict):
            raise _bad("invalid_input", "value must be an object")
        bad = find_secret(value)
        if bad:
            hint = _HINT.get(section, "the dashboard")
            raise _bad(
                "secret_not_allowed",
                f"'{bad}' looks like a credential and is refused (the value is not shown). "
                f"Credentials are never set over MCP: tell the user to enter them in: {hint}. "
                "list_secrets_needed lists everything only a person can do.",
            )
        model = _models()[section]
        valid = set(model.model_fields) - {"expected_version"}
        unknown = sorted(set(value) - valid)
        if unknown:
            raise _bad(
                "unknown_keys",
                f"unknown keys {unknown} for {section}; valid keys: {sorted(valid)}",
            )
        if "expected_version" in model.model_fields:
            body_in = {**value, "expected_version": expected_version}
        elif expected_version is not None:
            raise _bad(
                "invalid_input", f"{section} settings have no version; omit expected_version"
            )
        else:
            body_in = dict(value)
        try:
            body = model.model_validate(body_in)
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        if isinstance(body, PaymentsConfigWrite):
            read: dict[str, Any] = PaymentsConfigRead.model_validate(
                await PaymentsService(self.db).put(project_id, body)
            ).model_dump(mode="json")
        elif isinstance(body, StorageConfigWrite):
            read = StorageConfigRead.model_validate(
                await StorageService(self.db).put(project_id, body)
            ).model_dump(mode="json")
        elif isinstance(body, DocumentsWrite):
            read = (await DocumentsService(self.db).put(project_id, body)).model_dump(mode="json")
        elif isinstance(body, ObservabilityWrite):
            read = (await ObservabilityService(self.db).put(project_id, body)).model_dump(
                mode="json"
            )
        else:
            assert isinstance(body, DeploymentWrite)
            read = (await DeploymentService(self.db).put(project_id, body)).model_dump(mode="json")
        await self._audit(
            principal,
            "set_config_section",
            project_id,
            extra={"section": section, "keys": sorted(value)[:30]},
        )
        if section in ("payments", "storage"):
            nxt = (
                f"Settings saved; {section} stays OFF (saving never switches it). Turning it on is a "
                "confirmed switch the user makes in the dashboard. Credentials go there too "
                "(list_secrets_needed). Then run validate_spec."
            )
        else:
            nxt = "Saved. Run validate_spec / get_project_status to see what is still missing."
        return _cap_dict(
            {
                "section": section,
                "saved": True,
                "enabled": read.get("enabled"),
                "value": read,
                "next": nxt,
            }
        )

    # -- metrics layer and reports ---------------------------------------------------------

    async def list_metrics(self, principal: Principal, project_id: uuid.UUID) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        page = await MetricsService(self.db).list_metrics(project_id)
        await self._audit(principal, "list_metrics", project_id)
        return _cap_dict(page.model_dump(mode="json"))

    async def define_metric(
        self, principal: Principal, project_id: uuid.UUID, key: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        await self._write_member(principal, project_id)
        if not isinstance(definition, dict):
            raise _bad("invalid_input", "definition must be an object")
        if definition.get("key", key) != key:
            raise _bad("invalid_input", "definition.key must equal key (or be left out)")
        svc = MetricsService(self.db)
        raw = {**definition, "key": key}
        try:
            await svc.get_metric(project_id, key)
            exists = True
        except AppError as exc:
            if exc.status_code != 404:
                raise
            exists = False
        if exists:
            out = await svc.update_metric(project_id, key, raw)
        else:
            out = await svc.create_metric(project_id, raw)
        await self._audit(
            principal, "define_metric", project_id, extra={"key": key[:80], "created": not exists}
        )
        return _cap_dict({**out.model_dump(mode="json"), "created": not exists})

    async def get_metric_value(
        self, principal: Principal, project_id: uuid.UUID, key: str
    ) -> dict[str, object]:
        member = await self._resolve_membership(principal, project_id)
        out = await MetricsService(self.db).metric_value(project_id, key, member.role.value)
        await self._audit(principal, "get_metric_value", project_id, extra={"key": key[:80]})
        return _cap_dict(out.model_dump(mode="json"))

    async def list_reports(self, principal: Principal, project_id: uuid.UUID) -> dict[str, object]:
        await self._resolve_membership(principal, project_id)
        page = await MetricsService(self.db).list_reports(project_id)
        await self._audit(principal, "list_reports", project_id)
        return _cap_dict(page.model_dump(mode="json"))

    async def define_report(
        self,
        principal: Principal,
        project_id: uuid.UUID,
        name: str,
        metric_keys: list[str],
        schedule: str,
        timezone: str = "UTC",
        enabled: bool = True,
        report_id: uuid.UUID | None = None,
    ) -> dict[str, object]:
        await self._write_member(principal, project_id)
        try:
            body = ReportBody(
                name=name,
                metric_keys=metric_keys,
                schedule=schedule,
                timezone=timezone,
                enabled=enabled,
            )
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        svc = MetricsService(self.db)
        if report_id is None:
            out = await svc.create_report(project_id, body)
        else:
            out = await svc.update_report(project_id, report_id, body)
        await self._audit(
            principal, "define_report", project_id,
            extra={"report_id": str(out.id), "created": report_id is None},
        )  # fmt: skip
        return _cap_dict({**out.model_dump(mode="json"), "created": report_id is None})

    async def run_report(
        self, principal: Principal, project_id: uuid.UUID, report_id: uuid.UUID
    ) -> dict[str, object]:
        member = await self._write_member(principal, project_id)
        out = await MetricsService(self.db).run_now(project_id, report_id, member.role.value)
        await self._audit(principal, "run_report", project_id, extra={"report_id": str(report_id)})
        return _cap_dict(out.model_dump(mode="json"))
