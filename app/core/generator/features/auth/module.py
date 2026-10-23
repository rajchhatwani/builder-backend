"""The `auth` feature: users, JWT access + rotating refresh tokens, and email / mobile flows.

Email: verification, magic-link login and password reset through SMTP. Mobile: phone
verification, OTP login and password reset through Twilio, Vonage or AWS SNS. Secrets
(JWT key, SMTP password, SMS keys) are read from the environment of the generated project,
never rendered into source. Custom registration fields become real `auth_users` columns.
"""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree
from app.core.generator.context import ProjectCtx
from app.core.generator.features.tests.module import creatable
from app.core.generator.render import make_environment, pyrepr, read_verbatim, render_template
from app.core.spec_models import SpecAuth, SpecAuthCustomField
from app.core.validation import invitations_enabled

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/auth/__init__.py.tpl",
    "app/auth/access.py.tpl",
    "app/auth/deps.py.tpl",
    "app/auth/middleware.py.tpl",
    "app/auth/ratelimit.py.tpl",
    "app/auth/service.py.tpl",
    "app/auth/provider_lock.py.tpl",
    "tests/test_provider_lock.py.tpl",
)
_RENDERED = (
    "app/auth/config.py.j2",
    "app/auth/delivery.py.j2",
    "app/auth/keys.py.j2",
    "app/auth/models.py.j2",
    "app/auth/router.py.j2",
    "app/auth/schemas.py.j2",
    "app/auth/security.py.j2",
    "app/auth/tokens.py.j2",
    "alembic/versions/0002_auth.py.j2",
    "tests/_auth_support.py.j2",
    "tests/test_auth.py.j2",
)

# With Keycloak the identity provider owns passwords, tokens and sign-in, so the auth module
# is much smaller: verify tokens, keep a profile row per user, enforce the same permissions.
_KEYCLOAK_VERBATIM = (
    "app/auth/__init__.py.tpl",
    "app/auth/access.py.tpl",
    "app/auth/middleware.py.tpl",
    "app/auth/provider_lock.py.tpl",
    "tests/test_provider_lock.py.tpl",
    "keycloak/app/auth/deps.py.tpl",
    "keycloak/app/auth/oidc.py.tpl",
    "keycloak/app/auth/router.py.tpl",
    "keycloak/app/auth/service.py.tpl",
)
_KEYCLOAK_RENDERED = (
    "keycloak/alembic/versions/0002_auth.py.j2",
    "keycloak/app/auth/config.py.j2",
    "keycloak/app/auth/models.py.j2",
    "keycloak/tests/_auth_support.py.j2",
    "keycloak/tests/test_auth.py.j2",
)
_KEYCLOAK_DIR = "keycloak/"

_EMAIL_PATTERN = r"^[^@\s\"'<>]+@[^@\s\"'<>]+\.[^@\s\"'<>]+$"
_PHONE_PATTERN = r"^\+[1-9][0-9]{6,14}$"
_URL_PATTERN = r"^https?://[^\s\"'<>\\]+$"
_TEXT_LENGTH_FALLBACK = 255


@dataclass(frozen=True)
class CustomFieldCtx:
    name: str
    label: str
    schema_decl: str  # pydantic field line on RegisterRequest
    read_decl: str  # pydantic field line on UserRead
    column_decl: str  # SQLAlchemy mapped column on AuthUser
    migration_column: str
    sample: str  # python expression for a valid JSON value, used by the generated test
    variant: str  # like sample but different per `n` (for unique fields)
    required: bool  # must be sent at registration
    unique: bool
    indexed: bool
    exact: bool  # the API returns the sample unchanged (not true for date / datetime)


def _number(value: float) -> str:
    return repr(int(value)) if float(value).is_integer() else repr(float(value))


def _default_literal(field: SpecAuthCustomField) -> str | None:
    """The default as a Python source literal, or None when there is none."""
    raw = field.default_value
    if raw is None:
        return None
    match field.type:
        case "integer":
            return repr(int(raw))
        case "float":
            return repr(float(raw))
        case "boolean":
            return "True" if raw == "true" else "False"
        case "date":
            return f"_dt.date.fromisoformat({pyrepr(raw)})"
        case "datetime":
            return f"_dt.datetime.fromisoformat({pyrepr(raw)})"
        case _:
            return pyrepr(raw)


def _variant(field_type: str, sample: str) -> str:
    """A python expression, using the variable `n` (0-9), that differs for every n and is
    valid wherever `sample` is. Types that cannot vary keep their sample."""
    match field_type:
        case "email":
            return 'f"sample{n}@example.com"'
        case "phone":
            return 'f"+1415555010{n}"'
        case "url":
            return 'f"https://example.com/sample{n}"'
        case "string" | "text":
            return f'f"{ast.literal_eval(sample)[:-1]}{{n}}"'
        case "integer":
            return f"{sample} + n"
        case "float":
            return f"{sample} + n"
        case "date":
            return 'f"2000-01-{10 + n}"'
        case _:
            return sample


