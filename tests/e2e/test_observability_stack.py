"""Observability end to end with the real OpenTelemetry Collector (Docker, no compose needed).

1. The collector config the generator writes is accepted by the pinned collector image
   (`validate`), including the redaction and attributes processors.
2. A generated service exports real OTLP/HTTP to a collector running that config's receivers and
   processors; what arrives (spans and metrics, as the collector wrote them) has the right service
   and route names and none of the secrets the requests carried.
"""

import json
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.observability import COLLECTOR_IMAGE
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
TOKEN = "tok_abcdef0123456789"
BEARER = "abcdefghijklmnop.qrstuvwx.yz0123456"

SCRIPT = f"""
import asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.core import telemetry
from app.core.logging import configure_logging

configure_logging("INFO")
app = FastAPI()


@app.get("/items/{{item_id}}")
async def item(item_id: int) -> dict[str, int]:
    return {{"id": item_id}}


handle = telemetry.setup(app)


async def main() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for i in range(5):
            await client.get(
                f"/items/{{i}}?token={TOKEN}",
                headers={{"Authorization": "Bearer {BEARER}"}},
            )


asyncio.run(main())
handle.shutdown()
"""


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=240, check=check
    )


def generated(name: str, tmp: Path) -> dict[str, str]:
    spec = Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    files = generate(spec)
    for path, content in files.items():
        target = tmp / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return files


def test_generated_collector_config_is_valid_for_the_pinned_image(tmp_path: Path) -> None:
    generated("obs_blog", tmp_path)
    config = tmp_path / "deploy" / "observability" / "otel-collector.yaml"
    result = docker(
        "run",
        "--rm",
        "-v",
        f"{config}:/etc/otelcol/config.yaml:ro",
        COLLECTOR_IMAGE,
        "validate",
        "--config=/etc/otelcol/config.yaml",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_otlp_through_a_real_collector_arrives_clean(tmp_path: Path) -> None:
    project = tmp_path / "project"
    out = tmp_path / "out"
    out.mkdir()
    out.chmod(0o777)
    files = generated("obs_blog", project)

    # The generated receivers and processors, with a file exporter instead of Jaeger/Prometheus.
    text = files["deploy/observability/otel-collector.yaml"]
    head = text[: text.index("\nexporters:")]
    config = tmp_path / "collector.yaml"
    config.write_text(
        head
        + """
exporters:
  file/traces:
    path: /out/traces.jsonl
  file/metrics:
    path: /out/metrics.jsonl
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, attributes/drop_headers, redaction, batch]
      exporters: [file/traces]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [file/metrics]
""",
        encoding="utf-8",
    )

    name = f"otel-e2e-{uuid.uuid4().hex[:8]}"
    docker(
        "run", "-d", "--name", name, "-p", "127.0.0.1::4318",
        "-v", f"{config}:/etc/otelcol/config.yaml:ro",
        "-v", f"{out}:/out",
        COLLECTOR_IMAGE, "--config=/etc/otelcol/config.yaml",
    )  # fmt: skip
    try:
        port = int(docker("port", name, "4318/tcp").stdout.strip().rsplit(":", 1)[1])
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("the collector did not start: " + docker("logs", name).stdout)

        script = project / "send_telemetry.py"
        script.write_text(SCRIPT, encoding="utf-8")
        import os

        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env.update(
            OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{port}",
            OTEL_TRACES_SAMPLER="always_on",
            OTEL_BSP_SCHEDULE_DELAY="200",
        )
        launcher = f"import sys; sys.path.insert(0, r'{project}'); exec(open(r'{script}').read())"
        run = subprocess.run(
            [sys.executable, "-I", "-c", launcher],
            cwd=project, env=env, capture_output=True, text=True, timeout=120,
        )  # fmt: skip
        assert run.returncode == 0, run.stdout + run.stderr

        traces, metrics = out / "traces.jsonl", out / "metrics.jsonl"
        deadline = time.time() + 30
        while time.time() < deadline and not (
            traces.exists()
            and traces.stat().st_size > 0
            and metrics.exists()
            and metrics.stat().st_size > 0
        ):
            time.sleep(0.5)
        trace_text = traces.read_text(encoding="utf-8")
        metric_text = metrics.read_text(encoding="utf-8")
    finally:
        logs = docker("logs", name, check=False)
        docker("rm", "-f", name, check=False)

    assert "obs-blog" in trace_text, logs.stderr[-2000:]  # the project's service name
    assert "/items/{item_id}" in trace_text  # the route template, not the raw path
    # span names use the template (few); the raw path stays an attribute of the span
    names = [n for n in re.findall(r'"name":"([^"]*)"', trace_text) if "/items" in n]
    assert names and all("{item_id}" in n for n in names), names
    assert "http.server" in metric_text or "http_server" in metric_text
    for blob in (trace_text, metric_text):
        assert TOKEN not in blob
        assert BEARER not in blob
        assert "abcdefghijklmnop" not in blob
    # every line of the trace file is valid JSON (the collector wrote real OTLP data)
    assert all(json.loads(line) for line in trace_text.splitlines() if line.strip())
