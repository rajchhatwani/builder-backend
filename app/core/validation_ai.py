"""Validation for `packs.ai` (Cycle 5, D33 LLM gateway; D34 documents and D35 knowledge are declared and checked here too).
Structure (unknown options, floats where an integer is required) is refused by the spec models (extra=forbid,
StrictInt); this module checks the values and the cross-section rules. Issues go through `add(path, code, message)`."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec, SpecAiDocuments, SpecAiGateway, SpecAiKnowledge

Add = Callable[[str, str, str], None]

AI_TABLES = ("ai_calls", "ai_budget_periods")
AI_DOCUMENT_TABLES = ("ai_documents", "ai_document_fields")
AI_KNOWLEDGE_TABLES = ("ai_knowledge_sources", "ai_knowledge_chunks")
AI_PROVIDER_KINDS = ("fake",)
# UNVERIFIED (owner): micro-USD per 1,000,000 tokens, (input, output). Fake models only; no real provider is priced here.
AI_PRICES: dict[str, tuple[int, int]] = {
    "fake-embed": (20_000, 0),
    "fake-large": (3_000_000, 15_000_000),
    "fake-small": (150_000, 600_000),
}
MAX_INT = 2**53 - 1
MAX_STAGES = 50
MAX_PROVIDERS = 10
MAX_OUTPUT_TOKENS = 100_000
_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
_STAGE = re.compile(r"[a-z][a-z0-9_.-]{0,39}")
_ENV = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_REGION = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def ai_active(spec: Spec) -> bool:
    return spec.packs is not None and spec.packs.ai is not None


def gateway_active(spec: Spec) -> bool:
    return ai_active(spec) and spec.packs.ai.gateway is not None  # type: ignore[union-attr]


def documents_active(spec: Spec) -> bool:
    return ai_active(spec) and spec.packs.ai.documents is not None  # type: ignore[union-attr]


def knowledge_active(spec: Spec) -> bool:
    return ai_active(spec) and spec.packs.ai.knowledge is not None  # type: ignore[union-attr]


def ai_tables(spec: Spec) -> tuple[str, ...]:
    """Gateway tables when the gateway is declared; the documents / knowledge tables only when those are declared."""
    if not gateway_active(spec):
        return ()
    out: tuple[str, ...] = AI_TABLES
    if documents_active(spec):
        out += AI_DOCUMENT_TABLES
    if knowledge_active(spec):
        out += AI_KNOWLEDGE_TABLES
    return out


def ceil_cost(tokens: int, price_per_mtok: int) -> int:
    """Integer micro-USD of `tokens` at `price_per_mtok` micro-USD per million tokens, rounded up."""
    return -(-(tokens * price_per_mtok) // 1_000_000)


def check_ai(spec: Spec, add: Add) -> None:
    if not ai_active(spec):
        return
    pack = spec.packs.ai  # type: ignore[union-attr]
    assert pack is not None
    p = "packs.ai"
    if pack.gateway is None and pack.documents is None and pack.knowledge is None:
        add(p, "empty_pack", "packs.ai declares no block (gateway, documents, knowledge)")
        return
    if spec.auth is None or not spec.auth.enabled:
        add(p, "needs_auth", "the ai pack needs auth.enabled: every route needs a signed-in caller")
    elif spec.authorization is not None and spec.authorization.model != "rbac":
        add(p, "needs_rbac", "the ai pack needs authorization.model rbac (it checks roles, not abac / pbac policies)")
    if pack.documents is not None and pack.gateway is not None and pack.gateway.zero_retention:
        add(
            "packs.ai.documents",
            "zero_retention_conflict",
            "documents store the document text; gateway.zero_retention promises that no text is stored: declare one of them, not both",
        )
    if (pack.documents is not None or pack.knowledge is not None) and pack.gateway is None:
        add(p, "needs_gateway", "documents and knowledge call the model gateway: declare packs.ai.gateway")
    known = {r.name for r in spec.auth.roles} if spec.auth is not None else set()

    def roles(path: str, values: list[str]) -> None:
        for role in values:
            if role not in known:
                add(path, "unknown_role", f"role {role!r} is not an auth role")

    stage_names: set[str] = set()
    gw = pack.gateway
    if gw is not None:
        stage_names = _check_gateway(spec, gw, add, roles)
    if pack.documents is not None:
        _check_documents(pack.documents, stage_names, add, roles)
    if pack.knowledge is not None:
        _check_knowledge(pack.knowledge, stage_names, add, roles)


def _check_gateway(spec: Spec, gw: SpecAiGateway, add: Add, roles: Callable[[str, list[str]], None]) -> set[str]:
    p = "packs.ai.gateway"
    roles(f"{p}.roles.call_roles", gw.roles.call_roles)
    roles(f"{p}.roles.read_roles", gw.roles.read_roles)
    roles(f"{p}.roles.manage_roles", gw.roles.manage_roles)
    if not gw.roles.manage_roles:
        add(f"{p}.roles.manage_roles", "empty", "manage_roles needs at least one role (an empty list would make nobody a manager)")
    if not _REGION.fullmatch(gw.region):
        add(f"{p}.region", "invalid_region", "a region id: lower case letters, digits and -")
    if not gw.providers:
        add(f"{p}.providers", "empty", "declare at least one provider")
    if len(gw.providers) > MAX_PROVIDERS:
        add(f"{p}.providers", "too_many", f"at most {MAX_PROVIDERS} providers")
    provider_names = [pr.name for pr in gw.providers]
    if len(set(provider_names)) != len(provider_names):
        add(f"{p}.providers", "duplicate", "a provider name is declared twice")
    for i, pr in enumerate(gw.providers):
        pp = f"{p}.providers[{i}]"
        if not _NAME.fullmatch(pr.name):
            add(f"{pp}.name", "invalid_identifier", "a provider name is lower case letters, digits and _")
        if pr.kind not in AI_PROVIDER_KINDS:
            add(f"{pp}.kind", "unsupported_provider", f"provider kind {pr.kind[:20]!r} is not available; only: {', '.join(AI_PROVIDER_KINDS)}")
        if pr.byo_key_env is not None and not _ENV.fullmatch(pr.byo_key_env):
            add(f"{pp}.byo_key_env", "invalid_env_name", "an environment variable name: upper case letters, digits and _")
    b = gw.budget
    if b.period not in ("day", "month"):
        add(f"{p}.budget.period", "invalid_period", "period is 'day' or 'month'")
    if not 1 <= b.limit_micro_usd <= MAX_INT:
        add(f"{p}.budget.limit_micro_usd", "out_of_range", "1 .. 2**53-1 micro-USD")
    if not 1 <= b.per_call_cap_micro_usd <= MAX_INT:
        add(f"{p}.budget.per_call_cap_micro_usd", "out_of_range", "1 .. 2**53-1 micro-USD")
    elif b.per_call_cap_micro_usd > b.limit_micro_usd:
        add(f"{p}.budget.per_call_cap_micro_usd", "cap_above_budget", "the per-call cap cannot exceed the budget of the period")
    if not gw.stages:
        add(f"{p}.stages", "empty", "declare at least one stage")
    if len(gw.stages) > MAX_STAGES:
        add(f"{p}.stages", "too_many", f"at most {MAX_STAGES} stages")
    names = [s.name for s in gw.stages]
    if len(set(names)) != len(names):
        add(f"{p}.stages", "duplicate", "a stage name is declared twice")
    for i, st in enumerate(gw.stages):
        sp = f"{p}.stages[{i}]"
        if not _STAGE.fullmatch(st.name):
            add(f"{sp}.name", "invalid_identifier", "a stage name is lower case letters, digits and _ . -")
        if st.provider not in provider_names:
            add(f"{sp}.provider", "unknown_provider", f"provider {st.provider[:40]!r} is not declared in providers")
        for field, model in (("model", st.model), ("fallback_model", st.fallback_model)):
            if model is not None and model not in AI_PRICES:
                add(f"{sp}.{field}", "unknown_model", f"model {model[:40]!r} has no price: known models are {', '.join(sorted(AI_PRICES))}")
        if st.fallback_model is not None and st.fallback_model == st.model:
            add(f"{sp}.fallback_model", "same_as_model", "the fallback model must differ from the model")
        if not 1 <= st.max_output_tokens <= MAX_OUTPUT_TOKENS:
            add(f"{sp}.max_output_tokens", "out_of_range", f"1 .. {MAX_OUTPUT_TOKENS}")
        elif 1 <= b.per_call_cap_micro_usd <= MAX_INT:
            dearest = max((AI_PRICES[m][1] for m in (st.model, st.fallback_model) if m in AI_PRICES), default=0)
            if ceil_cost(st.max_output_tokens, dearest) > b.per_call_cap_micro_usd:
                add(f"{sp}.max_output_tokens", "stage_above_cap", "the output alone can cost more than per_call_cap_micro_usd: no call could succeed")
    return set(names)


def _check_documents(doc: SpecAiDocuments, stages: set[str], add: Add, roles: Callable[[str, list[str]], None]) -> None:
    p = "packs.ai.documents"
    for field in ("upload_roles", "review_roles", "read_roles"):
        roles(f"{p}.{field}", getattr(doc, field))
    if not doc.review_roles:
        add(f"{p}.review_roles", "empty", "review_roles needs at least one role")
    if doc.stage not in stages and stages:
        add(f"{p}.stage", "unknown_stage", f"stage {doc.stage[:40]!r} is not a gateway stage")
    if not 0 <= doc.review_below_bp <= 10_000:
        add(f"{p}.review_below_bp", "out_of_range", "0 .. 10000 basis points")
    if not 1 <= doc.max_text_chars <= 2_000_000:
        add(f"{p}.max_text_chars", "out_of_range", "1 .. 2000000 characters")
    if not doc.kinds:
        add(f"{p}.kinds", "empty", "declare at least one document kind")
    kinds = [k.name for k in doc.kinds]
    if len(set(kinds)) != len(kinds):
        add(f"{p}.kinds", "duplicate", "a document kind is declared twice")
    for i, kind in enumerate(doc.kinds):
        kp = f"{p}.kinds[{i}]"
        if not _NAME.fullmatch(kind.name):
            add(f"{kp}.name", "invalid_identifier", "a kind name is lower case letters, digits and _")
        if not kind.fields:
            add(f"{kp}.fields", "empty", "a document kind needs at least one field")
        fields = [f.name for f in kind.fields]
        if len(set(fields)) != len(fields):
            add(f"{kp}.fields", "duplicate", "a field is declared twice")
        for j, f in enumerate(kind.fields):
            if not _NAME.fullmatch(f.name):
                add(f"{kp}.fields[{j}].name", "invalid_identifier", "a field name is lower case letters, digits and _")


def _check_knowledge(kn: SpecAiKnowledge, stages: set[str], add: Add, roles: Callable[[str, list[str]], None]) -> None:
    p = "packs.ai.knowledge"
    roles(f"{p}.manage_roles", kn.manage_roles)
    roles(f"{p}.read_roles", kn.read_roles)
    if not kn.manage_roles:
        add(f"{p}.manage_roles", "empty", "manage_roles needs at least one role")
    if kn.stage not in stages and stages:
        add(f"{p}.stage", "unknown_stage", f"stage {kn.stage[:40]!r} is not a gateway stage")
    if not 100 <= kn.chunk_chars <= 5000:
        add(f"{p}.chunk_chars", "out_of_range", "100 .. 5000 characters")
    if not 1 <= kn.max_sources <= 100_000:
        add(f"{p}.max_sources", "out_of_range", "1 .. 100000")
    if not 1 <= kn.max_text_chars <= 5_000_000:
        add(f"{p}.max_text_chars", "out_of_range", "1 .. 5000000 characters")
