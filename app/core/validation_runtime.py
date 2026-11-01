"""Validation for the `settings`, `sequences` and `lists` sections. Issues go through
`add(path, code, message)`. Nothing here evaluates anything: values are checked against fixed rules."""

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from app.core.spec_models import Spec

Add = Callable[[str, str, str], None]

RC_TABLES = ("rc_list_items", "rc_sequences", "rc_settings")
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,59}")
VALUE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
PREFIX_RE = re.compile(r"[A-Za-z0-9_/\-]{0,20}")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")
DECIMAL_RE = re.compile(r"-?[0-9]{1,18}(\.[0-9]{1,8})?")
SETTING_TYPES = ("string", "int", "bool", "decimal")
# A setting is a business knob that API callers can read: refuse names that suggest a credential.
SECRET_WORDS = (
    "secret", "password", "passwd", "passphrase", "token", "credential", "private_key", "api_key",
    "cardnumber", "card_number",
)  # fmt: skip
# Short words are matched as whole name parts ("pin_code", "userPin") so "shipping" stays allowed.
SECRET_PARTS = frozenset({"pwd", "pin", "otp", "cvv", "cvc", "ssn", "iban", "credentials"})
_PART_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")
# NUL cannot be stored by Postgres text columns (a 500); bidi controls can disguise a label.
BAD_TEXT_RE = re.compile("[\x00\u202a-\u202e\u2066-\u2069]")


def looks_secret(name: str) -> bool:
    """True when a field / setting / sequence name suggests a credential. Shared by every validator."""
    lowered = name.lower()
    if any(w in lowered for w in SECRET_WORDS):
        return True
    return any(part.lower() in SECRET_PARTS for part in _PART_SPLIT.split(name) if part)
MAX_SETTINGS = 200
MAX_SEQUENCES = 50
MAX_LISTS = 100
MAX_LIST_ITEMS = 500
DEFAULT_MAX_LENGTH = 200
MAX_STRING_LENGTH = 2000
MAX_INT = 2**53


def runtime_config_active(spec: Spec) -> bool:
    return bool(spec.settings or spec.sequences or spec.lists)


def runtime_router_present(spec: Spec) -> bool:
    """Counters are readable through the API only by signed-in roles, so a project without auth
    and with only sequences has no router (the `next_number` helper is still generated)."""
    auth_on = spec.auth is not None and spec.auth.enabled
    return bool(spec.settings or spec.lists or (auth_on and spec.sequences))


