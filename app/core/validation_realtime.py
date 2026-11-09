"""Validation for the `realtime` and `metrics_layer` sections (generated realtime stream and metrics).
Issues go through `add(path, code, message)`. Nothing here runs anything. Both blocks stand on role
permissions (rbac): the abac / pbac policies are not evaluated by the stream or the metrics endpoints,
so a spec that combines them is refused instead of quietly serving nothing."""

from collections.abc import Callable

from app.core.metrics import MetricError, parse_metric, validate_metric
from app.core.spec_models import Spec, SpecEntity

Add = Callable[[str, str, str], None]

RT_TABLES = ("rt_events", "rt_floor")
MAX_METRICS = 50


def realtime_active(spec: Spec) -> bool:
    return spec.realtime is not None and spec.realtime.enabled


def metrics_active(spec: Spec) -> bool:
    return spec.metrics_layer is not None and bool(spec.metrics_layer.definitions)


def _rbac(spec: Spec) -> bool:
    return spec.authorization is None or spec.authorization.model == "rbac"


def check_realtime(spec: Spec, add: Add) -> None:
    if not realtime_active(spec):
        return
    if not _rbac(spec):
        add("realtime", "needs_rbac", "realtime needs authorization.model rbac (abac / pbac policies are not streamed)")
    if not any("list" in e.options.operations for e in spec.entities):
        add("realtime", "no_listable_entity", "realtime needs at least one entity with a list operation")


def check_metrics_layer(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    block = spec.metrics_layer
    if block is None or not block.definitions:
        return
    if not _rbac(spec):
        add("metrics_layer", "needs_rbac", "metrics_layer needs authorization.model rbac (abac / pbac policies are not applied)")
    if len(block.definitions) > MAX_METRICS:
        add("metrics_layer.definitions", "too_many", f"at most {MAX_METRICS} metric definitions")
    seen: set[str] = set()
    for i, raw in enumerate(block.definitions):
        path = f"metrics_layer.definitions[{i}]"
        try:
            definition = parse_metric(raw)
            validate_metric(definition, entities.get(definition.entity))
        except MetricError as exc:
            add(path, "invalid_metric", str(exc))
            continue
        if definition.key in seen:
            add(f"{path}.key", "duplicate_key", f"metric key {definition.key!r} is used twice")
        seen.add(definition.key)
        if "list" not in entities[definition.entity].options.operations:
            add(f"{path}.entity", "no_list_operation", f"{definition.entity} has no list operation, so nobody may aggregate it")
