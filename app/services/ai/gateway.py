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
)
from app.services.ai.claude import ClaudeProvider
from app.services.ai.fake import FakeProvider
from app.services.ai.pricing import price_table
from app.services.ai.ledger import AiLedgerService
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

    async def _provider(self, org_id: uuid.UUID) -> ModelProvider:
        key = await self.ledger.api_key(org_id)
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
        try:
            result = await provider.complete(model, request)
        except ProviderError as exc:
            raise AppError("ai_provider_error", str(exc), 502) from None
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
        try:
            async for event in provider.stream(model, request):
                if event.kind == "done" and event.completion is not None:
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
            raise AppError("ai_provider_error", str(exc), 502) from None
