"""Approvals A-E of the builder agent (B3-5; architecture 6.5, DECISIONS CO-3).

An approval is a human decision bound to a spec hash and a commit, and it expires. The run loop
asks with `request`, a person answers with `decide`, and the loop may only continue past a gate
after `require_valid` returns. A stale, expired, denied or missing approval is never accepted.

Who may decide (hard-coded, no setting can lower it):
  A, B, C                         project editors (and owners)
  D, E                            the project OWNER
  any payload that concerns an AI-written hook or a hook effect (key `hook`, `hooks`, `effects`,
  `hook_effects`, at any depth up to 4)  the project OWNER   (CO-3: effects are owner-only)

Policy (`effective_policy`), B-001. Platform values are real Settings fields:
  ai_approval_ttl_hours             int,  default 24    lifetime of B-E approvals (clamped 1 min .. 7 days)
  ai_approval_ttl_plan_hours        int,  default 168   lifetime of kind A
  ai_approval_auto_plan_small_edit  bool, default False kind A with payload {"small_config_edit": true}
                                    and no risk flags is approved automatically (the ONLY relaxation)
  ai_approval_roles                 dict kind->role ("editor"|"owner"); may only RAISE the floor
  ai_approval_separation_of_duties  bool, default False the creator of a run may not decide its approvals
An org may store an override (`ai_org_settings.approval_policy`: ttl_hours, ttl_plan_hours, roles,
auto_plan_small_edit, separation_of_duties) that can only TIGHTEN: a shorter lifetime, a higher role,
auto-approval off, separation of duties on. A looser value is ignored.
Anything that tries to relax B-D (auto approval, a lower role, a longer lifetime than 7 days) is ignored.

Transaction rule: `request` and `decide` flush; the caller commits (the API does). The one exception
is the expiry transition in `decide`/`require_valid`, which commits itself so it survives the 409.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.spec_models import Spec, SpecRelation
from app.exceptions import AppError
from app.models.agent import AiApproval, AiRun
from app.models.ai_ledger import AiOrgSettings
from app.models.enums import MemberRole
from app.models.project import Project
from app.services.access_service import member_role
from app.services.agent.contract import ApprovalKind, ApprovalRequest

FLAG_ORDER = (
    "auth",
    "tenancy",
    "money",
    "public_endpoints",
    "data_deletion",
    "new_egress",
    "new_dependencies",
)
STATES = ("pending", "approved", "denied", "expired", "superseded")
MAX_PAYLOAD_BYTES = 200_000
MIN_TTL = timedelta(minutes=1)
MAX_TTL = timedelta(days=7)

# Hard floor: the lowest role that may decide each kind. Settings can only raise it.
_ROLE_FLOOR: dict[str, str] = {"A": "editor", "B": "editor", "C": "editor", "D": "owner", "E": "owner"}
_HOOK_KEYS = frozenset({"hook", "hooks", "effects", "hook_effects"})
_RUN_OVER = frozenset({"applied", "stopped", "failed", "cancelled"})


# -- risk flags ------------------------------------------------------------------------------
def _dump(obj: Any) -> Any:
    return obj.model_dump(mode="json") if obj is not None else None


def _public_ops(spec: Spec) -> set[tuple[str, str]]:
    """(entity, operation) pairs reachable without a grant: no auth at all, or auth with no
    permission row for the pair under the plain role model."""
    ops: set[tuple[str, str]] = set()
    auth = spec.auth
    open_all = auth is None or not auth.enabled
    granted = set()
    if not open_all and auth is not None:
        granted = {(p.entity, p.operation) for p in auth.permissions}
    model = spec.authorization.model if spec.authorization is not None else "rbac"
    for ent in spec.entities:
        for op in ent.options.operations:
            if open_all or (model == "rbac" and (ent.name, op) not in granted):
                ops.add((ent.name, op))
    return ops


def _egress(spec: Spec) -> set[str]:
    out: set[str] = set()
    if spec.auth is not None:
        if spec.auth.smtp is not None:
            out.add(f"smtp:{spec.auth.smtp.host}")
        if spec.auth.sms_provider:
            out.add(f"sms:{spec.auth.sms_provider}")
        if spec.auth.provider != "builtin":
            out.add(f"idp:{spec.auth.provider}")
        if spec.auth.keycloak is not None:
            out.update(f"idp:{p.alias}:{p.type}" for p in spec.auth.keycloak.identity_providers)
    if spec.payments is not None and spec.payments.enabled:
        out.add(f"payments:{spec.payments.provider}")
    if spec.storage is not None and spec.storage.enabled:
        out.add(f"storage:{spec.storage.backend}:{spec.storage.bucket}")
    if spec.webhooks is not None and spec.webhooks.enabled:
        out.add("webhooks:out")
    if spec.hook_effects is not None and spec.hook_effects.enabled:
        out.update(f"hook_host:{h}" for h in spec.hook_effects.webhook_hosts)
    for hook in spec.hooks:
        out.update(f"hook_effect:{hook.name}:{e}" for e in hook.effects)
    if spec.events is not None and spec.events.enabled and spec.events.adapter != "in_process":
        out.add(f"events:{spec.events.adapter}")
    return out


def _rel_key(r: SpecRelation) -> tuple[str, str, str, str, str]:
    return (r.kind, r.from_entity, r.to_entity, r.from_name, r.to_name)


def _deletion_risk(before: Spec, after: Spec) -> bool:
    b_ent = {e.name: e for e in before.entities}
    a_ent = {e.name: e for e in after.entities}
    for name, e in b_ent.items():
        n = a_ent.get(name)
        if n is None or n.table_name != e.table_name:
            return True
        if e.options.soft_delete and not n.options.soft_delete:
            return True
        b_f = {f.name: f for f in e.fields}
        a_f = {f.name: f for f in n.fields}
        for fname, f in b_f.items():
            nf = a_f.get(fname)
            if nf is None or nf.type != f.type:
                return True
            if f.max_length is not None and (nf.max_length or 0) < f.max_length:
                return True
    b_rel = {_rel_key(r): r for r in before.relations}
    a_rel = {_rel_key(r): r for r in after.relations}
    if set(b_rel) - set(a_rel):
        return True
    if any(a_rel[k].on_delete == "cascade" and b_rel[k].on_delete != "cascade" for k in b_rel if k in a_rel):
        return True
    if before.auth is not None and after.auth is not None:
        if before.auth.deletion_mode == "soft" and after.auth.deletion_mode != "soft":
            return True
    return False


def risk_flags(
    spec_before: Spec, spec_after: Spec, *, dependencies: Iterable[str] = ()
) -> list[str]:
    """Deterministic risk flags of a spec change (6.5). Pure; order follows FLAG_ORDER."""
    flags: set[str] = set()
    b_auth = _dump(spec_before.auth) or {}
    a_auth = _dump(spec_after.auth) or {}
    b_tenant, a_tenant = b_auth.pop("multi_tenant", None), a_auth.pop("multi_tenant", None)
    b_kc = (b_auth.get("keycloak") or {}).get("mode")
    a_kc = (a_auth.get("keycloak") or {}).get("mode")
    if b_auth != a_auth or _dump(spec_before.authorization) != _dump(spec_after.authorization):
        flags.add("auth")
    if bool(b_tenant) != bool(a_tenant) or b_kc != a_kc:
        flags.add("tenancy")
    if _dump(spec_before.payments) != _dump(spec_after.payments):
        flags.add("money")
    else:
        money = {"decimal", "money", "currency"}

        def money_fields(s: Spec) -> set[tuple[str, str, str]]:
            return {(e.name, f.name, f.type) for e in s.entities for f in e.fields if f.type in money}

        if money_fields(spec_before) != money_fields(spec_after):
            flags.add("money")
    if _public_ops(spec_after) - _public_ops(spec_before):
        flags.add("public_endpoints")
    if _deletion_risk(spec_before, spec_after):
        flags.add("data_deletion")
    if _egress(spec_after) - _egress(spec_before):
        flags.add("new_egress")
    if any(str(d).strip() for d in dependencies):
        flags.add("new_dependencies")
    return [f for f in FLAG_ORDER if f in flags]


# -- policy ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class ApprovalPolicy:
    ttl: dict[str, timedelta]
    min_role: dict[str, str]
    auto_plan_small_edit: bool
    separation_of_duties: bool = False


def _clamp(td: timedelta) -> timedelta:
    return max(MIN_TTL, min(MAX_TTL, td))


def effective_policy(settings: Settings, org: dict[str, Any] | None = None) -> ApprovalPolicy:
    """The policy actually enforced: hard-coded floor, then the platform Settings, then the org
    override. Each step can only tighten the one before (a looser value is ignored)."""
    hours = getattr(settings, "ai_approval_ttl_hours", 24)
    plan_hours = getattr(settings, "ai_approval_ttl_plan_hours", 168)
    ttl = {k: _clamp(timedelta(hours=_num(hours, 24))) for k in "BCDE"}
    ttl["A"] = _clamp(timedelta(hours=_num(plan_hours, 168)))
    roles = dict(_ROLE_FLOOR)
    override = getattr(settings, "ai_approval_roles", None)
    if isinstance(override, dict):
        for kind, role in override.items():
            if kind in roles and role == "owner":  # may only raise; "editor" or junk is ignored
                roles[kind] = "owner"
    auto = getattr(settings, "ai_approval_auto_plan_small_edit", False) is True
    sod = getattr(settings, "ai_approval_separation_of_duties", False) is True
    if isinstance(org, dict):
        if "ttl_hours" in org and _is_num(org["ttl_hours"]):
            cap = _clamp(timedelta(hours=float(org["ttl_hours"])))
            for k in "BCDE":
                ttl[k] = min(ttl[k], cap)
        if "ttl_plan_hours" in org and _is_num(org["ttl_plan_hours"]):
            ttl["A"] = min(ttl["A"], _clamp(timedelta(hours=float(org["ttl_plan_hours"]))))
        org_roles = org.get("roles")
        if isinstance(org_roles, dict):
            for kind, role in org_roles.items():
                if kind in roles and role == "owner":
                    roles[kind] = "owner"
        if org.get("auto_plan_small_edit") is False:
            auto = False  # an org may switch auto-approval off, never on
        if org.get("separation_of_duties") is True:
            sod = True  # an org may switch it on, never off
    return ApprovalPolicy(ttl=ttl, min_role=roles, auto_plan_small_edit=auto, separation_of_duties=sod)


def _is_num(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and value == value


def payload_digest(payload: dict[str, Any]) -> str:
    """sha256 of the canonical payload: what an approval is bound to besides spec hash and commit."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _num(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value != value:
        return default
    return float(value)


