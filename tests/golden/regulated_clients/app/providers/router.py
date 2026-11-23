"""The credential vault API (generated). Admin role only (default deny): every route needs it.

Secrets are write-only. A listing shows names, a fingerprint and dates; no route returns a value, and
nothing in this file decrypts (that happens only in app/providers/client.py)."""

import datetime as _dt
import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.auth.deps import CurrentPrincipal, require_roles
from app.core.errors import AppError, NotFoundError
from app.db import SessionDep
from app.providers import client, definitions, logsafe, vault
from app.providers.errors import NotConfigured, VaultError
from app.providers.schemas import KINDS, HealthStatus

router = APIRouter(
    prefix="/providers",
    tags=["providers"],
    dependencies=[Depends(require_roles(definitions.ADMIN_ROLE))],
)


class CredentialIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: SecretStr = Field(min_length=1, max_length=vault.MAX_SECRET_LENGTH)


class CredentialOut(BaseModel):
    provider: str
    key_name: str
    fingerprint: str
    key_version: int
    created_at: _dt.datetime
    rotated_at: _dt.datetime | None


def _out(meta: vault.CredentialMeta) -> CredentialOut:
    return CredentialOut(**meta.__dict__)


def _tenant(principal: CurrentPrincipal) -> uuid.UUID:
    return principal.tenant_id or vault.NIL_TENANT


def _known(provider: str, key_name: str | None = None) -> None:
    if provider not in definitions.PROVIDERS:
        raise NotFoundError("unknown provider")
    if not vault.NAME_RE.fullmatch(provider) or (key_name is not None and not vault.NAME_RE.fullmatch(key_name)):
        raise AppError("validation_error", "names are lowercase letters, digits and underscores", 422)


@router.get("/credentials", response_model=list[CredentialOut])
async def list_credentials(
    session: SessionDep, principal: CurrentPrincipal, provider: str | None = None
) -> list[CredentialOut]:
    if provider is not None:
        _known(provider)
    return [_out(m) for m in await vault.list_credentials(session, _tenant(principal), provider)]


@router.put("/credentials/{provider}/{key_name}", response_model=CredentialOut)
async def put_credential(
    provider: str, key_name: str, body: CredentialIn, session: SessionDep, principal: CurrentPrincipal
) -> CredentialOut:
    _known(provider, key_name)
    try:
        meta = await vault.put(
            session, _tenant(principal), provider, key_name, body.value.get_secret_value(), principal.user_id
        )
    except VaultError as exc:
        raise AppError("vault_unavailable", str(exc), 503) from None
    await session.commit()
    logsafe.log("credential_written", provider=provider, key_name=key_name, tenant=str(_tenant(principal)))
    return _out(meta)


@router.delete("/credentials/{provider}/{key_name}", status_code=204)
async def delete_credential(
    provider: str, key_name: str, session: SessionDep, principal: CurrentPrincipal
) -> Response:
    _known(provider, key_name)
    if not await vault.delete(session, _tenant(principal), provider, key_name):
        raise NotFoundError("credential not found")
    await session.commit()
    logsafe.log("credential_deleted", provider=provider, key_name=key_name, tenant=str(_tenant(principal)))
    return Response(status_code=204)


@router.get("/health/{kind}", response_model=HealthStatus)
async def provider_health(kind: str, session: SessionDep, principal: CurrentPrincipal) -> HealthStatus:
    """Health of the adapter this tenant would use for `kind`."""
    if kind not in KINDS:
        raise NotFoundError("unknown provider kind")
    try:
        return await client.check_health(session, _tenant(principal), kind)
    except NotConfigured:
        return HealthStatus(ok=False, detail="no provider is configured for this tenant")
    except VaultError:
        return HealthStatus(ok=False, detail="the credential vault is unavailable")
