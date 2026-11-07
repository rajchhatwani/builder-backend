"""One entry point for the agent: route the model, check the budget, call, write the ledger."""

import uuid
from collections.abc import AsyncIterator, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import AppError
from app.services.ai.base import (
    Completion,
    CompletionRequest,
    ModelProvider,
    ProviderError,
    StreamEvent,
    TaskClass,
    Usage,
)
from app.services.ai.claude import ClaudeProvider
from app.services.ai.fake import FakeProvider
from app.services.ai.ledger import AiLedgerService
from app.services.ai.platform_cap import PlatformCap, Reservation
from app.services.ai.pricing import price_table
from app.services.ai.routing import route_model

ProviderFactory = Callable[[str | None], ModelProvider]


class ModelGateway:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = AiLedgerService(session, settings)
        self._factory = provider_factory
        self._cap = PlatformCap(session, settings)
        self._byo = False

    async def _reserve(self, provider: ModelProvider, model: str, request: CompletionRequest) -> Reservation | None:
        # Fake providers cost nothing real and are never counted against the platform cap.
        if isinstance(provider, FakeProvider) or self._byo:
            return None
        return await self._cap.reserve(model, request)

    async def _settle(
        self, res: Reservation | None, model: str, usage: Usage | None, error: ProviderError | None = None
    ) -> None:
        if res is None:
            return
        if usage is None and (error is None or error.status_code is None):
            # Outcome unknown (timeout, dropped stream): the call may have been billed, so the
            # worst case stays counted.
            await self._cap.settle_worst_case(res)
        else:
            await self._cap.settle(res, model, usage)

    async def _provider(self, org_id: uuid.UUID) -> ModelProvider:
        key = await self.ledger.api_key(org_id)
        self._byo = key is not None  # the org pays with its own key: not the owner's budget
        if key is None and self.settings.ai_api_key is not None:
            # By org ID, never by slug: a slug is user-chosen and can be claimed by anyone.
            if str(org_id) in self.settings.ai_platform_key_orgs:
                key = self.settings.ai_api_key.get_secret_value()
        if self._factory is not None:
            return self._factory(key)
        if self.settings.ai_provider == "fake":
            if not self.settings.is_local and self.settings.environment not in ("test", "testing"):
                raise AppError("ai_provider_misconfigured", "fake provider is not allowed here", 500)
            return FakeProvider()
        if key is None:
            raise AppError("ai_key_missing", "add your model provider API key first", 409)
        return ClaudeProvider(key, timeout=self.settings.ai_request_timeout_seconds)

    def _require_price(self, model: str) -> None:
        # Check before calling the provider so an unpriced model never makes an unbilled call.
        if model not in price_table(self.settings.ai_price_table):
            raise AppError("ai_model_unpriced", f"no price configured for model '{model}'", 500)

    async def complete(
        self,
        org_id: uuid.UUID,
        task_class: TaskClass,
        request: CompletionRequest,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
    ) -> Completion:
        await self.ledger.check_budget(org_id)
        provider = await self._provider(org_id)
        model = route_model(task_class, self.settings)
        self._require_price(model)
        res = await self._reserve(provider, model, request)
        try:
            result = await provider.complete(model, request)
        except ProviderError as exc:
            await self._settle(res, model, None, exc)
            raise AppError("ai_provider_error", str(exc), 502) from None
        except BaseException:
            await self._settle(res, model, None)
            raise
        await self._settle(res, model, result.usage)
        await self.ledger.record(
            org_id,
            project_id=project_id,
            run_id=run_id,
            model=model,
            task_class=task_class.value,
            usage=result.usage,
        )
        return result

    async def stream(
        self,
        org_id: uuid.UUID,
        task_class: TaskClass,
        request: CompletionRequest,
        *,
        project_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
    ) -> AsyncIterator[StreamEvent]:
        await self.ledger.check_budget(org_id)
        provider = await self._provider(org_id)
        model = route_model(task_class, self.settings)
        self._require_price(model)
        res = await self._reserve(provider, model, request)
        settled = False
        try:
            async for event in provider.stream(model, request):
                if event.kind == "done" and event.completion is not None:
                    await self._settle(res, model, event.completion.usage)
                    settled = True
                    await self.ledger.record(
                        org_id,
                        project_id=project_id,
                        run_id=run_id,
                        model=model,
                        task_class=task_class.value,
                        usage=event.completion.usage,
                    )
                yield event
        except ProviderError as exc:
            if not settled:
                settled = True
                await self._settle(res, model, None, exc)
            raise AppError("ai_provider_error", str(exc), 502) from None
        finally:
            if not settled:
                await self._settle(res, model, None)
