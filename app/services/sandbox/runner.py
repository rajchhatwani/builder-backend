"""Narrow sandbox runner (P1): the ONLY process that holds docker access.

Run:  BB_RUNNER_TOKEN=<32+ chars> python -m app.services.sandbox.runner --uds /run/bb/runner.sock
      (or --host 127.0.0.1 --port 8790). Settings come from the usual BUILDER_* env:
      BUILDER_RUNNER_MOUNT_ROOT (the only directory a code mount may come from),
      BUILDER_SANDBOX_IMAGES, BUILDER_SANDBOX_RUNTIME, BUILDER_SANDBOX_DOCKER_BIN.

The API process talks to it through RemoteSandbox. What it exposes is a closed list of operations
mirroring the Sandbox interface; there is no way to pass raw docker arguments. Every start request
goes through the same `_validate`/`build_run_args` as a direct DockerSandbox (so: runner-built
labels bb.sandbox*, image allow-list, non-root user, --internal networks only, never privileged,
host network, published ports or docker.sock), plus: the code mount must resolve under
`runner_mount_root`, unknown fields/operations are refused, the body is size-capped, and
operations on existing containers only touch containers carrying the bb.sandbox label.
The runner runs docker with its own environment; nothing from a caller reaches DOCKER_HOST,
DOCKER_CONFIG or DOCKER_CONTEXT. Request bodies (which carry container env values) are never logged.
"""

import argparse
import hmac
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.services.sandbox import wire as w
from app.services.sandbox.base import LABEL, SandboxError
from app.services.sandbox.docker import DockerSandbox, name_for

TOKEN_ENV = "BB_RUNNER_TOKEN"  # noqa: S105 (env var NAME)
MIN_TOKEN_LEN = 32
MAX_BODY_BYTES = 256 * 1024


