"""SCIM 2.0 wire format (RFC 7643 schemas, RFC 7644 protocol); no database, no web framework.

Only what provisioning clients use: `eq` filters on the attributes IdPs look people up by, PATCH
`add` / `replace` / `remove` (with and without a path), and the discovery documents. The parsers
are lenient where the big IdPs differ from the RFC (Entra ID capitalises ops and sends booleans as
strings; Okta sends a path-less `replace` with a value object) and strict about everything else:
unknown filters, operators and read-only attributes are a 400, never silently ignored.
"""

import re
from dataclasses import dataclass, field
from typing import Any

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
ENTERPRISE_USER_SCHEMA = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
SPC_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
RESOURCE_TYPE_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"
MEDIA_TYPE = "application/scim+json"

DEFAULT_PAGE = 100
MAX_PAGE = 200
MAX_OPERATIONS = 100
MAX_MEMBERS = 1000

# Lower-cased attribute name in a filter -> the canonical key the service filters on.
USER_FILTER_ATTRS = {
    "username": "username",
    "externalid": "externalid",
    "id": "id",
    "emails.value": "emails.value",
    'emails[type eq "work"].value': "emails.value",
}
GROUP_FILTER_ATTRS = {"displayname": "displayname", "externalid": "externalid", "id": "id"}

_FILTER_RE = re.compile(r'^\s*(?P<attr>\S.*?)\s+eq\s+"(?P<value>(?:[^"\\]|\\.)*)"\s*$', re.I)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MEMBER_FILTER_RE = re.compile(r'^members\[\s*value\s+eq\s+"(?P<id>[^"]+)"\s*\]$', re.I)
_WORK_EMAIL_PATHS = {'emails[type eq "work"].value', "emails.value", "emails"}


class ScimError(Exception):
    """A SCIM error response (RFC 7644 §3.12). `scim_type` is the RFC's keyword, if any."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def body(self) -> dict[str, object]:
        out: dict[str, object] = {"schemas": [ERROR_SCHEMA], "status": str(self.status)}
        if self.scim_type:
            out["scimType"] = self.scim_type
        out["detail"] = self.detail
        return out


def invalid(detail: str) -> ScimError:
    return ScimError(400, detail, "invalidValue")


# -- small parsers -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Filter:
    attr: str  # canonical, lower-case
    value: str


def parse_filter(text: str, allowed: dict[str, str]) -> Filter:
    match = _FILTER_RE.match(text or "")
    if not match:
        raise ScimError(
            400, 'only filters of the form `attribute eq "value"` are supported', "invalidFilter"
        )
    attr = match.group("attr").lower()
    canonical = allowed.get(attr) or allowed.get(match.group("attr"))
    if canonical is None:
        # `emails[type eq "work"].value` keeps its inner quotes; compare it case-insensitively.
        canonical = {k.lower(): v for k, v in allowed.items()}.get(attr)
    if canonical is None:
        raise ScimError(
            400, f"filtering on '{match.group('attr')}' is not supported", "invalidFilter"
        )
    value = re.sub(r"\\(.)", r"\1", match.group("value"))
    return Filter(canonical, value)


def as_bool(raw: object, name: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    raise invalid(f"'{name}' must be a boolean")


def _text(raw: object, name: str, limit: int) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise invalid(f"'{name}' must be a string")
    raw = raw.strip()
    if len(raw) > limit:
        raise invalid(f"'{name}' is longer than {limit} characters")
    return raw or None


def paging(start_index: str | None, count: str | None) -> tuple[int, int]:
    """RFC 7644 §3.4.2.4: 1-based startIndex (below 1 means 1), count >= 0 (capped)."""
    try:
        start = int(start_index) if start_index not in (None, "") else 1
        size = int(count) if count not in (None, "") else DEFAULT_PAGE
    except ValueError as exc:
        raise invalid("startIndex and count must be integers") from exc
    return max(start, 1), min(max(size, 0), MAX_PAGE)


# -- users -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UserInput:
    user_name: str
    email: str  # lower-cased; the Builder account's address
    external_id: str | None
    given_name: str | None
    family_name: str | None
    display_name: str | None
    active: bool


def _pick_email(emails: object) -> str | None:
    if emails is None:
        return None
    if not isinstance(emails, list):
        raise invalid("'emails' must be a list")
    entries = [e for e in emails if isinstance(e, dict) and isinstance(e.get("value"), str)]

    def rank(e: dict[str, Any]) -> tuple[int, int]:
        primary = e.get("primary") in (True, "true", "True")
        return (0 if primary else 1, 0 if e.get("type") == "work" else 1)

    entries.sort(key=rank)
    return entries[0]["value"] if entries else None


def parse_user(body: object) -> UserInput:
    """A full User body (POST / PUT, or the result of a PATCH). Unknown attributes are ignored;
    `password` is never read: these accounts sign in through the org's SSO."""
    if not isinstance(body, dict):
        raise invalid("the body must be a JSON object")
    user_name = _text(body.get("userName"), "userName", 254)
    if not user_name:
        raise invalid("'userName' is required")
    raw_name = body.get("name")
    name: dict[str, Any] = raw_name if isinstance(raw_name, dict) else {}
    email = user_name if "@" in user_name else _pick_email(body.get("emails"))
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise invalid("the user needs an e-mail address (as userName or a work e-mail)")
    active = as_bool(body["active"], "active") if body.get("active") is not None else True
    return UserInput(
        user_name=user_name,
        email=email,
        external_id=_text(body.get("externalId"), "externalId", 255),
        given_name=_text(name.get("givenName"), "name.givenName", 100),
        family_name=_text(name.get("familyName"), "name.familyName", 100),
        display_name=_text(body.get("displayName"), "displayName", 200),
        active=active,
    )


