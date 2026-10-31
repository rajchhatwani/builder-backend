"""The `observability` feature: OpenTelemetry traces and metrics, log correlation, redaction.

Emitted only when the spec has an enabled `observability` block:

  app/core/telemetry.py                 setup, redacting span exporter, log/trace correlation
  tests/test_observability.py           spans, correlation, redaction, cardinality, kill switch
  docs/OBSERVABILITY.md                 what is collected, how to run it, how to size it
  deploy/observability/                 (local_stack) collector, Jaeger, Prometheus (overlay)
"""

from pathlib import Path

from app.core import observability as obs
from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, render_template
from app.core.spec_models import SpecObservability
from app.core.validation_observability import observability_active

_TEMPLATES = Path(__file__).parent / "templates"


def template_context(project: ProjectCtx, block: SpecObservability) -> dict[str, object]:
    uses_redis = (
        project.auth is not None
        and project.auth.provider == "builtin"
        and project.auth.token_store == "redis"
    )
    return {
        "project_name": project.name,
        "service_name": block.service_name or project.slug,
        "sample_ratio": block.sample_ratio,
        "metrics": block.metrics,
        "db_spans": block.db_spans,
        "exclude_paths": tuple(block.exclude_paths),
        "extra_redact_keys": tuple(sorted(set(block.extra_redact_keys))),
        "local_stack": block.local_stack,
        "expected_rps": block.expected_rps,
        "recommended_ratio": obs.recommended_sample_ratio(block.expected_rps),
        "span_budget": obs.SPAN_BUDGET_PER_SECOND,
        "redis": uses_redis,
        "collector_image": obs.COLLECTOR_IMAGE,
        "jaeger_image": obs.JAEGER_IMAGE,
        "prometheus_image": obs.PROMETHEUS_IMAGE,
    }


class ObservabilityModule:
    name = "observability"
    manifest = ModuleManifest(id="observability", version="1", depends_on=())

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        block = observability_active(project.spec)
        if block is None:
            return {}
        context = template_context(project, block)

        def render(template: str) -> str:
            return render_template(self._env, template, **context)

        files: FileTree = {
            "app/core/telemetry.py": render("app/core/telemetry.py.j2"),
            "tests/test_observability.py": render("tests/test_observability.py.j2"),
            "docs/OBSERVABILITY.md": render("docs/OBSERVABILITY.md.j2"),
        }
        if block.local_stack:
            files["deploy/observability/compose.yml"] = render("deploy/compose.yml.j2")
            files["deploy/observability/otel-collector.yaml"] = render(
                "deploy/otel-collector.yaml.j2"
            )
            files["deploy/observability/prometheus.yml"] = render("deploy/prometheus.yml.j2")
        return files
