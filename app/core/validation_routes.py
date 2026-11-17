"""Route prefixes the generated app mounts for its own modules. An entity whose `plural_path` equals the prefix
of an ACTIVE module would be mounted first (`/{item_id}`) and shadow that module's GET routes."""

from collections.abc import Callable

from app.core.spec_models import Spec
from app.core.validation_ai import ai_active
from app.core.validation_booking import booking_active
from app.core.validation_documents import documents_active as doc_templates_active
from app.core.validation_notifications import notifications_active
from app.core.validation_operations import (
    geo_active,
    location_active,
    matching_active,
    prediction_active,
)
from app.core.validation_packs import (
    invoicing_active,
    ledger_active,
    payouts_active,
    reconciliation_active,
)
from app.core.validation_payments import payments_active
from app.core.validation_providers import providers_active
from app.core.validation_realtime import metrics_active, realtime_active
from app.core.validation_runtime import runtime_config_active
from app.core.validation_storage import storage_active
from app.core.validation_webhooks import webhooks_active
from app.core.validation_workflows import workflows_active

MODULE_PREFIXES: dict[str, Callable[[Spec], bool]] = {
    "auth": lambda s: s.auth is not None and s.auth.enabled,
    "files": storage_active,
    "payments": payments_active,
    "documents": lambda s: bool(doc_templates_active(s)) or (s.packs is not None and s.packs.ai is not None and s.packs.ai.documents is not None),
    "ledger": ledger_active,
    "reconciliation": reconciliation_active,
    "invoices": invoicing_active,
    "payouts": payouts_active,
    "booking": booking_active,
    "ai": ai_active,
    "geo": geo_active,
    "location": location_active,
    "matching": matching_active,
    "prediction": prediction_active,
    "providers": providers_active,
    "webhooks": webhooks_active,
    "notifications": notifications_active,
    "workflows": workflows_active,
    "config": runtime_config_active,
    "metrics": metrics_active,
    "realtime": realtime_active,
}


def reserved_paths(spec: Spec) -> frozenset[str]:
    return frozenset(prefix for prefix, active in MODULE_PREFIXES.items() if active(spec))