def _custom_field(field: SpecAuthCustomField) -> CustomFieldCtx:
    default = _default_literal(field)
    required_input = field.required and default is None
    nullable_input = not field.required and default is None
    constraints: list[str] = []

    match field.type:
        case "string" | "text" | "email" | "phone" | "url":
            ann = "str"
            length = field.max_length or _TEXT_LENGTH_FALLBACK
            if field.type == "text" and field.max_length is None:
                sa_type, mig_type = "_sa.Text()", "sa.Text()"
            else:
                sa_type, mig_type = f"_sa.String({length})", f"sa.String({length})"
            if field.min_length is not None:
                constraints.append(f"min_length={field.min_length}")
            constraints.append(f"max_length={length}")
            patterns = {"email": _EMAIL_PATTERN, "phone": _PHONE_PATTERN, "url": _URL_PATTERN}
            if field.type in patterns:
                constraints.append(f"pattern={pyrepr(patterns[field.type])}")
            sample = {
                "email": pyrepr("sample@example.com"),
                "phone": pyrepr("+14155550100"),
                "url": pyrepr("https://example.com/sample"),
            }.get(field.type, pyrepr("x" * max(field.min_length or 0, 6)))
        case "integer" | "float":
            ann = "int" if field.type == "integer" else "float"
            sa_type, mig_type = (
                ("_sa.Integer()", "sa.Integer()")
                if field.type == "integer"
                else ("_sa.Float()", "sa.Float()")
            )
            if field.min_value is not None:
                constraints.append(f"ge={_number(field.min_value)}")
            if field.max_value is not None:
                constraints.append(f"le={_number(field.max_value)}")
            if field.min_value is not None:
                sample = _number(field.min_value)
            else:
                sample = "1" if field.type == "integer" else "1.5"
        case "boolean":
            ann, sa_type, mig_type, sample = "bool", "_sa.Boolean()", "sa.Boolean()", "True"
        case "date":
            ann, sa_type, mig_type = "_dt.date", "_sa.Date()", "sa.Date()"
            sample = pyrepr("2000-01-31")
        case "datetime":
            ann = "_dt.datetime"
            sa_type, mig_type = "_sa.DateTime(timezone=True)", "sa.DateTime(timezone=True)"
            sample = pyrepr("2000-01-31T12:00:00+00:00")
        case "enum":
            values = field.enum_values or []
            ann = "_t.Literal[" + ", ".join(pyrepr(v) for v in values) + "]"
            sa_type, mig_type = "_sa.String(64)", "sa.String(64)"
            sample = pyrepr(values[0])
        case _:  # unreachable: validation rejects unknown types
            raise ValueError(f"unsupported custom field type {field.type!r}")

    variant = _variant(field.type, sample)
    parts = list(constraints)
    if default is not None:
        parts.append(f"default={default}")
    elif nullable_input:
        parts.append("default=None")
    schema_decl = f"{field.name}: {ann + ' | None' if nullable_input else ann}"
    if parts:
        schema_decl += f" = _pd.Field({', '.join(parts)})"

    # A required field with a default is filled in by the schema, so it is never null.
    is_nullable = not field.required
    mapped = f"{ann} | None" if is_nullable else ann
    column_decl = (
        f"{field.name}: _orm.Mapped[{mapped}] = "
        f"_orm.mapped_column({sa_type}, nullable={is_nullable})"
    )
    return CustomFieldCtx(
        name=field.name,
        label=field.label,
        schema_decl=schema_decl,
        read_decl=f"{field.name}: {ann} | None = None",
        column_decl=column_decl,
        migration_column=f'sa.Column("{field.name}", {mig_type}, nullable={is_nullable}),',
        sample=sample,
        variant=variant,
        required=required_input,
        unique=field.unique,
        indexed=field.indexed and not field.unique,
        exact=field.type not in ("date", "datetime"),
    )


def _tuple(items: list[str]) -> str:
    body = ", ".join(pyrepr(i) for i in items)
    return f"({body},)" if len(items) == 1 else f"({body})"


