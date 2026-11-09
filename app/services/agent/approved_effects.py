"""B-002: what an APPROVED Gate D / E request does.

The S! tools and the E tools only ask. When a human approved the request, the run loop calls
`execute` ONCE (the approval is consumed in the same transaction) and the action described by the
approval's payload runs server-side:

  D  remove_entity, remove_field, update_field (weakening), add_relation (cascade), change_tenancy_mode,
     weaken_access_rule: one typed operation appended to the run's spec DRAFT (the live spec still only
     changes through the final review). The operation is validated like every other draft op.
  E  fetch_docs: a guarded HTTPS GET (public hosts only, no redirects, size/time capped); the text comes
     back as untrusted data. apply_migration, create_pr, request_secret run through the adapters of
     external_adapters.py (local defaults, no outbound call; FX-4).

The caller has already verified the approval is approved, unexpired, bound to the current spec hash
and content hash, and that its payload still hashes to what was asked (`check_usable`, strict).
"""

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.spec_models import SpecPermission
from app.exceptions import AppError
from app.models.agent import AiApproval, AiRun
from app.services.agent.draft import add_draft_op, run_spec
from app.services.agent.tools._common import _detail_text
from sqlalchemy.ext.asyncio import AsyncSession

FETCH_MAX_BYTES = 200_000
FETCH_TIMEOUT = 10.0
FETCH_TOTAL_TIMEOUT = 20.0  # one deadline for the whole fetch
_TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml", "application/yaml")
NO_EXECUTOR: frozenset[str] = frozenset()  # FX-4: every E action has an executor now (external_adapters)


# -- D: spec draft operations -------------------------------------------------------------------


def _need(p: dict[str, Any], *keys: str) -> list[Any]:
    missing = [k for k in keys if k not in p]
    if missing:
        raise AppError("approval_payload_invalid", f"the approved request lacks {missing}", 422)
    return [p[k] for k in keys]


async def _d_op(session: AsyncSession, run: AiRun, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    kind = str(p.get("op_type"))
    if kind == "remove_entity":
        return "remove_entity", {"name": _need(p, "name")[0]}
    if kind == "remove_field":
        e, n = _need(p, "entity", "name")
        return "remove_field", {"entity": e, "name": n}
    if kind == "update_field":
        e, n, c = _need(p, "entity", "name", "changes")
        return "update_field", {"entity": e, "name": n, "changes": c}
    if kind == "add_relation":
        return "add_relation", {"relation": _need(p, "relation")[0]}
    if kind in ("change_tenancy_mode", "weaken_access_rule"):
        spec = (await run_spec(session, run.id, run.project_id)).model_copy(deep=True)
        if spec.auth is None:
            raise AppError("approval_not_applicable", "the project has no auth section to change", 422)
        if kind == "change_tenancy_mode":
            spec.auth.multi_tenant = _need(p, "mode")[0] == "multi"
        else:
            entity, role, action = _need(p, "entity", "role", "action")
            row = next((x for x in spec.auth.permissions if x.entity == entity and x.operation == action), None)
            if row is None:
                spec.auth.permissions.append(SpecPermission(entity=entity, operation=action, roles=[role]))
            elif role not in row.roles:
                row.roles.append(role)
        return "replace_spec", {"spec": spec.model_dump(mode="json")}
    raise AppError("approval_not_applicable", f"no executor for '{kind[:40]}'", 422)


# -- E: guarded fetch ---------------------------------------------------------------------------


def check_fetch_url(url: str) -> tuple[str, str, int]:
    """(host, path+query, port) of an https URL, or AppError. No credentials, no odd ports."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise AppError("fetch_refused", "only plain https URLs without credentials can be fetched", 422)
    try:
        port = parts.port or 443
    except ValueError as exc:
        raise AppError("fetch_refused", "the URL has an invalid port", 422) from exc
    if port != 443:
        raise AppError("fetch_refused", "only port 443 can be fetched", 422)
    path = parts.path or "/"
    return parts.hostname, path + (f"?{parts.query}" if parts.query else ""), port


async def resolve_public(host: str, port: int) -> str:
    """One public IP of the host. A host with ANY non-public address is refused (rebinding, split DNS)."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AppError("fetch_failed", "the host does not resolve", 502) from exc
    addrs = {str(i[4][0]) for i in infos}
    try:
        ok = bool(addrs) and all(_public_ip(a) for a in addrs)
    except ValueError as exc:
        raise AppError("fetch_refused", "the host is not a public address", 422) from exc
    if not ok:
        raise AppError("fetch_refused", "the host is not a public address", 422)
    return sorted(addrs)[0]


def _public_ip(raw: str) -> bool:
    """Globally routable, also after unwrapping IPv4 embedded in IPv6 (mapped, NAT64, 6to4, Teredo)."""
    ip = ipaddress.ip_address(raw.split("%", 1)[0])
    if not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded: list[ipaddress.IPv4Address] = []
        if ip.ipv4_mapped:
            embedded.append(ip.ipv4_mapped)
        if ip in ipaddress.ip_network("64:ff9b::/96"):
            embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip in ipaddress.ip_network("2002::/16"):  # 6to4
            embedded.append(ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF))
        if ip.teredo:
            embedded.extend(ip.teredo)
        if ip in ipaddress.ip_network("64:ff9b:1::/48"):  # local-use NAT64
            return False
        return all(e.is_global for e in embedded)
    return True


