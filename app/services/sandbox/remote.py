"""RemoteSandbox: the Sandbox interface over the narrow runner's HTTP API (P1).

Never runs the docker binary and never reads DOCKER_HOST. The bearer token comes from settings
(SecretStr) and travels only in the Authorization header; request bodies (container env values)
are never logged and error text never includes them.
"""

from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings, get_settings
from app.services.sandbox import wire as w
from app.services.sandbox.base import (
    Limits,
    ReapResult,
    RunResult,
    Sandbox,
    SandboxError,
    SandboxSpec,
)

_DEFAULT_TIMEOUT = 120.0


class RemoteSandbox(Sandbox):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        s = settings or get_settings()
        if not s.sandbox_runner_url or s.sandbox_runner_token is None:
            raise SandboxError("sandbox_runner_url and sandbox_runner_token are required")
        parts = urlsplit(s.sandbox_runner_url)
        self._base = "http://runner"
        if parts.scheme == "unix":
            transport = transport or httpx.AsyncHTTPTransport(uds=parts.path)
        else:
            self._base = s.sandbox_runner_url.rstrip("/")
        self._transport = transport
        self._auth = {"Authorization": "Bearer " + s.sandbox_runner_token.get_secret_value()}

    async def _call(
        self, op: str, body: dict[str, Any] | None = None, timeout: float = _DEFAULT_TIMEOUT
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=timeout, trust_env=False
            ) as client:
                r = await client.post(f"{self._base}/v1/{op}", json=body or {}, headers=self._auth)
        except httpx.TimeoutException:
            raise SandboxError("sandbox runner timed out") from None
        except httpx.HTTPError:
            raise SandboxError("sandbox runner is not reachable") from None
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code != 200 or not isinstance(data, dict):
            msg = data.get("error") if isinstance(data, dict) else None
            raise SandboxError(f"sandbox runner refused ({r.status_code}): {str(msg)[:200]}")
        return data

    @staticmethod
    def _result(d: dict[str, Any]) -> RunResult:
        return RunResult(**{k: d[k] for k in RunResult.__dataclass_fields__ if k in d})

    async def check_runtime(self) -> None:
        await self._call("check_runtime")

    async def create_network(self, sandbox_id: str, limits: Limits | None = None) -> str:
        body = {"sandbox_id": sandbox_id, "limits": w.LimitsW.of(limits).model_dump() if limits else None}
        return str((await self._call("create_network", body))["name"])

    async def start(self, spec: SandboxSpec) -> str:
        d = await self._call("start", {"spec": w.SpecW.of(spec).model_dump()})
        return str(d["sandbox_id"])

    async def run(self, spec: SandboxSpec) -> RunResult:
        d = await self._call(
            "run", {"spec": w.SpecW.of(spec).model_dump()}, spec.limits.wall_seconds + 90
        )
        return self._result(d)

    async def exec(self, sandbox_id: str, argv: list[str], timeout: float) -> RunResult:
        timeout = max(0.1, min(timeout, 3600))
        d = await self._call(
            "exec", {"sandbox_id": sandbox_id, "argv": argv, "timeout": timeout}, timeout + 30
        )
        return self._result(d)

    async def logs(self, sandbox_id: str, tail: int = 2000, since: str | None = None) -> str:
        body = {"sandbox_id": sandbox_id, "tail": max(1, min(tail, 2000)), "since": since}
        try:
            return str((await self._call("logs", body))["logs"])
        except SandboxError:
            return ""

    async def is_running(self, sandbox_id: str) -> bool:
        try:
            return bool((await self._call("state", {"sandbox_id": sandbox_id}))["running"])
        except SandboxError:
            return False

    async def ip_of(self, sandbox_id: str, network: str) -> str | None:
        try:
            ip = (await self._call("ip_of", {"sandbox_id": sandbox_id, "network": network}))["ip"]
        except SandboxError:
            return None
        return str(ip) if ip else None

    async def stop(self, sandbox_id: str) -> None:
        await self._call("stop", {"sandbox_id": sandbox_id}, 60)

    async def destroy(self, sandbox_id: str) -> None:
        await self._call("destroy", {"sandbox_id": sandbox_id})

    async def reap(self, now: float | None = None) -> ReapResult:
        d = await self._call("reap", {"now": now}, 300)
        return ReapResult(containers=list(d["containers"]), networks=list(d["networks"]))
