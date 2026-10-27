"""Compare frontend/src/api/types.ts interfaces with the live OpenAPI schemas (property names only).

Run: PYTHONPATH=. BUILDER_ENVIRONMENT=local uv run python review/tests/types_drift.py
"""
import os
import re
import pathlib

os.environ.setdefault("BUILDER_ENVIRONMENT", "local")
from app.main import app  # noqa: E402

spec = app.openapi()
schemas = spec["components"]["schemas"]
ts = pathlib.Path("frontend/src/api/types.ts").read_text()

# interface blocks (brace matched, one level)
ifaces: dict[str, dict[str, bool]] = {}
for m in re.finditer(r"export interface (\w+)(?:<[^>]*>)?(?: extends [\w, <>]+)? \{", ts):
    name, i, depth = m.group(1), m.end(), 1
    while depth and i < len(ts):
        depth += {"{": 1, "}": -1}.get(ts[i], 0)
        i += 1
    body = ts[m.end(): i - 1]
    # only top-level fields (strip nested braces)
    flat, d = [], 0
    for ch in body:
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
        elif d == 0:
            flat.append(ch)
    fields = {}
    for fm in re.finditer(r"^\s*(?:readonly )?(\w+)(\?)?\s*:", "".join(flat), re.M):
        fields[fm.group(1)] = bool(fm.group(2))
    ifaces[name] = fields

ALIASES = {"Organization": "OrganizationRead", "OrgMember": "OrganizationMemberRead", "OrgInvitation": "InvitationRead",
           "OrgInvitationCreated": "InvitationCreated", "OrgPlan": "OrgPlanRead", "OrgPolicies": "OrgPoliciesRead",
           "OrgAuditEntry": "OrgAuditRead", "PlanInfo": "PlanRead", "Project": "ProjectRead", "Member": "MemberRead",
           "AuditEntry": "AuditRead", "SsoConfig": "SsoConfigRead", "SsoConfigWrite": "SsoConfigUpdate", "SsoDomain": "SsoDomainRead",
           "ScimConfig": "ScimConfigRead", "ScimToken": "ScimTokenRead", "LoginDiscovery": "LoginDiscoverRead",
           "UserAccount": "AccountRead", "AdminOrg": "AdminOrgRead", "AdminUser": "AdminUserRead", "AdminProject": "AdminProjectRead",
           "MfaStatus": "MfaStatusRead", "TotpSetup": "TotpSetupRead", "SsoCheck": "SsoCheckRead",
           "Entity": "EntityRead", "Field": "FieldRead", "Relation": "RelationRead", "ProjectToken": "ProjectTokenRead"}
def oa(name):
    cands = [name, name + "Read", ALIASES.get(name, name)]
    for c in list(cands):
        cands += [c + "-Output", c + "-Input"]
    for cand in cands:
        if cand in schemas:
            return schemas[cand]
    return None

matched = drift = 0
unmatched = []
for name, fields in sorted(ifaces.items()):
    s = oa(name)
    if s is None:
        unmatched.append(name)
        continue
    matched += 1
    props = s.get("properties", {})
    req = set(s.get("required", []))
    only_ts = sorted(set(fields) - set(props))
    only_oa = sorted(set(props) - set(fields))
    optional_mismatch = sorted(f for f in fields if f in props and fields[f] and f in req)
    if only_ts or only_oa or optional_mismatch:
        drift += 1
        print(f"{name}: ts-only={only_ts} openapi-only={only_oa} ts-optional-but-required-in-api={optional_mismatch}")
print(f"\n{len(ifaces)} TS interfaces, {matched} matched an OpenAPI schema by name, {drift} with drift")
print("no same-named schema (not compared):", unmatched)
