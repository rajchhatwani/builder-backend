"""Sandboxed Jinja rendering shared by all feature modules.

Spec values reach templates only as validated identifiers or through `pyrepr`, which
turns a Python scalar into a source literal, so a value can never break out of a string.
Template files ending in `.tpl` are copied verbatim; `.j2` files are rendered.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from app.core.generator.context import tuple_literal

ALIAS_MARKER = "@@ALIAS_IMPORTS@@"

# token used in generated source -> (section, import statement). Section order: stdlib,
# then third-party; within a section plain imports precede `from` imports (isort default).
_ALIASES: tuple[tuple[str, str, str, str], ...] = (
    # (token, section, kind, statement)
    ("_dt.", "std", "import", "import datetime as _dt"),
    ("_decimal.", "std", "import", "import decimal as _decimal"),
    ("_random.", "std", "import", "import random as _random"),
    ("_string.", "std", "import", "import string as _string"),
    ("_t.", "std", "import", "import typing as _t"),
    ("_uuid.", "std", "import", "import uuid as _uuid"),
    ("_fa.", "third", "import", "import fastapi as _fa"),
    ("_pd.", "third", "import", "import pydantic as _pd"),
    ("_sa.", "third", "import", "import sqlalchemy as _sa"),
    ("_orm.", "third", "from", "from sqlalchemy import orm as _orm"),
    ("_pg.", "third", "from", "from sqlalchemy.dialects import postgresql as _pg"),
    (
        "_AsyncSession",
        "third",
        "from",
        "from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession",
    ),
)


def pyrepr(value: Any) -> str:
    """Source literal for a validated scalar. Strings go through repr(), never raw."""
    if value is None or isinstance(value, bool | int | float | str):
        return repr(value)
    raise TypeError(f"pyrepr cannot render {type(value).__name__}")


def make_environment(templates_dir: Path) -> SandboxedEnvironment:
    env = SandboxedEnvironment(
        loader=FileSystemLoader(str(templates_dir), encoding="utf-8"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pyrepr"] = pyrepr
    env.filters["tuple_lit"] = tuple_literal
    env.filters["tuple_lit_args"] = lambda names: ", ".join(f'"{n}"' for n in names)
    return env


def render_template(env: SandboxedEnvironment, template: str, /, **context: Any) -> str:
    text = env.get_template(template).render(**context)
    return _expand_alias_imports(text)


def read_verbatim(templates_dir: Path, name: str) -> str:
    return (templates_dir / name).read_text(encoding="utf-8")


def _expand_alias_imports(text: str) -> str:
    """Replace the marker line with exactly the `_x` alias imports the body uses, so the
    generated file never has unused or missing imports."""
    if ALIAS_MARKER not in text:
        return text
    head, _, body = text.partition(ALIAS_MARKER + "\n")
    used = [a for a in _ALIASES if re.search(r"(?<![A-Za-z0-9_])" + re.escape(a[0]), body)]
    blocks: list[str] = []
    for section in ("std", "third"):
        lines = [a[3] for a in used if a[1] == section and a[2] == "import"]
        lines += [a[3] for a in used if a[1] == section and a[2] == "from"]
        if lines:
            blocks.append("\n".join(lines))
    header = "\n\n".join(blocks)
    return head + (header + "\n" if header else "") + body


def render_tree(
    env: SandboxedEnvironment,
    templates_dir: Path,
    mapping: dict[str, Callable[[], dict[str, Any]] | None],
) -> dict[str, str]:
    """Render `{template name: context factory}`; the output path is the template name
    minus its .j2/.tpl suffix. A None factory means a verbatim (.tpl) copy."""
    out: dict[str, str] = {}
    for name, factory in mapping.items():
        path = name.rsplit(".", 1)[0]
        out[path] = (
            read_verbatim(templates_dir, name)
            if factory is None
            else render_template(env, name, **factory())
        )
    return out
