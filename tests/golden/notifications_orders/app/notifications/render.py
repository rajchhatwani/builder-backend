"""Rendering and recipient checks (generated). Pure functions, no I/O.

A template is text with `{{ name }}` placeholders and nothing else. Rendering is ONE pass of plain
substitution: a value is inserted as text and never looked at again, so a value of `{{ 7*7 }}` stays
`{{ 7*7 }}`. There is no expression language, no attribute access, no filter and no include. Values are
HTML-escaped in an HTML email; subjects, titles and SMS text lose control characters (no header or
line injection)."""

import html as _html
import re
from collections.abc import Callable, Mapping

MAX_VALUE = 2000
MAX_VARIABLES = 50
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,39})\s*\}\}")
_BRACES = ("{{", "}}", "{%", "%}", "{#", "#}")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u0080-\u009f  ‪-‮⁦-⁩]")
_LINE = re.compile(r"[\x00-\x1f\x7f\u0080-\u009f  ‪-‮⁦-⁩]+")

LIMITS = {
    "email": {"subject": 200, "body": 200_000},
    "sms": {"subject": 0, "body": 1_000},
    "push": {"subject": 200, "body": 1_000},
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,63}")
_PHONE_RE = re.compile(r"\+[1-9][0-9]{6,14}")
_DEVICE_RE = re.compile(r"[A-Za-z0-9:_.\-]{8,512}")


class RenderError(ValueError):
    """The template or the data cannot be rendered. The message never contains a value."""


def placeholders(text: str) -> set[str]:
    return {m.group(1) for m in PLACEHOLDER_RE.finditer(text)}


def check_template(text: str, variables: set[str] | frozenset[str]) -> None:
    """Raise RenderError unless `text` uses only `{{ name }}` of declared variables."""
    unknown = sorted(placeholders(text) - set(variables))
    if unknown:
        raise RenderError(f"unknown variable(s): {', '.join(unknown)}")
    rest = PLACEHOLDER_RE.sub("", text)
    if any(token in rest for token in _BRACES):
        raise RenderError("only {{ name }} placeholders of declared variables are allowed")


def clean_values(values: Mapping[str, object], variables: set[str] | frozenset[str]) -> dict[str, str]:
    """The data as text. Unknown names are an error (a typo must not silently drop data); a declared
    variable that is missing renders as empty text."""
    if len(values) > MAX_VARIABLES:
        raise RenderError("too many variables")
    out: dict[str, str] = {}
    for name, value in values.items():
        if isinstance(value, str) and "\x00" in value:
            raise RenderError(f"variable {name} contains a NUL character")
        if name not in variables:
            raise RenderError(f"unknown variable: {name}")
        if value is None:
            text = ""
        elif isinstance(value, bool | int | float | str):
            text = str(value)
        else:
            raise RenderError(f"variable {name} must be text, a number or a boolean")
        if len(text) > MAX_VALUE:
            raise RenderError(f"variable {name} is longer than {MAX_VALUE} characters")
        out[name] = text
    return out


# A value placed inside one of these attributes of an HTML template is a URL: only these schemes pass.
_URL_ATTR_RE = re.compile(
    r"""(?:href|src|action|formaction|xlink:href|poster|background|cite)\s*=\s*(?:"[^"]*|'[^']*|[^\s"'>]*)$""",
    re.IGNORECASE,
)
_SAFE_SCHEMES = ("http", "https", "mailto", "tel")
_SCHEME_RE = re.compile(r"([a-z][a-z0-9+.\-]*):")
_STRIP = re.compile(r"[\s\x00-\x1f\x7f\u0080-\u009f\u200b-\u200f\u2028\u2029\u2060\ufeff]+")


def safe_url(value: str) -> str:
    """`value` if it has no scheme or an allowed one (http, https, mailto, tel); otherwise `#`.
    Whitespace and control characters are ignored when looking for the scheme (`java\tscript:`)."""
    probe = _STRIP.sub("", value).lower()
    found = _SCHEME_RE.match(probe)
    if found is not None and found.group(1) not in _SAFE_SCHEMES:
        return "#"
    return value


def _substitute(
    template: str, values: Mapping[str, str], transform: Callable[[str], str], urls: bool = False
) -> str:
    def one(match: re.Match[str]) -> str:
        raw = values.get(match.group(1), "")
        if urls and _URL_ATTR_RE.search(template[: match.start()]):
            raw = safe_url(raw)
        return transform(raw)

    return PLACEHOLDER_RE.sub(one, template)


def _one_line(text: str) -> str:
    return " ".join(_LINE.sub(" ", text).split())


def _text(text: str) -> str:
    return _CONTROL.sub("", text)


def _escape(text: str) -> str:
    return _html.escape(_CONTROL.sub("", text), quote=True)


def render(
    channel: str, subject: str, body: str, html: bool, values: Mapping[str, str]
) -> tuple[str, str]:
    """(subject, body) ready for the provider. Template text (written by an admin) is kept as it is,
    except that the subject is one line; only the VALUES are escaped or cleaned."""
    limits = LIMITS.get(channel)
    if limits is None:
        raise RenderError("unknown channel")
    use_html = html and channel == "email"
    out_subject = _one_line(_substitute(subject, values, _one_line)) if limits["subject"] else ""
    out_body = _substitute(body, values, _escape if use_html else _text, urls=use_html)
    if len(out_subject) > limits["subject"] or len(out_body) > limits["body"]:
        raise RenderError("the rendered message is too long")
    if not out_body.strip():
        raise RenderError("the rendered message is empty")
    return out_subject, out_body


def valid_address(channel: str, address: str | None) -> bool:
    """Strict, so nothing can smuggle a header, a second recipient or a command into a send."""
    if not address or len(address) > 320:
        return False
    if channel == "email":
        return _EMAIL_RE.fullmatch(address) is not None
    if channel == "sms":
        return _PHONE_RE.fullmatch(address) is not None
    if channel == "push":
        return _DEVICE_RE.fullmatch(address) is not None
    return False


def mask(channel: str, address: str | None) -> str:
    """A hint for humans that cannot be used to send: `a***@example.com`, `+1*****67`, `dev***`."""
    if not address or not valid_address(channel, address):
        return ""
    if channel == "email":
        local, _, domain = address.partition("@")
        return f"{local[:1]}***@{domain}"[:80]
    if channel == "sms":
        return f"{address[:2]}{'*' * 5}{address[-2:]}"
    return f"{address[:3]}***"