def _mentions_hook(obj: Any, depth: int = 0) -> bool:
    if depth > 4:
        return True  # too deep to inspect: treat as sensitive
    if isinstance(obj, dict):
        return any(k in _HOOK_KEYS or _mentions_hook(v, depth + 1) for k, v in obj.items())
    if isinstance(obj, list | tuple):
        return any(_mentions_hook(v, depth + 1) for v in obj)
    return False


_OWNER_EXTEND_KINDS = frozenset({"hook", "zone", "dependency"})


def requires_owner(kind: str, payload: dict[str, Any], policy: ApprovalPolicy | None = None) -> bool:
    floor = (policy.min_role if policy else _ROLE_FLOOR).get(kind, "owner")
    ext = payload.get("extend")
    # A plan extension that grants hooks, custom-zone paths or dependencies is an owner decision
    # (the kind is a VALUE, so _mentions_hook cannot see it); so is a plan that lists any of them.
    items = payload.get("extend_items")
    listed = [e for e in (items if isinstance(items, list) else []) if isinstance(e, dict)]
    grants = any(e.get("kind") in _OWNER_EXTEND_KINDS for e in [*([ext] if isinstance(ext, dict) else []), *listed])
    plan = payload.get("plan")
    plan_grants = isinstance(plan, dict) and any(plan.get(k) for k in ("hooks", "zones", "dependencies"))
    return floor == "owner" or _mentions_hook(payload) or grants or plan_grants


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _err(code: str, message: str, status: int = 409) -> AppError:
    return AppError(code, message, status)


