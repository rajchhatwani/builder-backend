"""The error taxonomy every adapter maps its failures onto (generated).

Messages are written here, by the platform, from fixed text: never from a provider's response body
or a request, so an error can be logged and returned without leaking a credential or a payload."""


class ProviderError(Exception):
    """Base of every provider failure. `code` is stable and safe to show."""

    code = "provider_error"
    retryable = False

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)


class Retryable(ProviderError):
    """A temporary failure (5xx, network, timeout): the call may be repeated."""

    code = "retryable"
    retryable = True


class Permanent(ProviderError):
    """The provider refused the request itself (4xx): repeating it will not help."""

    code = "permanent"


class AuthFailed(ProviderError):
    """The tenant's credentials were refused or are missing: an admin must fix them."""

    code = "auth_failed"


class RateLimited(ProviderError):
    """The provider asked us to slow down. `retry_after` is seconds (None = unknown)."""

    code = "rate_limited"
    retryable = True

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderTimeout(Retryable):
    code = "timeout"


class CircuitOpen(ProviderError):
    """The circuit breaker is open: the call was not attempted."""

    code = "circuit_open"


class NotConfigured(ProviderError):
    """No adapter may serve this tenant and kind (no credentials in production)."""

    code = "not_configured"


class VaultError(ProviderError):
    """The vault cannot be used (no master key, a key version that is no longer configured)."""

    code = "vault_error"


class CredentialNotFound(VaultError):
    code = "credential_not_found"