def to_decimal(value: object) -> Decimal | None:
    """A decimal setting value: a string like "12.50" or a whole number; never a float."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str) and DECIMAL_RE.fullmatch(value):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return None


def check_runtime_config(spec: Spec, add: Add) -> None:
    auth_on = spec.auth is not None and spec.auth.enabled
    roles = {r.name for r in spec.auth.roles} if spec.auth is not None else set()

    def check_roles(names: list[str], path: str) -> None:
        if not names:
            return
        if not auth_on:
            add(path, "auth_required", "roles need the auth feature switched on")
            return
        for k, role in enumerate(names):
            if role not in roles:
                add(f"{path}[{k}]", "unknown_role", f"no role named {role!r}")

    _settings(spec, check_roles, add)
    _sequences(spec, check_roles, add)
    _lists(spec, check_roles, add)


def _settings(spec: Spec, check_roles: Callable[[list[str], str], None], add: Add) -> None:
    if len(spec.settings) > MAX_SETTINGS:
        add("settings", "too_many", f"at most {MAX_SETTINGS} settings")
        return
    seen: set[str] = set()
    for i, s in enumerate(spec.settings):
        p = f"settings[{i}]"
        if not NAME_RE.fullmatch(s.key):
            add(f"{p}.key", "invalid_value", "use lowercase letters, digits and '_' (max 60)")
        elif s.key in seen:
            add(f"{p}.key", "duplicate_name", f"setting {s.key} is listed twice")
        elif looks_secret(s.key):
            add(f"{p}.key", "secret_name", "settings are readable through the API: no secrets here")
        seen.add(s.key)
        check_roles(s.read_roles, f"{p}.read_roles")
        check_roles(s.edit_roles, f"{p}.edit_roles")
        if s.type not in SETTING_TYPES:
            add(f"{p}.type", "invalid_value", f"type must be one of {', '.join(SETTING_TYPES)}")
            continue
        if s.default is None:
            add(f"{p}.default", "required", "every setting needs a default value")
            continue
        _check_typed(s.type, s.default, s.minimum, s.maximum, s.max_length, p, add)


def _check_typed(
    kind: str,
    default: object,
    minimum: object,
    maximum: object,
    max_length: int | None,
    p: str,
    add: Add,
) -> None:
    if kind in ("string", "bool") and (minimum is not None or maximum is not None):
        add(f"{p}.minimum", "invalid_value", "minimum and maximum are for int and decimal settings")
    if kind != "string" and max_length is not None:
        add(f"{p}.max_length", "invalid_value", "max_length is for string settings")
    if kind == "string":
        limit = DEFAULT_MAX_LENGTH if max_length is None else max_length
        if not 1 <= limit <= MAX_STRING_LENGTH:
            add(f"{p}.max_length", "invalid_value", f"max_length must be 1 to {MAX_STRING_LENGTH}")
        if not isinstance(default, str):
            add(f"{p}.default", "invalid_value", "default must be a string")
        elif len(default) > limit:
            add(f"{p}.default", "too_long", f"default is longer than {limit} characters")
        elif "\x00" in default:
            add(f"{p}.default", "invalid_value", "no NUL character")
    elif kind == "bool":
        if not isinstance(default, bool):
            add(f"{p}.default", "invalid_value", "default must be true or false")
    else:
        number = _number(kind, default)
        if number is None:
            add(f"{p}.default", "invalid_value", f"default must be a valid {kind}")
        low = _bound(kind, minimum, f"{p}.minimum", add)
        high = _bound(kind, maximum, f"{p}.maximum", add)
        if low is not None and high is not None and low > high:
            add(f"{p}.minimum", "invalid_value", "minimum is above maximum")
        if number is not None:
            if low is not None and number < low:
                add(f"{p}.default", "out_of_range", "default is below the minimum")
            if high is not None and number > high:
                add(f"{p}.default", "out_of_range", "default is above the maximum")


def _number(kind: str, value: object) -> Decimal | None:
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > MAX_INT:
            return None
        return Decimal(value)
    return to_decimal(value)


def _bound(kind: str, value: object, path: str, add: Add) -> Decimal | None:
    if value is None:
        return None
    number = _number(kind, value)
    if number is None:
        add(path, "invalid_value", f"must be a valid {kind}")
    return number


def _sequences(spec: Spec, check_roles: Callable[[list[str], str], None], add: Add) -> None:
    if len(spec.sequences) > MAX_SEQUENCES:
        add("sequences", "too_many", f"at most {MAX_SEQUENCES} sequences")
        return
    tenant = spec.auth is not None and spec.auth.enabled and spec.auth.multi_tenant
    seen: set[str] = set()
    for i, q in enumerate(spec.sequences):
        p = f"sequences[{i}]"
        if not NAME_RE.fullmatch(q.name):
            add(f"{p}.name", "invalid_value", "use lowercase letters, digits and '_' (max 60)")
        elif q.name in seen:
            add(f"{p}.name", "duplicate_name", f"sequence {q.name} is listed twice")
        elif looks_secret(q.name):
            add(f"{p}.name", "secret_name", "counters are readable through the API: no secrets here")
        seen.add(q.name)
        if not PREFIX_RE.fullmatch(q.prefix):
            add(f"{p}.prefix", "invalid_value", "up to 20 letters, digits, '-', '_' or '/'")
        if not 0 <= q.padding <= 12:
            add(f"{p}.padding", "invalid_value", "padding must be 0 to 12")
        if not 0 <= q.start <= MAX_INT:
            add(f"{p}.start", "invalid_value", f"start must be 0 to {MAX_INT}")
        if q.per_tenant and not tenant:
            add(f"{p}.per_tenant", "tenancy_required", "per-tenant counters need auth.multi_tenant")
        check_roles(q.view_roles, f"{p}.view_roles")


def _lists(spec: Spec, check_roles: Callable[[list[str], str], None], add: Add) -> None:
    if len(spec.lists) > MAX_LISTS:
        add("lists", "too_many", f"at most {MAX_LISTS} lists")
        return
    seen: set[str] = set()
    for i, lst in enumerate(spec.lists):
        p = f"lists[{i}]"
        if not NAME_RE.fullmatch(lst.name):
            add(f"{p}.name", "invalid_value", "use lowercase letters, digits and '_' (max 60)")
        elif lst.name in seen:
            add(f"{p}.name", "duplicate_name", f"list {lst.name} is listed twice")
        seen.add(lst.name)
        check_roles(lst.edit_roles, f"{p}.edit_roles")
        if not 1 <= lst.max_items <= MAX_LIST_ITEMS:
            add(f"{p}.max_items", "invalid_value", f"max_items must be 1 to {MAX_LIST_ITEMS}")
        elif len(lst.items) > lst.max_items:
            add(f"{p}.items", "too_many", f"{len(lst.items)} default items exceed max_items")
        values: set[str] = set()
        for j, item in enumerate(lst.items):
            ip = f"{p}.items[{j}]"
            if not VALUE_RE.fullmatch(item.value):
                add(f"{ip}.value", "invalid_value", "use lowercase letters, digits and '_' (max 40)")
            elif item.value in values:
                add(f"{ip}.value", "duplicate_name", f"value {item.value} is listed twice")
            values.add(item.value)
            if not item.label.strip() or len(item.label) > 80:
                add(f"{ip}.label", "invalid_value", "label must be 1 to 80 characters")
            elif BAD_TEXT_RE.search(item.label):
                add(f"{ip}.label", "invalid_value", "no NUL or bidi control characters")
            if item.color is not None and not COLOR_RE.fullmatch(item.color):
                add(f"{ip}.color", "invalid_value", "color must look like #1a2b3c")
