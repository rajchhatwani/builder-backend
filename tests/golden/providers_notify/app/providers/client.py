"""Calling a provider: selection, guard, timeout, retries, circuit breaker, safe logging (generated).

This is the only code path that decrypts a tenant's credentials."""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers import config, definitions, logsafe, registry, vault
from app.providers.base import Credentials, ProviderAdapter
from app.providers.breaker import breaker_for
from app.providers.errors import (
    AuthFailed,
    CircuitOpen,
    NotConfigured,
    Permanent,
    ProviderError,
    ProviderTimeout,
    RateLimited,
    Retryable,
)
from app.providers.schemas import REQUESTS, HealthStatus

_MAX_WAIT = 30.0
_BACKOFF_BASE = 0.5
sleep: Callable[[float], Awaitable[None]] = asyncio.sleep  # tests replace it


def assert_allowed(adapter: ProviderAdapter) -> None:
    """The guard: APP_ENV=test runs the emulator only; production never runs it."""
    if config.is_test() and adapter.name != "emulator":
        raise NotConfigured("only the emulator may run when APP_ENV=test")
    if config.is_production() and adapter.name == "emulator":
        raise NotConfigured("the emulator may not run in production")


async def resolve(
    session: AsyncSession, tenant_id: uuid.UUID, kind: str, prefer: str | None = None
) -> tuple[ProviderAdapter, Credentials | None]:
    """The adapter this tenant uses for `kind`: the first adapter of the spec (or `prefer`) for which
    the tenant stored credentials. Without credentials: the emulator, but never in production."""
    if kind not in REQUESTS:
        raise NotConfigured("unknown provider kind")
    if not config.is_test():
        names = registry.allowed(kind)
        if prefer is not None:
            names = [n for n in names if n == prefer]
        for name in names:
            if await vault.has_credentials(session, tenant_id, name):
                adapter = registry.adapter(kind, name)
                assert_allowed(adapter)
                return adapter, await vault.load(session, tenant_id, name)
    if config.is_production():
        raise NotConfigured("this tenant has no credentials for a provider of this kind")
    adapter = registry.adapter(kind, "emulator")
    assert_allowed(adapter)
    return adapter, None


def _delay(error: ProviderError, attempt: int) -> float:
    if isinstance(error, RateLimited) and error.retry_after is not None:
        return min(max(error.retry_after, 0.0), _MAX_WAIT)
    return min(_BACKOFF_BASE * 2 ** (attempt - 1), _MAX_WAIT)


async def call_provider(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    kind: str,
    request: BaseModel,
    *,
    prefer: str | None = None,
) -> BaseModel:
    """Send `request` through this tenant's adapter of `kind`. Raises a ProviderError subclass."""
    model = REQUESTS.get(kind)
    if model is None or not isinstance(request, model):
        raise Permanent("the request does not match the provider kind")
    adapter, credentials = await resolve(session, tenant_id, kind, prefer)
    breaker = breaker_for(
        str(tenant_id), kind, adapter.name, definitions.BREAKER_FAILURES, definitions.BREAKER_RESET_SECONDS
    )
    shape = logsafe.shape(request)
    attempt = 0
    while True:
        attempt += 1
        if not breaker.allow():
            logsafe.warn("provider_call", kind=kind, adapter=adapter.name, tenant=str(tenant_id), outcome="circuit_open")
            raise CircuitOpen("the provider is failing: calls are paused for a moment")
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(adapter.call(request, credentials), definitions.TIMEOUT_SECONDS)
            error: ProviderError | None = None
        except TimeoutError:
            error = ProviderTimeout("the provider did not answer in time")
        except ProviderError as exc:
            error = exc
        except Exception as exc:  # noqa: BLE001 - an adapter bug: report the class only, never the text
            logsafe.warn("provider_adapter_bug", kind=kind, adapter=adapter.name, error_class=type(exc).__name__)
            error = Permanent("the adapter failed unexpectedly")
        millis = round((time.monotonic() - started) * 1000)
        if error is None:
            breaker.success()
            logsafe.log(
                "provider_call", kind=kind, adapter=adapter.name, tenant=str(tenant_id),
                outcome="ok", attempt=attempt, ms=millis, request=shape,
            )
            return result
        if isinstance(error, Retryable):
            breaker.failure()  # network and server trouble counts toward opening the breaker
        else:
            breaker.success()  # the provider answered (refused, rate limited): it is reachable
        logsafe.warn(
            "provider_call", kind=kind, adapter=adapter.name, tenant=str(tenant_id),
            outcome=error.code, attempt=attempt, ms=millis, request=shape,
        )
        if error.retryable and attempt < definitions.MAX_ATTEMPTS:
            await sleep(_delay(error, attempt))
            continue
        raise _public(error)


def _public(error: ProviderError) -> ProviderError:
    """The same error with a fixed message: what an adapter wrote is never shown or logged."""
    if isinstance(error, RateLimited):
        return RateLimited("the provider asked us to slow down", retry_after=error.retry_after)
    if isinstance(error, ProviderTimeout):
        return ProviderTimeout("the provider did not answer in time")
    if isinstance(error, AuthFailed):
        return AuthFailed("the provider refused this tenant's credentials")
    if isinstance(error, Retryable):
        return Retryable("the provider is temporarily unavailable")
    if isinstance(error, (CircuitOpen, NotConfigured)):
        return error
    return Permanent("the provider refused the request")


async def check_health(session: AsyncSession, tenant_id: uuid.UUID, kind: str) -> HealthStatus:
    adapter, credentials = await resolve(session, tenant_id, kind)
    try:
        return await asyncio.wait_for(adapter.health(credentials), definitions.TIMEOUT_SECONDS)
    except (TimeoutError, ProviderError):
        return HealthStatus(ok=False, detail="health check failed")
    except Exception:  # noqa: BLE001
        return HealthStatus(ok=False, detail="health check failed")