def user_patch_base(
    *,
    user_name: str,
    external_id: str | None,
    given_name: str | None,
    family_name: str | None,
    display_name: str | None,
    email: str,
    active: bool,
) -> dict[str, Any]:
    """The mutable part of a stored user, in the shape PATCH paths address."""
    return {
        "userName": user_name,
        "externalId": external_id,
        "name": {"givenName": given_name, "familyName": family_name},
        "displayName": display_name,
        "emails": [{"value": email, "type": "work", "primary": True}],
        "active": active,
    }


def _operations(body: object) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise invalid("the body must be a JSON object")
    ops = body.get("Operations")
    if not isinstance(ops, list) or not ops or len(ops) > MAX_OPERATIONS:
        raise invalid("'Operations' must be a non-empty list")
    out = []
    for op in ops:
        if not isinstance(op, dict):
            raise invalid("each operation must be an object")
        kind = str(op.get("op", "")).lower()
        if kind not in ("add", "replace", "remove"):
            raise invalid(f"unsupported operation '{op.get('op')}'")
        out.append({**op, "op": kind})
    return out


_READ_ONLY = {"id", "meta", "schemas", "groups"}


def _set_user_attr(doc: dict[str, Any], path: str, value: Any, *, remove: bool) -> None:
    lowered = path.lower()
    if lowered.startswith(ENTERPRISE_USER_SCHEMA.lower()) or lowered.startswith("urn:"):
        return  # extension attributes (department, manager, ...) are not stored
    if lowered in _READ_ONLY or lowered.split(".", 1)[0] in _READ_ONLY:
        raise ScimError(400, f"'{path}' is read-only", "mutability")
    if lowered in {p.lower() for p in _WORK_EMAIL_PATHS}:
        if remove:
            raise ScimError(400, "the e-mail address can't be removed", "mutability")
        email = _pick_email(value) if isinstance(value, list) else value
        if not isinstance(email, str):
            raise invalid("the e-mail must be a string")
        doc["emails"] = [{"value": email, "type": "work", "primary": True}]
        return
    if lowered in ("name.givenname", "name.familyname"):
        key = "givenName" if lowered.endswith("givenname") else "familyName"
        doc["name"][key] = None if remove else value
        return
    if lowered == "name":
        if remove:
            doc["name"] = {"givenName": None, "familyName": None}
        elif isinstance(value, dict):
            doc["name"].update({k: value[k] for k in ("givenName", "familyName") if k in value})
        return
    canonical = {
        "username": "userName",
        "externalid": "externalId",
        "displayname": "displayName",
        "active": "active",
    }.get(lowered)
    if canonical is None:
        return  # an attribute we don't keep (title, locale, phoneNumbers, ...)
    if remove and canonical in ("userName", "active"):
        raise ScimError(400, f"'{path}' can't be removed", "mutability")
    doc[canonical] = None if remove else value