def _auth_context(project: ProjectCtx, auth: SpecAuth) -> dict[str, Any]:
    reset = auth.password_reset
    roles = sorted(auth.roles, key=lambda r: r.name)
    custom = tuple(
        _custom_field(f) for f in sorted(auth.registration.custom_fields, key=lambda f: f.name)
    )
    return {
        "a": auth,
        "project_name": project.name,
        "app_name": auth.app_name or project.name,
        "email_enabled": auth.smtp is not None,
        "magic_link": reset.email_magic_link,
        "sms_otp": reset.sms_otp,
        "verification_required": auth.registration.email_verification_required,
        "hard_delete": auth.deletion_mode == "hard",
        "custom_fields": custom,
        "extra_payload": "{"
        + ", ".join(f"{pyrepr(f.name)}: {f.variant if f.unique else f.sample}" for f in custom)
        + "}",
        "all_roles": _tuple([r.name for r in roles]),
        "multi_tenant": auth.multi_tenant,
        "tenant_tables": sorted(e.table for e in project.entities if e.tenant_scoped),
        "rs256": auth.jwt_algorithm == "RS256",
        "jwt_algorithm": auth.jwt_algorithm,
        "redis_store": auth.token_store == "redis",
        "invite_only": auth.registration.invite_only,
        "invitations": invitations_enabled(auth),
        "self_assignable": _tuple([r.name for r in roles if r.self_assignable]),
        "self_assignable_names": [r.name for r in roles if r.self_assignable],
        "invite_role": next(
            (r.name for r in roles if r.invite_only), roles[0].name if roles else None
        ),
        "not_assignable": next((r.name for r in roles if not r.self_assignable), None),
        "role_literal": "_t.Literal[" + ", ".join(pyrepr(r.name) for r in roles) + "]",
        "assignable_literal": "_t.Literal["
        + ", ".join(pyrepr(r.name) for r in roles if r.self_assignable)
        + "]",
        "gated": _gated_entities(project, auth),
        "inheriting_roles": [(r.name, r.inherits_from) for r in roles if r.inherits_from],
        "default_roles": _tuple([r.name for r in roles if r.is_default]),
        "role_parents": "{"
        + ", ".join(f"{pyrepr(r.name)}: {pyrepr(r.inherits_from)}" for r in roles)
        + "}",
        "sms_provider": auth.sms_provider if auth.sms is not None else None,
        "owned_tables": sorted(e.table for e in project.entities if e.owned),
    }


def _keycloak_context(project: ProjectCtx, auth: SpecAuth) -> dict[str, Any]:
    kc = auth.keycloak
    assert kc is not None  # validation guarantees the block when the provider is keycloak
    return {
        **_auth_context(project, auth),
        "kc": kc,
        "docs_client_id": f"{kc.web_client_id}-docs",
    }


def _held(role: str, parents: dict[str, str | None]) -> set[str]:
    held: set[str] = set()
    cursor: str | None = role
    while cursor is not None and cursor not in held:
        held.add(cursor)
        cursor = parents.get(cursor)
    return held


def _gated_entities(project: ProjectCtx, auth: SpecAuth) -> list[dict[str, Any]]:
    """What the generated access tests need to know about each entity with access rules."""
    parents = {r.name: r.inherits_from for r in auth.roles}
    default_held: set[str] = set()
    for role in auth.roles:
        if role.is_default:
            default_held |= _held(role.name, parents)
    rules = {(p.entity, p.operation): p.row_rule for p in auth.permissions}
    gated: list[dict[str, Any]] = []
    for entity in project.entities:
        if not entity.access:
            continue
        ops = []
        for a in entity.access:
            ops.append(
                {
                    "op": a.op,
                    "needs_user": a.needs_user,
                    # a user holding only the default roles is turned away
                    "denies_default": bool(a.roles) and not (default_held & set(a.roles)),
                    "owner": a.owner,
                    "admin_sees_all": a.admin_sees_all,
                    "rule": rules.get((entity.name, a.op)),
                }
            )
        gated.append(
            {
                "name": entity.name,
                "table": entity.table,
                "path": entity.path,
                "owned": entity.owned,
                "scoped": any(o["owner"] for o in ops),
                "tenant_scoped": entity.tenant_scoped,
                "creatable": creatable(entity, project),
                "ops": ops,
            }
        )
    return gated


class AuthModule:
    name = "auth"

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        auth = project.auth
        if auth is None:
            return {}
        if auth.provider == "keycloak":
            return self._render_keycloak(project, auth)
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        context = _auth_context(project, auth)
        for template in _RENDERED:
            files[template.rsplit(".", 1)[0]] = render_template(self._env, template, **context)
        if context["invitations"] or context["self_assignable_names"]:
            files["tests/test_invitations.py"] = render_template(
                self._env, "tests/test_invitations.py.j2", **context
            )
        if context["multi_tenant"]:
            files["tests/test_tenancy.py"] = render_template(
                self._env, "tests/test_tenancy.py.j2", **context
            )
        if context["gated"]:
            files["tests/test_access.py"] = render_template(
                self._env, "tests/test_access.py.j2", **context
            )
        return files

    def _render_keycloak(self, project: ProjectCtx, auth: SpecAuth) -> FileTree:
        files: FileTree = {
            template.removeprefix(_KEYCLOAK_DIR).rsplit(".", 1)[0]: read_verbatim(
                _TEMPLATES, template
            )
            for template in _KEYCLOAK_VERBATIM
        }
        context = _keycloak_context(project, auth)
        for template in _KEYCLOAK_RENDERED:
            target = template.removeprefix(_KEYCLOAK_DIR).rsplit(".", 1)[0]
            files[target] = render_template(self._env, template, **context)
        if context["gated"]:
            files["tests/test_access.py"] = render_template(
                self._env, "tests/test_access.py.j2", **context
            )
        return files