class RunnerRefusal(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class RunnerCore:
    """Validation + dispatch, separate from HTTP so it is unit-testable."""

    def __init__(self, settings: Settings, box: DockerSandbox | None = None) -> None:
        self.settings = settings
        self.box = box or DockerSandbox(settings, runner_process=True)
        root = settings.runner_mount_root
        self.mount_root = Path(root).resolve() if root else None

    # -- checks beyond _validate -------------------------------------------------------------
    def check_spec(self, spec: w.SpecW) -> None:
        if spec.code_dir is not None:
            if self.mount_root is None:
                raise RunnerRefusal(422, "code mounts are disabled (runner_mount_root unset)")
            resolved = Path(spec.code_dir).resolve()
            if not resolved.is_relative_to(self.mount_root) or resolved == self.mount_root:
                raise RunnerRefusal(422, "code_dir is outside the runner mount root")

    async def _labelled(self, sandbox_id: str) -> bool:
        """True when a container of that name exists AND carries our label."""
        rc, out, _ = await self.box._docker(
            "inspect", "--format", '{{index .Config.Labels "' + LABEL + '"}}', name_for(sandbox_id)
        )
        return rc == 0 and out.strip() == "1"

    async def _require_labelled(self, sandbox_id: str) -> None:
        if not await self._labelled(sandbox_id):
            raise RunnerRefusal(404, "no such sandbox")

    # -- operations --------------------------------------------------------------------------
    async def check_runtime(self, _r: w.Empty) -> dict[str, Any]:
        await self.box.check_runtime()
        return {}

    async def create_network(self, r: w.CreateNetworkReq) -> dict[str, Any]:
        lim = r.limits.to_limits() if r.limits else None
        if lim:
            lim.validate()
        return {"name": await self.box.create_network(r.sandbox_id, lim)}

    async def start(self, r: w.SpecReq) -> dict[str, Any]:
        self.check_spec(r.spec)
        return {"sandbox_id": await self.box.start(r.spec.to_spec())}

    async def run(self, r: w.SpecReq) -> dict[str, Any]:
        self.check_spec(r.spec)
        return w.run_result_to_dict(await self.box.run(r.spec.to_spec()))

    async def state(self, r: w.IdReq) -> dict[str, Any]:
        await self._require_labelled(r.sandbox_id)
        return {"running": await self.box.is_running(r.sandbox_id)}

    async def logs(self, r: w.LogsReq) -> dict[str, Any]:
        await self._require_labelled(r.sandbox_id)
        return {"logs": await self.box.logs(r.sandbox_id, tail=r.tail, since=r.since)}

    async def exec(self, r: w.ExecReq) -> dict[str, Any]:
        await self._require_labelled(r.sandbox_id)
        return w.run_result_to_dict(await self.box.exec(r.sandbox_id, r.argv, r.timeout))

    async def stop(self, r: w.IdReq) -> dict[str, Any]:
        await self._require_labelled(r.sandbox_id)
        await self.box.stop(r.sandbox_id)
        return {}

    async def destroy(self, r: w.IdReq) -> dict[str, Any]:
        # An absent/foreign container is a no-op, never a removal: only labelled ones are removed.
        if await self._labelled(r.sandbox_id):
            await self.box.destroy(r.sandbox_id)
        else:
            await self._destroy_networks_only(r.sandbox_id)
        return {}

    async def _destroy_networks_only(self, sandbox_id: str) -> None:
        # DockerSandbox.destroy filters networks by our label, so it is safe even with no container.
        # The `rm -f` of a same-named FOREIGN container is what we avoid here, hence this split.
        rc, out, _ = await self.box._docker(
            "network", "ls", "-q", "--filter", f"label=bb.sandbox.id={sandbox_id}"
        )
        if rc == 0:
            for net_id in out.split():
                await self.box._docker("network", "rm", net_id)

    async def reap(self, r: w.ReapReq) -> dict[str, Any]:
        return w.reap_to_dict(await self.box.reap(r.now))

    async def ip_of(self, r: w.IpReq) -> dict[str, Any]:
        await self._require_labelled(r.sandbox_id)
        return {"ip": await self.box.ip_of(r.sandbox_id, r.network)}


Handler = Callable[[Any], Awaitable[dict[str, Any]]]


def _routes(core: RunnerCore) -> dict[str, tuple[type[BaseModel], Handler]]:
    return {
        "check_runtime": (w.Empty, core.check_runtime),
        "create_network": (w.CreateNetworkReq, core.create_network),
        "start": (w.SpecReq, core.start),
        "run": (w.SpecReq, core.run),
        "state": (w.IdReq, core.state),
        "logs": (w.LogsReq, core.logs),
        "exec": (w.ExecReq, core.exec),
        "stop": (w.IdReq, core.stop),
        "destroy": (w.IdReq, core.destroy),
        "reap": (w.ReapReq, core.reap),
        "ip_of": (w.IpReq, core.ip_of),
    }


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def create_app(
    settings: Settings | None = None,
    token: str | None = None,
    core: RunnerCore | None = None,
    max_body: int = MAX_BODY_BYTES,
) -> FastAPI:
    """Build the runner app. Refuses to build without a strong token (fail closed)."""
    tok = token if token is not None else os.environ.get(TOKEN_ENV, "")
    if len(tok) < MIN_TOKEN_LEN:
        raise SandboxError(f"{TOKEN_ENV} must be set (>= {MIN_TOKEN_LEN} chars)")
    token_bytes = tok.encode()
    rcore = core or RunnerCore(settings or get_settings())
    routes = _routes(rcore)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/{op}")
    async def dispatch(op: str, request: Request) -> JSONResponse:
        auth = request.headers.get("authorization", "")
        scheme, _, given = auth.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(given.encode(), token_bytes):
            return _err(401, "unauthorized")
        route = routes.get(op)
        if route is None:
            return _err(404, "unknown operation")
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > max_body):
            return _err(413, "request too large")
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > max_body:
                return _err(413, "request too large")
        try:
            data = json.loads(bytes(buf) or b"{}")
            model, handler = route
            req = model.model_validate(data)
        except (ValueError, ValidationError):
            return _err(422, "invalid request")  # never echo the body (it may hold env values)
        try:
            return JSONResponse(await handler(req))
        except RunnerRefusal as exc:
            return _err(exc.status, exc.message)
        except SandboxError as exc:
            return _err(422, str(exc))
        except TimeoutError:
            return _err(504, "docker timed out")

    return app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.services.sandbox.runner")
    ap.add_argument("--uds", help="unix socket path (mode 0600)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args(argv)
    if not a.uds and a.host not in ("127.0.0.1", "::1"):
        print("runner refuses to bind a non-loopback address", file=sys.stderr)
        return 2
    try:
        app = create_app()
    except SandboxError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    import uvicorn

    if a.uds:
        os.umask(0o077)
        uvicorn.run(app, uds=a.uds, access_log=False, log_level="warning")
    else:
        uvicorn.run(app, host=a.host, port=a.port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