class ApprovalService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.policy = effective_policy(settings)

    @classmethod
    async def for_project(
        cls, session: AsyncSession, settings: Settings, project_id: uuid.UUID
    ) -> "ApprovalService":
        """The service with the org override of the project's organisation applied (B-001)."""
        svc = cls(session, settings)
        raw = (
            await session.execute(
                select(AiOrgSettings.approval_policy)
                .join(Project, Project.organization_id == AiOrgSettings.organization_id)
                .where(Project.id == project_id)
            )
        ).scalar_one_or_none()
        svc.policy = effective_policy(settings, raw if isinstance(raw, dict) else None)
        return svc

    # -- ask ---------------------------------------------------------------------------------
    async def request(
        self,
        run: AiRun,
        req: ApprovalRequest,
        *,
        spec_hash: str,
        commit: str | None,
        spec_before: Spec | None = None,
        spec_after: Spec | None = None,
    ) -> AiApproval:
        kind = ApprovalKind(req.kind).value
        payload = dict(req.payload)
        if len(json.dumps(payload, default=str)) > MAX_PAYLOAD_BYTES:
            raise AppError("approval_payload_too_large", "approval payload is too large", 413)
        deps = payload.get("dependencies") or payload.get("dependency") or []
        deps = [deps] if isinstance(deps, str) else list(deps) if isinstance(deps, list | tuple) else []
        flags: list[str] = []
        if spec_before is not None and spec_after is not None:
            flags = risk_flags(spec_before, spec_after, dependencies=deps)
        elif deps:
            flags = ["new_dependencies"]
        now = _utcnow()
        await self.session.execute(
            update(AiApproval)
            .where(
                AiApproval.run_id == run.id,
                AiApproval.kind == kind,
                AiApproval.state == "pending",
            )
            .values(state="superseded")
        )
        row = AiApproval(
            id=uuid.uuid4(),
            run_id=run.id,
            project_id=run.project_id,
            kind=kind,
            subject=req.subject[:300],
            payload=payload,
            risk_flags=flags,
            state="pending",
            bound_spec_hash=spec_hash,
            bound_commit=commit,
            payload_hash=payload_digest(payload),
            expires_at=now + self.policy.ttl[kind],
            created_at=now,
        )
        if (
            kind == "A"
            and self.policy.auto_plan_small_edit
            and payload.get("small_config_edit") is True
            and not flags
            and not _mentions_hook(payload)
        ):
            row.state, row.decided_at, row.decision_note = "approved", now, "auto-approved by org policy"
        self.session.add(row)
        await self.session.flush()
        return row

    # -- answer ------------------------------------------------------------------------------
    async def _role_ok(self, project_id: uuid.UUID, user_id: uuid.UUID, row: AiApproval) -> bool:
        role = await member_role(self.session, user_id, project_id)
        if role == MemberRole.owner:
            return True
        if requires_owner(row.kind, row.payload, self.policy):
            return False
        return role == MemberRole.editor

    async def get(self, project_id: uuid.UUID, approval_id: uuid.UUID) -> AiApproval:
        row = await self.session.get(AiApproval, approval_id)
        if row is None or row.project_id != project_id:
            raise _err("not_found", "approval not found", 404)
        return row

    async def decide(
        self,
        project_id: uuid.UUID,
        approval_id: uuid.UUID,
        user_id: uuid.UUID,
        approve: bool,
        note: str | None = None,
        plan: Mapping[Any, list[str]] | None = None,
        expected_payload_hash: str | None = None,
        expected_spec_hash: str | None = None,
    ) -> AiApproval:
        row = await self.get(project_id, approval_id)
        # ND-4: authorize first, so a caller who may not decide learns nothing about the binding.
        if not await self._role_ok(project_id, user_id, row):
            raise _err("approval_forbidden", "your role may not decide this approval", 403)
        # S3-004/S3-005: the decision is bound to what the reviewer saw. Approving without saying
        # which payload was reviewed is refused; a mismatch decides nothing (re-checked in the
        # atomic UPDATE below, so a payload changed between this read and the write also loses).
        if approve and row.state == "pending" and row.payload_hash and not expected_payload_hash:
            raise _err("payload_hash_required", "approving needs expected_payload_hash: the hash of the request you reviewed", 422)
        if row.state == "pending" and (
            (expected_payload_hash and row.payload_hash and expected_payload_hash != row.payload_hash)
            or (expected_spec_hash and expected_spec_hash != row.bound_spec_hash)
        ):
            raise _err("approval_changed", "this request changed since you opened it: review it again", 409)
        run = await self.session.get(AiRun, row.run_id)
        if run is not None and run.state in _RUN_OVER:  # S1-011: nothing is decided for a finished run
            raise _err("run_finished", f"the run is already {run.state}; its approvals can no longer be decided")
        if self.policy.separation_of_duties and run is not None and run.created_by == user_id:
            raise _err(
                "separation_of_duties",
                "this organisation requires someone other than the run's creator to decide its approvals",
                403,
            )
        new_payload: dict[str, Any] | None = None
        if plan is not None:
            if row.kind != "A" or not approve:
                raise _err("plan_edit_not_allowed", "only an approved plan (Gate A) can carry an edited plan", 422)
            from app.services.agent.run_service import (
                clean_plan,  # lazy: run_service imports this module
            )

            cleaned = clean_plan(plan)
            if not cleaned:
                raise _err("plan_empty", "the edited plan is empty: nothing could be built from it", 422)
            old = row.payload or {}
            new_payload = {
                **old,
                "plan": cleaned,
                "edited_from": old.get("plan"),
                "edited_by": str(user_id),
            }
            probe = AiApproval(**{c.name: getattr(row, c.name) for c in AiApproval.__table__.columns})
            probe.payload = new_payload
            if not await self._role_ok(project_id, user_id, probe):
                raise _err("approval_forbidden", "your role may not approve a plan that adds hooks or dependencies", 403)
        now = _utcnow()
        if row.state == "pending" and row.expires_at <= now:
            await self.session.execute(
                update(AiApproval)
                .where(AiApproval.id == row.id, AiApproval.state == "pending")
                .values(state="expired")
            )
            await self.session.commit()
            raise _err("approval_expired", "this approval has expired")
        guards = [AiApproval.id == row.id, AiApproval.state == "pending", AiApproval.expires_at > now]
        if expected_payload_hash and row.payload_hash:
            guards.append(AiApproval.payload_hash == expected_payload_hash)
        if expected_spec_hash:
            guards.append(AiApproval.bound_spec_hash == expected_spec_hash)
        result = await self.session.execute(
            update(AiApproval)
            .where(*guards)
            .values(
                state="approved" if approve else "denied",
                decided_by=user_id,
                decided_at=now,
                decision_note=note[:500] if note else None,
                **(
                    {"payload": new_payload, "payload_hash": payload_digest(new_payload)}
                    if new_payload is not None
                    else {}
                ),
            )
            .returning(AiApproval.id)
        )
        if result.first() is None:
            await self.session.refresh(row)
            if row.state == "expired":
                raise _err("approval_expired", "this approval has expired")
            if row.state == "pending":
                raise _err("approval_changed", "this request changed since you opened it: review it again", 409)
            raise _err("approval_already_decided", f"this approval is already {row.state}")
        await self.session.refresh(row)
        return row

    # -- the exit test: stale approvals are never accepted -----------------------------------
    async def require_valid(
        self, run_id: uuid.UUID, kind: ApprovalKind | str, *, spec_hash: str, commit: str | None
    ) -> AiApproval:
        k = ApprovalKind(kind).value
        row = (
            await self.session.execute(
                select(AiApproval)
                .where(
                    AiApproval.run_id == run_id,
                    AiApproval.kind == k,
                    AiApproval.state != "superseded",
                )
                .order_by(AiApproval.created_at.desc(), AiApproval.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None or row.state == "pending" and row.expires_at > _utcnow():
            raise _err("approval_missing", f"no approved {k} approval for this run")
        self.check_usable(row, spec_hash=spec_hash, commit=commit)
        return row

    @staticmethod
    def check_usable(
        row: AiApproval, *, spec_hash: str, commit: str | None, strict_payload: bool = False
    ) -> None:
        """Raise unless THIS row is approved, unexpired, still bound to the given spec hash and commit,
        and its payload is the one that was asked (S1-004). `strict_payload`: a row without a payload
        hash is refused too (used before an approved action is executed)."""
        k = row.kind
        if row.state == "pending" and row.expires_at > _utcnow():
            raise _err("approval_missing", f"no approved {k} approval for this run")
        if row.state == "denied":
            raise _err("approval_denied", f"the {k} approval was denied")
        if row.state == "expired" or row.expires_at <= _utcnow():
            raise _err("approval_expired", f"the {k} approval has expired")
        if row.state != "approved":
            raise _err("approval_missing", f"no approved {k} approval for this run")
        if row.bound_spec_hash != spec_hash or row.bound_commit != (commit or None):
            raise _err(
                "approval_stale",
                f"the {k} approval was given for a different spec or commit; ask again",
            )
        if row.payload_hash is None:
            if strict_payload:
                raise _err("approval_unbound", f"the {k} approval carries no payload hash; ask again")
        elif row.payload_hash != payload_digest(row.payload or {}):
            raise _err("approval_payload_changed", f"the {k} approval no longer matches what was approved; ask again")

    # -- read --------------------------------------------------------------------------------
    @staticmethod
    def effective_state(row: AiApproval) -> str:
        if row.state == "pending" and row.expires_at <= _utcnow():
            return "expired"
        return row.state

    async def list(
        self,
        project_id: uuid.UUID,
        *,
        state: str | None = None,
        run_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[AiApproval]:
        if state is not None and state not in STATES:
            raise AppError("bad_request", "unknown approval state", 422)
        q = select(AiApproval).where(AiApproval.project_id == project_id)
        if run_id is not None:
            q = q.where(AiApproval.run_id == run_id)
        now = _utcnow()
        if state == "pending":
            q = q.where(AiApproval.state == "pending", AiApproval.expires_at > now)
        elif state == "expired":
            q = q.where(
                (AiApproval.state == "expired")
                | ((AiApproval.state == "pending") & (AiApproval.expires_at <= now))
            )
        elif state is not None:
            q = q.where(AiApproval.state == state)
        q = q.order_by(AiApproval.created_at.desc(), AiApproval.id.desc()).limit(max(1, min(limit, 200)))
        return list((await self.session.execute(q)).scalars())
