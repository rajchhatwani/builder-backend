"""Pick the Sandbox implementation: the narrow runner when configured, else direct docker."""

from app.config import Settings, get_settings
from app.services.sandbox.base import ReapResult, Sandbox
from app.services.sandbox.docker import DockerSandbox
from app.services.sandbox.remote import RemoteSandbox


def make_sandbox(settings: Settings | None = None) -> Sandbox:
    """With `sandbox_runner_url` set the API process never touches docker. Without it,
    DockerSandbox fails closed itself in a deployed (explicit non-local/test) environment."""
    s = settings or get_settings()
    if s.sandbox_runner_url:
        return RemoteSandbox(s)
    return DockerSandbox(s)


async def reap_expired(settings: Settings | None = None) -> ReapResult:
    """Scheduling hook for the preview runtime: call every `sandbox_reap_interval_seconds`.
    Raises SandboxError when the daemon cannot be listed, so the caller can alert."""
    box = make_sandbox(settings)
    await box.check_runtime()
    return await box.reap()