def apply_user_patch(current: dict[str, Any], body: object) -> dict[str, Any]:
    """Apply a PatchOp to `user_patch_base(...)`; feed the result to `parse_user`."""
    doc: dict[str, Any] = {
        **current,
        "name": dict(current.get("name") or {}),
        "emails": list(current.get("emails") or []),
    }
    for op in _operations(body):
        path = op.get("path")
        if path is not None and not isinstance(path, str):
            raise invalid("'path' must be a string")
        if path:
            if op["op"] != "remove" and "value" not in op:
                raise invalid("the operation needs a 'value'")
            _set_user_attr(doc, path, op.get("value"), remove=op["op"] == "remove")
            continue
        if op["op"] == "remove":
            raise ScimError(400, "'remove' needs a path", "noTarget")
        value = op.get("value")
        if not isinstance(value, dict):
            raise invalid("an operation without a path needs an object 'value'")
        for key, item in value.items():
            if key.lower() in ("id", "meta", "schemas"):
                continue  # Okta echoes these back; harmless
            _set_user_attr(doc, key, item, remove=False)
    return doc


def user_resource(
    *,
    base_url: str,
    id: str,
    user_name: str,
    email: str,
    external_id: str | None,
    given_name: str | None,
    family_name: str | None,
    display_name: str | None,
    active: bool,
    groups: list[tuple[str, str]],
    created: str,
    last_modified: str,
) -> dict[str, object]:
    name: dict[str, str] = {}
    if given_name:
        name["givenName"] = given_name
    if family_name:
        name["familyName"] = family_name
    formatted = " ".join(x for x in (given_name, family_name) if x)
    if formatted:
        name["formatted"] = formatted
    out: dict[str, object] = {"schemas": [USER_SCHEMA], "id": id, "userName": user_name}
    if external_id:
        out["externalId"] = external_id
    out["name"] = name
    out["displayName"] = display_name or formatted or user_name
    out["emails"] = [{"value": email, "type": "work", "primary": True}]
    out["active"] = active
    out["groups"] = [
        {"value": gid, "display": gname, "$ref": f"{base_url}/Groups/{gid}"}
        for gid, gname in groups
    ]
    out["meta"] = {
        "resourceType": "User",
        "created": created,
        "lastModified": last_modified,
        "location": f"{base_url}/Users/{id}",
    }
    return out


# -- groups ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupInput:
    display_name: str
    external_id: str | None
    member_ids: list[str]


def _member_ids(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or len(raw) > MAX_MEMBERS:
        raise invalid("'members' must be a list")
    ids = []
    for m in raw:
        if not isinstance(m, dict) or not isinstance(m.get("value"), str):
            raise invalid("each member needs a 'value'")
        ids.append(m["value"])
    return ids


def parse_group(body: object) -> GroupInput:
    if not isinstance(body, dict):
        raise invalid("the body must be a JSON object")
    display_name = _text(body.get("displayName"), "displayName", 255)
    if not display_name:
        raise invalid("'displayName' is required")
    return GroupInput(
        display_name=display_name,
        external_id=_text(body.get("externalId"), "externalId", 255),
        member_ids=_member_ids(body.get("members")),
    )


@dataclass
class GroupPatch:
    display_name: str | None = None
    external_id: str | None = None
    external_id_set: bool = False
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    replace: list[str] | None = None  # the full member list, when replaced


def parse_group_patch(body: object) -> GroupPatch:
    out = GroupPatch()

    def apply(path: str, value: Any, kind: str) -> None:
        lowered = path.lower()
        member = _MEMBER_FILTER_RE.match(path)
        if member:
            if kind != "remove":
                raise invalid("a member filter can only be removed")
            out.remove.append(member.group("id"))
        elif lowered == "members":
            if kind == "add":
                out.add.extend(_member_ids(value))
            elif kind == "remove":
                if value is None:
                    out.replace, out.add, out.remove = [], [], []
                else:
                    out.remove.extend(_member_ids(value))
            else:
                out.replace, out.add, out.remove = _member_ids(value), [], []
        elif lowered == "displayname":
            if kind == "remove":
                raise ScimError(400, "'displayName' can't be removed", "mutability")
            name = _text(value, "displayName", 255)
            if not name:
                raise invalid("'displayName' can't be empty")
            out.display_name = name
        elif lowered == "externalid":
            out.external_id = None if kind == "remove" else _text(value, "externalId", 255)
            out.external_id_set = True
        elif lowered in ("id", "meta", "schemas"):
            if kind != "replace" or path == "id":
                raise ScimError(400, f"'{path}' is read-only", "mutability")
        elif lowered.startswith("urn:"):
            return
        else:
            raise ScimError(400, f"unknown attribute '{path}'", "invalidPath")

    for op in _operations(body):
        path = op.get("path")
        if path:
            if not isinstance(path, str):
                raise invalid("'path' must be a string")
            if op["op"] != "remove" and "value" not in op:
                raise invalid("the operation needs a 'value'")
            apply(path, op.get("value"), op["op"])
            continue
        if op["op"] == "remove":
            raise ScimError(400, "'remove' needs a path", "noTarget")
        value = op.get("value")
        if not isinstance(value, dict):
            raise invalid("an operation without a path needs an object 'value'")
        for key, item in value.items():
            if key.lower() in ("id", "meta", "schemas"):
                continue
            apply(key, item, op["op"])
    return out


def group_resource(
    *,
    base_url: str,
    id: str,
    display_name: str,
    external_id: str | None,
    members: list[tuple[str, str]] | None,
    created: str,
    last_modified: str,
) -> dict[str, object]:
    out: dict[str, object] = {"schemas": [GROUP_SCHEMA], "id": id, "displayName": display_name}
    if external_id:
        out["externalId"] = external_id
    if members is not None:
        out["members"] = [
            {"value": uid, "display": name, "$ref": f"{base_url}/Users/{uid}"}
            for uid, name in members
        ]
    out["meta"] = {
        "resourceType": "Group",
        "created": created,
        "lastModified": last_modified,
        "location": f"{base_url}/Groups/{id}",
    }
    return out


# -- lists and discovery -----------------------------------------------------------------------


def list_response(
    resources: list[dict[str, object]], *, total: int, start_index: int
) -> dict[str, object]:
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def service_provider_config(base_url: str) -> dict[str, object]:
    return {
        "schemas": [SPC_SCHEMA],
        "documentationUri": None,
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": MAX_PAGE},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer token",
                "description": "The SCIM token from the organization's SSO & SCIM settings",
                "primary": True,
            }
        ],
        "meta": {
            "resourceType": "ServiceProviderConfig",
            "location": f"{base_url}/ServiceProviderConfig",
        },
    }