async def fetch_url(url: str) -> dict[str, Any]:
    """The whole fetch (DNS, connect, headers, body) shares ONE deadline: a trickling server cannot hold it."""
    try:
        return await asyncio.wait_for(_fetch_url(url), FETCH_TOTAL_TIMEOUT)
    except TimeoutError as exc:
        raise AppError("fetch_failed", "the fetch took too long", 504) from exc


async def _fetch_url(url: str) -> dict[str, Any]:
    host, target, port = check_fetch_url(url)
    ip = await resolve_public(host, port)
    shown = f"[{ip}]" if ":" in ip else ip
    # Connect to the address that was checked (no second DNS lookup); the name is kept for Host and TLS.
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=False, trust_env=False) as client:
        req = client.build_request(
            "GET", f"https://{shown}{target}", headers={"Host": host, "Accept": "text/*, application/json"},
            extensions={"sni_hostname": host},
        )
        try:
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            raise AppError("fetch_failed", f"the request failed: {type(exc).__name__}", 502) from exc
        try:
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if resp.is_redirect:
                return {"status": resp.status_code, "redirect": "not followed", "text": ""}
            if not ctype.startswith(_TEXT_TYPES):
                return {"status": resp.status_code, "content_type": ctype[:80], "text": "", "skipped": "not text"}
            chunks: list[bytes] = []
            total = 0
            async for part in resp.aiter_bytes():
                total += len(part)
                chunks.append(part[: max(FETCH_MAX_BYTES - (total - len(part)), 0)])
                if total >= FETCH_MAX_BYTES:
                    break
        finally:
            await resp.aclose()
    text = b"".join(chunks).decode("utf-8", errors="replace")
    return {"status": resp.status_code, "content_type": ctype[:80], "bytes": min(total, FETCH_MAX_BYTES),
            "truncated": total >= FETCH_MAX_BYTES, "text": text}  # fmt: skip


# -- entry --------------------------------------------------------------------------------------


async def execute(session: AsyncSession, run: AiRun, approval: AiApproval) -> dict[str, Any]:
    """Run the approved action. Never raises for an action that cannot run: the outcome says why."""
    payload = approval.payload or {}
    try:
        if approval.kind == "D":
            op_type = payload.get("op_type")
            if op_type == "request_dependency" or "package" in payload:
                return {"executed": False, "reason": "dependencies are approved in the dependency policy"}
            name, op = await _d_op(session, run, payload)
            seq = await add_draft_op(session, run.id, run.project_id, name, op, commit=False)
            return {"executed": True, "action": str(op_type), "draft_seq": seq}
        if approval.kind == "E":
            action = str(payload.get("action"))
            if action == "fetch_docs":
                got = await fetch_url(str(payload.get("url", "")))
                return {"executed": True, "action": action, **got}
            from app.services.agent.external_adapters import get_adapters

            ad = get_adapters()
            if action == "apply_migration":
                return {"executed": True, "action": action, **await ad.dev.apply_migration(session, run)}
            if action == "create_pr":
                return {"executed": True, "action": action,
                        **await ad.pull_requests.create(session, run, str(payload.get("title", "")))}  # fmt: skip
            if action == "request_secret":
                return {"executed": True, "action": action, **await ad.secrets.request(session, run, str(payload.get("name", "")))}
            if action in NO_EXECUTOR:
                return {"executed": False, "action": action, "reason": "this platform has no executor for it yet"}
            return {"executed": False, "action": action[:40], "reason": "unknown action"}
    except AppError as exc:
        detail = _detail_text(exc)  # the validation issues, so the agent can see what to repair
        return {"executed": False, "error": exc.code, "detail": f"{exc.message}: {detail}"[:500] if detail else exc.message[:300]}
    return {"executed": False, "reason": f"kind {approval.kind} has no action"}
