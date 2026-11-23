"""Dump the JSON Schemas of the AI pack settings forms (CP-6G) from the backend's Pydantic models (read-only).

Run from the repo root:  PYTHONPATH=. uv run python frontend/scripts/dump_form_schemas_ai.py
Writes frontend/src/forms/schemas/ai-{gateway,documents,knowledge,agents,evals}.json. The `x-ui` hints are the only
hand-written part. Note the `ai-` prefix: SpecDocuments (non-pack) is a different model from SpecAiDocuments.
No secret is a form field: SpecAiProvider.byo_key_env is the NAME of an environment variable, never a key.
"""

import json
from pathlib import Path

from app.core.spec_models import (
    SpecAiAction,
    SpecAiAgent,
    SpecAiAgentRoles,
    SpecAiAgents,
    SpecAiBudget,
    SpecAiDocField,
    SpecAiDocKind,
    SpecAiDocuments,
    SpecAiEvalCase,
    SpecAiEvals,
    SpecAiEvalSuite,
    SpecAiGateway,
    SpecAiKnowledge,
    SpecAiRoles,
)

OUT = Path(__file__).resolve().parent.parent / "src" / "forms" / "schemas"
CSV = {"widget": "csv"}


def prop(schema: dict, name: str) -> dict:
    return schema["properties"][name]


def hint(node: dict, **ui) -> None:
    node["x-ui"] = {**node.get("x-ui", {}), **ui}


def roles(schema: dict, *names: str) -> None:
    for n in names:
        hint(prop(schema, n), **CSV)


def with_defaults(model, extra: tuple = ()) -> dict:
    """The model's JSON schema, plus the `default` Pydantic leaves out for default_factory fields (so the form starts
    from the real defaults, e.g. read_roles ["admin"], not from empty = any signed-in user)."""
    schema = model.model_json_schema()
    nested = {m.__name__: m for m in extra}
    for node, cls in [
        (schema, model),
        *[(schema["$defs"][n], c) for n, c in nested.items() if n in schema.get("$defs", {})],
    ]:
        for fname, field in cls.model_fields.items():
            if field.default_factory is not None:
                v = field.get_default(call_default_factory=True)
                node["properties"][fname]["default"] = (
                    v.model_dump(mode="json") if hasattr(v, "model_dump") else v
                )
    return schema


# --- gateway ---
gateway = with_defaults(SpecAiGateway, (SpecAiBudget, SpecAiRoles))
hint(gateway, order=["region", "zero_retention", "providers", "stages", "budget", "roles"])
hint(prop(gateway, "providers"), itemLabel="Provider")
hint(prop(gateway, "stages"), itemLabel="Stage")
hint(prop(gateway, "region"), help="Where the AI data is handled (a label, for example eu).")
prov = gateway["$defs"]["SpecAiProvider"]
hint(prov, order=["name", "kind", "byo_key_env"])
hint(prov["properties"]["kind"], help="Only fake (deterministic, no network) exists for now.")
hint(
    prov["properties"]["byo_key_env"],
    help="The NAME of an environment variable that would hold your own key. Never type a key here.",
)
hint(
    gateway["$defs"]["SpecAiStage"],
    order=["name", "provider", "model", "max_output_tokens", "fallback_model"],
)
hint(gateway["$defs"]["SpecAiBudget"]["properties"]["period"], help="day or month.")
hint(
    gateway["$defs"]["SpecAiBudget"]["properties"]["limit_micro_usd"],
    help="Integer micro-USD (1 USD = 1,000,000). The price table is an estimate.",
)
hint(
    gateway["$defs"]["SpecAiBudget"]["properties"]["per_call_cap_micro_usd"],
    help="Integer micro-USD: the cap on one call's worst case.",
)
roles(gateway["$defs"]["SpecAiRoles"], "call_roles", "read_roles", "manage_roles")

# --- documents ---
documents = with_defaults(SpecAiDocuments, (SpecAiDocKind, SpecAiDocField))
hint(
    documents,
    order=[
        "stage",
        "kinds",
        "upload_roles",
        "review_roles",
        "read_roles",
        "review_below_bp",
        "max_text_chars",
        "allow_self_review",
    ],
)
roles(documents, "upload_roles", "review_roles", "read_roles")
hint(prop(documents, "kinds"), itemLabel="Document kind")
hint(
    prop(documents, "review_below_bp"),
    help="Confidence in basis points (10000 = 100%). A field below this goes to the review queue.",
)
hint(documents["$defs"]["SpecAiDocKind"]["properties"]["fields"], itemLabel="Field")

# --- knowledge ---
knowledge = with_defaults(SpecAiKnowledge)
hint(
    knowledge,
    order=["stage", "manage_roles", "read_roles", "chunk_chars", "max_sources", "max_text_chars"],
)
roles(knowledge, "manage_roles", "read_roles")

# --- agents ---
agents = with_defaults(SpecAiAgents, (SpecAiAction, SpecAiAgent, SpecAiAgentRoles))
hint(agents, order=["agents", "actions", "roles", "allow_self_approval"])
hint(
    prop(agents, "actions"),
    itemLabel="Action",
    help="The action registry: the only things an agent can ever do.",
)
hint(prop(agents, "agents"), itemLabel="Agent")
act = agents["$defs"]["SpecAiAction"]
hint(act, order=["name", "kind", "description", "risk", "max_autonomy", "entity", "fields"])
hint(act["properties"]["kind"], help="note or entity_create.")
hint(
    act["properties"]["risk"],
    help="low, medium or high. A high-risk action never runs without a human.",
)
hint(act["properties"]["max_autonomy"], help="suggest, draft or auto.")
hint(act["properties"]["entity"], help="The entity's table name (kind entity_create).")
hint(act["properties"]["fields"], **CSV)
agt = agents["$defs"]["SpecAiAgent"]
hint(agt, order=["name", "stage", "autonomy", "actions", "max_actions_per_run", "require_eval"])
hint(agt["properties"]["autonomy"], help="The agent's ceiling: suggest, draft or auto.")
hint(agt["properties"]["actions"], **CSV)
hint(
    agt["properties"]["require_eval"],
    help="An eval suite of this agent that must have passed before auto runs.",
)
roles(agents["$defs"]["SpecAiAgentRoles"], "run_roles", "approve_roles", "read_roles")

# --- evals ---
evals = with_defaults(SpecAiEvals, (SpecAiEvalSuite, SpecAiEvalCase))
hint(evals, order=["suites", "run_roles"])
roles(evals, "run_roles")
hint(prop(evals, "suites"), itemLabel="Suite")
hint(evals["$defs"]["SpecAiEvalSuite"], order=["name", "agent", "pass_bp", "cases"])
hint(
    evals["$defs"]["SpecAiEvalSuite"]["properties"]["pass_bp"],
    help="Pass mark in basis points (8000 = 80%).",
)
hint(evals["$defs"]["SpecAiEvalSuite"]["properties"]["cases"], itemLabel="Case")
case = evals["$defs"]["SpecAiEvalCase"]
hint(case, order=["name", "goal", "expect_actions", "forbid_actions"])
hint(case["properties"]["expect_actions"], **CSV)
hint(case["properties"]["forbid_actions"], **CSV)

for name, schema in (
    ("ai-gateway", gateway),
    ("ai-documents", documents),
    ("ai-knowledge", knowledge),
    ("ai-agents", agents),
    ("ai-evals", evals),
):
    (OUT / f"{name}.json").write_text(json.dumps(schema, indent=2, sort_keys=False) + "\n")
    print("wrote", name)
