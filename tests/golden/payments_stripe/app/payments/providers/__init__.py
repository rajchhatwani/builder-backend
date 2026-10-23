"""Provider selection (generated). Tests replace the provider with `set_provider`."""

import importlib

from app.payments import config
from app.payments.providers.base import PaymentProvider

_CLASSES = {"stripe": "StripeProvider", "razorpay": "RazorpayProvider"}
_provider: PaymentProvider | None = None


def get_provider() -> PaymentProvider:
    global _provider
    if _provider is None:
        module = importlib.import_module(f"app.payments.providers.{config.PROVIDER}")
        _provider = getattr(module, _CLASSES[config.PROVIDER])()
    return _provider


def set_provider(provider: PaymentProvider | None) -> None:
    global _provider
    _provider = provider