def resource_types(base_url: str) -> list[dict[str, object]]:
    return [
        {
            "schemas": [RESOURCE_TYPE_SCHEMA],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": USER_SCHEMA,
            "schemaExtensions": [],
            "meta": {"resourceType": "ResourceType", "location": f"{base_url}/ResourceTypes/User"},
        },
        {
            "schemas": [RESOURCE_TYPE_SCHEMA],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": GROUP_SCHEMA,
            "schemaExtensions": [],
            "meta": {"resourceType": "ResourceType", "location": f"{base_url}/ResourceTypes/Group"},
        },
    ]


def _attr(name: str, type_: str = "string", **extra: object) -> dict[str, object]:
    return {
        "name": name,
        "type": type_,
        "multiValued": False,
        "required": False,
        "caseExact": False,
        "mutability": "readWrite",
        "returned": "default",
        "uniqueness": "none",
        **extra,
    }


def schemas() -> list[dict[str, object]]:
    user_attrs = [
        _attr("userName", required=True, uniqueness="server"),
        _attr("externalId", caseExact=True),
        _attr(
            "name",
            "complex",
            subAttributes=[
                _attr("givenName"),
                _attr("familyName"),
                _attr("formatted", mutability="readOnly"),
            ],
        ),
        _attr("displayName"),
        _attr(
            "emails",
            "complex",
            multiValued=True,
            subAttributes=[_attr("value"), _attr("type"), _attr("primary", "boolean")],
        ),
        _attr("active", "boolean"),
        _attr(
            "groups",
            "complex",
            multiValued=True,
            mutability="readOnly",
            subAttributes=[_attr("value"), _attr("display")],
        ),
    ]
    group_attrs = [
        _attr("displayName", required=True, uniqueness="server"),
        _attr("externalId", caseExact=True),
        _attr(
            "members",
            "complex",
            multiValued=True,
            subAttributes=[_attr("value", mutability="immutable"), _attr("display")],
        ),
    ]
    return [
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": USER_SCHEMA,
            "name": "User",
            "description": "User account",
            "attributes": user_attrs,
            "meta": {"resourceType": "Schema"},
        },
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": GROUP_SCHEMA,
            "name": "Group",
            "description": "Group (mapped to organization roles)",
            "attributes": group_attrs,
            "meta": {"resourceType": "Schema"},
        },
    ]
