"""Gates G0-G7 for custom hooks. Plain standard library; the file is copied byte for byte into
generated projects, where it runs as `python -m app.platform_gate`, and it is unit-tested in the builder.

A hook body is free Python between two marked lines of a stub file. These gates look at the source
with `ast` only: nothing here imports, compiles to code, evaluates or runs the code it checks.

  G0  the file parses, is in the hook zone, the signature line and the body markers are intact
  G1  imports: banned modules, network clients, anything outside the allow-list and the SDK facade
  G2  banned names and calls (eval, open, getattr on dynamic names ...), dunder and private access
  G3  raw identity access (claims["sub"], request headers, tokens) and secret-looking literals
  G4  purity: no I/O, no global or input writes, no clock or randomness outside the SDK
  G5  contract: the signature matches the generated models and the function returns the output model
  G6  size and complexity: node count, loop depth, `while`, recursion, iteration bounds
  G7  zone integrity: files outside the manifest, generated files changed, edits outside the body

Every finding is `{rule, gate, file, line, message}`. Messages carry identifiers only, never a literal
from the checked source. Exit code 0 = no findings; 1 = findings; 2 = the gate could not run.

    python -m app.platform_gate [--root DIR] [--file PATH ...] [--hook NAME ...]
"""

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GATE_VERSION = 2
MANIFEST_PATH = "platform/hooks.json"
ZONES_PATH = "platform/zones.json"
HOOK_DIR = "app/custom/hooks"
SIGNATURE_COMMENT = "# platform:signature (fixed)"
BODY_PLACEHOLDER = "<body>"
GATES = ("G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7")
# What each gate means in THIS implementation (printed in the `gates` map of the report).
GATE_MEANING: dict[str, str] = {
    "G0": "the file parses, is plain UTF-8, sits in the hook zone; signature line, body markers and top-level structure are intact",
    "G1": "imports: banned/network/non-allow-listed modules, names outside a module's allow-list, and any use of a module object as a value",
    "G2": "banned built-ins and calls (getattr, format, vars ...), dunder/private/introspection attributes, format-string traversals, classes, decorators, async",
    "G3": "raw token claims, request headers and secret-looking literals",
    "G4": "purity: no I/O, global or input writes, clock or randomness outside the SDK, SDK I/O only in effect hooks",
    "G5": "contract: signature, return of the output model, output fields, known input fields, stub implemented",
    "G6": "static resource bounds: size, loop depth, while, recursion, ranges, powers, shifts, repetition, unbounded iterators (a static check, not a runtime limit)",
    "G7": "zone integrity: stub frame, generated and guarded files (app, alembic, requirements, Dockerfile, compose, conftest, .pth) unchanged, no stray files",
}

DEFAULT_LIMITS: dict[str, int] = {
    "max_file_bytes": 65536,
    "max_ast_nodes": 1500,
    "max_loop_depth": 3,
    "max_body_lines": 200,
    "max_iterations": 1_000_000,
    "max_string": 2000,
    "max_small": 100_000,
}

RULES: dict[str, str] = {
    "G0.syntax": "the file does not parse",
    "G0.encoding": "the file is not plain UTF-8 text (or declares another encoding)",
    "G0.size": "the file is larger than the limit",
    "G0.file_missing": "the stub file of a declared hook is missing",
    "G0.zone": "the file is not the stub of a declared hook",
    "G0.signature": "the fixed signature line changed",
    "G0.markers": "the body markers are missing, repeated or out of order",
    "G0.structure": "code outside the hook function",
    "G1.banned_import": "this module is never allowed in a hook",
    "G1.network_import": "network clients are not allowed in a hook",
    "G1.layer_import": "a hook may import only the SDK facade and its contracts from the app",
    "G1.not_allowed_import": "this module is not on the allow-list",
    "G1.star_import": "star imports are not allowed",
    "G1.relative_import": "relative imports are not allowed",
    "G1.name_not_allowed": "this name of an allowed module is not on its allow-list",
    "G1.module_value": "a module may only be used as `module.name` of an allow-listed name, never as a value",
    "G2.banned_name": "this built-in is not allowed",
    "G2.dunder": "dunder and name-mangled names are not allowed",
    "G2.private_attr": "private attributes (leading underscore) are not allowed",
    "G2.introspection_attr": "frame and code introspection attributes are not allowed",
    "G2.dynamic_attr": "pow, iter and range may only be called directly",
    "G2.format_call": "format and format_map can read attributes: use an f-string",
    "G2.format_string": "a string that looks like a format-field traversal, contains a dunder or has a huge width",
    "G2.class_def": "class definitions are not allowed in a hook body",
    "G2.decorator": "decorators are not allowed in a hook",
    "G2.async_syntax": "async, await and yield are not allowed",
    "G3.raw_claims": "raw token claims: use the Principal from the SDK",
    "G3.raw_header": "raw request headers: hooks get typed input only",
    "G3.raw_token_name": "raw token or request objects: hooks get typed input only",
    "G3.secret_literal": "a secret-looking literal in the code",
    "G4.io_call": "print and input are I/O",
    "G4.global_write": "global and nonlocal writes are not allowed",
    "G4.module_write": "writing to a module or imported object",
    "G4.input_write": "the input model is read-only",
    "G4.nondeterministic_import": "clock and randomness come from the SDK, not from the stdlib",
    "G4.nondeterministic_call": "this call gives a different answer each time",
    "G4.sdk_io": "this SDK function does I/O: not allowed in a pure hook",
    "G5.function": "the hook function is missing or defined twice",
    "G5.signature": "the function signature differs from the generated contract",
    "G5.return_type": "a return that is not the output model",
    "G5.missing_return": "the function can end without returning the output model",
    "G5.not_implemented": "the body is still the stub",
    "G5.output_fields": "the output model is built with unknown or missing fields",
    "G5.output_positional": "output models are built with keyword arguments",
    "G5.unknown_input_field": "the input model has no such field",
    "G6.nodes": "the body is bigger than the node budget",
    "G6.body_lines": "the body has too many lines",
    "G6.loop_depth": "loops nested too deeply",
    "G6.while_loop": "`while` loops are not allowed: loop over a bounded sequence",
    "G6.recursion": "recursion is not allowed",
    "G6.iteration_bound": "the loops, powers, shifts or repeated values could run or grow too long",
    "G6.unbounded": "an unbounded iterator, range or size argument",
    "G6.literal_size": "a string literal is too long",
    "G6.nesting": "the code is nested too deeply to analyse",
    "G7.manifest": "the hook manifest is missing or unreadable",
    "G7.undeclared_file": "a file in the hook folder that no declared hook owns",
    "G7.outside_manifest": "a file that is neither in the zone manifest nor in a custom zone",
    "G7.generated_missing": "a generated file is missing",
    "G7.generated_modified": "a generated file was changed",
    "G7.frame_changed": "the stub was edited outside the marked body",
    "G7.symlink": "symbolic links are not allowed in the hook zone",
    "G7.guarded_new_file": "a new file in a guarded place (alembic, requirements, Dockerfile, compose, conftest, .pth ...)",
}

# --- module policy -----------------------------------------------------------------------------

BANNED_MODULES = frozenset(
    """os sys subprocess socket ctypes importlib pickle cPickle _pickle shelve dbm marshal builtins
    __builtin__ io pathlib shutil tempfile glob signal threading _thread multiprocessing concurrent
    asyncio inspect gc code codeop runpy pkgutil zipimport zipfile tarfile types sysconfig platform
    resource pty tty posix nt atexit weakref logging traceback linecache tokenize ast dis imp site
    select selectors sqlite3 webbrowser operator dataclasses copyreg copy
    contextlib abc typing_extensions re regex __main__""".split()
)
NETWORK_MODULES = frozenset(
    """requests httpx urllib urllib3 http aiohttp ssl ftplib smtplib poplib imaplib telnetlib xmlrpc
    websockets websocket grpc boto3 botocore paramiko email""".split()
)
NONDETERMINISTIC_MODULES = frozenset({"time", "random", "secrets"})

# Every name below is a function, class or constant, never a module (a unit test checks that and that
# nothing reachable through public attributes is a module). No factorial/comb/perm (huge results), no
# count/cycle/permutations/combinations/product (unbounded or combinatorial), no quantiles (size = argument).
_MATH = """ceil floor sqrt isqrt pow log log2 log10 exp fabs fsum prod gcd lcm trunc isclose isfinite
isnan isinf pi e inf nan tau copysign fmod hypot degrees radians sin cos tan atan
atan2 asin acos sinh cosh tanh remainder modf frexp ldexp dist""".split()
_ITERTOOLS = """accumulate chain compress dropwhile filterfalse groupby islice pairwise repeat
starmap takewhile tee zip_longest batched""".split()
_STATISTICS = """mean fmean median median_low median_high median_grouped mode multimode stdev pstdev
variance pvariance harmonic_mean geometric_mean StatisticsError""".split()
_DATETIME = "datetime date time timedelta timezone UTC MINYEAR MAXYEAR".split()
_DECIMAL = """Decimal ROUND_HALF_UP ROUND_HALF_EVEN ROUND_HALF_DOWN ROUND_DOWN ROUND_UP ROUND_CEILING
ROUND_FLOOR ROUND_05UP InvalidOperation DivisionByZero""".split()
_TYPING = """Any Optional Union Literal Final TypeAlias cast Sequence Mapping Iterable Iterator
Callable TYPE_CHECKING""".split()

# module -> the public names a hook may use from it. A module not listed is not allowed at all.
ALLOWED_MODULES: dict[str, frozenset[str]] = {
    "math": frozenset(_MATH),
    "itertools": frozenset(_ITERTOOLS),
    "statistics": frozenset(_STATISTICS),
    "datetime": frozenset(_DATETIME),
    "decimal": frozenset(_DECIMAL),
    "json": frozenset({"loads", "dumps", "JSONDecodeError"}),
    "typing": frozenset(_TYPING),
    "collections": frozenset(
        {"Counter", "defaultdict", "OrderedDict", "deque", "ChainMap", "namedtuple"}
    ),
    "collections.abc": frozenset(
        {"Sequence", "Mapping", "Iterable", "Iterator", "Callable", "Set", "Collection"}
    ),
    "functools": frozenset({"reduce", "partial", "cmp_to_key"}),
    "string": frozenset(
        {"ascii_letters", "ascii_lowercase", "ascii_uppercase", "digits", "hexdigits",
         "octdigits", "punctuation", "printable", "whitespace"}
    ),
    "textwrap": frozenset({"dedent", "indent", "shorten", "fill", "wrap"}),
    "calendar": frozenset({"monthrange", "isleap", "leapdays", "weekday", "monthcalendar"}),
    "bisect": frozenset({"bisect", "bisect_left", "bisect_right", "insort", "insort_left",
                         "insort_right"}),
    "heapq": frozenset({"heappush", "heappop", "heapify", "heappushpop", "heapreplace",
                        "nlargest", "nsmallest", "merge"}),
    "unicodedata": frozenset({"normalize", "category", "name", "numeric", "decimal", "digit"}),
    "uuid": frozenset({"UUID", "uuid3", "uuid5", "NAMESPACE_DNS", "NAMESPACE_URL",
                       "NAMESPACE_OID", "NAMESPACE_X500"}),
}
SDK_MODULE = "app.platform_sdk"
CONTRACTS_MODULE = "app.hooks_gen.contracts"

# --- name and attribute policy -----------------------------------------------------------------

BANNED_NAMES = frozenset(
    """eval exec compile open __import__ globals locals vars dir getattr hasattr setattr delattr format
    type object super memoryview bytes bytearray classmethod staticmethod property breakpoint help exit
    quit copyright credits license __build_class__ __builtins__ builtins""".split()
)
IO_NAMES = frozenset({"print", "input"})
NONDETERMINISTIC_NAMES = frozenset({"id", "hash"})
NONDETERMINISTIC_ATTRS = frozenset(
    {"now", "today", "utcnow", "utcfromtimestamp", "fromtimestamp", "uuid1", "uuid4", "urandom"}
)
INTROSPECTION_ATTRS = frozenset(
    """gi_frame gi_code gi_yieldfrom gi_running gi_suspended cr_frame cr_code cr_await ag_frame ag_code
    ag_await f_globals f_locals f_builtins f_back f_code f_lineno f_trace tb_frame tb_next tb_lineno
    co_code co_consts co_names co_varnames func_globals func_code mro cell_contents cr_origin
    construct parse_obj parse_raw parse_file from_orm schema schema_json update_forward_refs""".split()
)
# Pydantic's own API on the input object: only `model_dump` is part of the hook contract.
ALLOWED_MODEL_ATTRS = frozenset({"model_dump"})
FORMAT_ATTRS = frozenset({"format", "format_map"})
SIZE_METHODS = frozenset({"ljust", "rjust", "center", "zfill", "to_bytes", "expandtabs"})
IDENTITY_KEYS = frozenset({"sub", "iss", "sid", "jti", "azp", "aud"})
HEADER_KEYS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization", "x-auth-token",
     "x-forwarded-for"}
)
TOKEN_NAMES = frozenset(
    {"claims", "jwt", "access_token", "id_token", "refresh_token", "bearer", "authorization",
     "headers", "cookies", "request"}
)
SECRET_WORDS = ("password", "passwd", "secret", "token", "api_key", "apikey", "private_key", "credential")
_SECRET_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"AKIA[0-9A-Z]{16}",
        r"sk_(?:live|test)_[A-Za-z0-9]{8,}",
        r"sk-[A-Za-z0-9_-]{20,}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"AIza[0-9A-Za-z_-]{35}",
        r"\b[0-9a-fA-F]{32,}\b",
        r"(?<![\w/+=-])[A-Za-z0-9+/_-]{40,}={0,2}(?![\w/+=-])",
    )
)
_FORMAT_FIELD = re.compile(r"\{[^{}]*[.\[][^{}]*\}")
_PCT_WIDTH = re.compile(r"%[-+ #0]*(?:\*|\d{6,})")
_SPEC_WIDTH = re.compile(r"\d{6,}")
_CODING_COOKIE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
_SAFE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,62}")
_BAD_TEXT_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x85  \r]")


# --- findings ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    rule: str
    file: str
    line: int
    message: str

    @property
    def gate(self) -> str:
        return self.rule.split(".", 1)[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "gate": self.gate,
            "file": self.file,
            "line": self.line,
            "message": self.message,
        }


def _safe(name: object) -> str:
    """An identifier for a message: short, plain, never a secret-looking token."""
    text = str(name)
    if not _SAFE_NAME.fullmatch(text) or _looks_secret(text) or (len(text) >= 40 and "." not in text):
        return "<name>"
    return text


@dataclass(frozen=True)
class HookInfo:
    """What the gate knows about one hook: read from platform/hooks.json."""

    name: str
    kind: str
    file: str
    function: str
    input_model: str
    output_model: str
    input_fields: tuple[str, ...]
    output_fields: tuple[tuple[str, bool], ...]  # (name, required)
    signature: str
    frame_sha256: str
    limits: dict[str, int]
    sdk_exports: frozenset[str]
    sdk_io: frozenset[str]
    contract_exports: frozenset[str]
    string_fields: frozenset[str] = frozenset()

    @property
    def required_output(self) -> frozenset[str]:
        return frozenset(n for n, req in self.output_fields if req)

    @property
    def output_names(self) -> frozenset[str]:
        return frozenset(n for n, _ in self.output_fields)


def hook_from_manifest(manifest: dict[str, Any], raw: dict[str, Any]) -> HookInfo:
    limits = {**DEFAULT_LIMITS, **{k: int(v) for k, v in manifest.get("limits", {}).items()}}
    return HookInfo(
        name=raw["name"],
        kind=raw["kind"],
        file=raw["file"],
        function=raw["function"],
        input_model=raw["input_model"],
        output_model=raw["output_model"],
        input_fields=tuple(f["name"] for f in raw["input_fields"]),
        output_fields=tuple((f["name"], bool(f["required"])) for f in raw["output_fields"]),
        signature=raw["signature"],
        frame_sha256=raw["frame_sha256"],
        limits=limits,
        sdk_exports=frozenset(manifest.get("sdk_exports", [])),
        sdk_io=frozenset(manifest.get("sdk_io", [])),
        contract_exports=frozenset(manifest.get("contract_exports", [])),
        string_fields=frozenset(f["name"] for f in raw["input_fields"] if f.get("type") == "string"),
    )


# --- stub frame --------------------------------------------------------------------------------


def body_markers(name: str) -> tuple[str, str]:
    return f"    # <agent:body hook={name}>", "    # </agent:body>"


def split_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").split("\n")


def body_range(lines: list[str], name: str) -> tuple[int, int] | None:
    """(index of the open marker, index of the close marker) when there is exactly one of each."""
    open_marker, close_marker = body_markers(name)
    opens = [i for i, line in enumerate(lines) if line == open_marker]
    closes = [i for i, line in enumerate(lines) if line == close_marker]
    spoofs = [i for i, line in enumerate(lines) if "agent:body" in line]
    if len(opens) != 1 or len(closes) != 1 or len(spoofs) != 2 or opens[0] >= closes[0]:
        return None
    return opens[0], closes[0]


def frame_hash(text: str, name: str) -> str | None:
    """SHA-256 of the stub with its body replaced by a placeholder; None if the markers are bad."""
    lines = split_lines(text)
    found = body_range(lines, name)
    if found is None:
        return None
    start, end = found
    frame = [*lines[: start + 1], BODY_PLACEHOLDER, *lines[end:]]
    return hashlib.sha256("\n".join(frame).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# --- the per-file checks -----------------------------------------------------------------------


def check_source(source: bytes | str, hook: HookInfo, path: str) -> list[Finding]:
    """G0-G7 (frame part) for one hook file. `path` is only used in findings."""
    found: list[Finding] = []

    def add(rule: str, line: int, message: str) -> None:
        found.append(Finding(rule, path, line, message))

    text = _decode(source, hook, add)
    if text is None:
        return _dedupe(found)
    lines = split_lines(text)
    signature_lines = [i for i, line in enumerate(lines) if line == hook.signature]
    if len(signature_lines) != 1:
        add("G0.signature", 1, "the signature line of the stub is missing, changed or repeated")
    markers = body_range(lines, hook.name)
    if markers is None:
        add("G0.markers", 1, "the body markers are missing, repeated or out of order")
    elif frame_hash(text, hook.name) != hook.frame_sha256:
        add("G7.frame_changed", 1, "the file differs from the stub outside the marked body")
    tree = _parse(text, add)
    if tree is None:
        return _dedupe(found)
    sig_line = signature_lines[0] + 1 if len(signature_lines) == 1 else 0
    func = _check_structure(tree, hook, sig_line, add)
    aliases, sdk_names, named = _check_imports(tree, hook, add)
    _guarded(_check_names, "G6.nesting", add, tree, hook, aliases, sdk_names, add)
    _guarded(_check_bounds, "G6.nesting", add, tree, hook, aliases, named, add)
    if func is not None:
        _guarded(_check_contract, "G6.nesting", add, func, hook, add)
    _guarded(_check_complexity, "G6.nesting", add, tree, func, hook, lines, markers, add)
    return _dedupe(found)


def _dedupe(found: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, int, str]] = set()
    out: list[Finding] = []
    for f in found:
        key = (f.rule, f.line, f.message)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return sorted(out, key=lambda f: (f.rule, f.line, f.message))


def _guarded(fn: Any, rule: str, add: Any, *args: Any) -> None:
    try:
        fn(*args)
    except RecursionError:
        add(rule, 1, "the code is nested too deeply to analyse")


def _decode(source: bytes | str, hook: HookInfo, add: Any) -> str | None:
    limit = hook.limits["max_file_bytes"]
    raw = source.encode("utf-8", "surrogatepass") if isinstance(source, str) else source
    if len(raw) > limit:
        add("G0.size", 1, f"the file is larger than {limit} bytes")
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        add("G0.encoding", 1, "the file is not valid UTF-8")
        return None
    if text.startswith("﻿"):
        add("G0.encoding", 1, "a byte order mark is not allowed")
        return None
    normalised = text.replace("\r\n", "\n")
    bad = _BAD_TEXT_CHARS.search(normalised)
    if bad is not None:
        line = normalised.count("\n", 0, bad.start()) + 1
        add("G0.encoding", line, "control characters and unusual line breaks are not allowed")
        return None
    for number, line_text in enumerate(normalised.split("\n")[:2], start=1):
        cookie = _CODING_COOKIE.match(line_text)
        if cookie is not None and cookie.group(1).lower().replace("_", "-") not in ("utf-8", "utf8"):
            add("G0.encoding", number, "an encoding declaration other than UTF-8 is not allowed")
            return None
    return normalised


def _parse(text: str, add: Any) -> ast.Module | None:
    try:
        return ast.parse(text, filename="<hook>", type_comments=False)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        line = getattr(exc, "lineno", None)
        add("G0.syntax", line if isinstance(line, int) else 1, f"does not parse ({type(exc).__name__})")
        return None


def _check_structure(
    tree: ast.Module, hook: HookInfo, sig_line: int, add: Any
) -> ast.FunctionDef | None:
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    named = [f for f in funcs if f.name == hook.function]
    seen_function = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name != hook.function:
                add("G0.structure", node.lineno, "only the hook function may be defined at top level")
            seen_function = True
        elif isinstance(node, ast.Import | ast.ImportFrom):
            if seen_function:
                add("G0.structure", node.lineno, "imports belong above the hook function")
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        else:
            add("G0.structure", node.lineno, "code outside the hook function")
    if len(named) != 1 or not isinstance(named[0], ast.FunctionDef):
        add("G5.function", 1, f"expected exactly one plain function named {_safe(hook.function)}")
        return None
    func = named[0]
    if sig_line and func.lineno != sig_line:
        add("G0.signature", func.lineno, "the function is not defined on the fixed signature line")
    _check_signature(func, hook, add)
    return func


def _check_signature(func: ast.FunctionDef, hook: HookInfo, add: Any) -> None:
    a = func.args
    plain = (
        len(a.args) == 1
        and not a.posonlyargs
        and not a.kwonlyargs
        and a.vararg is None
        and a.kwarg is None
        and not a.defaults
        and a.args[0].arg == "data"
    )
    typed = (
        plain
        and isinstance(a.args[0].annotation, ast.Name)
        and a.args[0].annotation.id == hook.input_model
        and isinstance(func.returns, ast.Name)
        and func.returns.id == hook.output_model
    )
    if not typed:
        add(
            "G5.signature",
            func.lineno,
            f"expected def {_safe(hook.function)}(data: {_safe(hook.input_model)}) "
            f"-> {_safe(hook.output_model)}",
        )
    if func.decorator_list:
        add("G2.decorator", func.lineno, "decorators are not allowed")


# --- G1 imports --------------------------------------------------------------------------------


def _module_rule(module: str) -> str | None:
    """The rule an import of `module` breaks, or None when the module itself is allowed."""
    if module in ALLOWED_MODULES or module in (SDK_MODULE, CONTRACTS_MODULE):
        return None
    root = module.split(".")[0]
    if root in BANNED_MODULES:
        return "G1.banned_import"
    if root in NETWORK_MODULES:
        return "G1.network_import"
    if root in NONDETERMINISTIC_MODULES:
        return "G4.nondeterministic_import"
    if root == "app":
        return "G1.layer_import"
    return "G1.not_allowed_import"


def _allowed_names(module: str, hook: HookInfo) -> frozenset[str] | None:
    if module == SDK_MODULE:
        return hook.sdk_exports
    if module == CONTRACTS_MODULE:
        return hook.contract_exports
    return ALLOWED_MODULES.get(module)


def _check_imports(
    tree: ast.Module, hook: HookInfo, add: Any
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Check every import anywhere in the tree (also inside functions and try blocks).
    Returns (local name -> module for `import m` / `import m as a`,
    local name -> original name for `from app.platform_sdk import name`,
    local name -> "module.name" for every allowed `from m import name`)."""
    aliases: dict[str, str] = {}
    sdk_names: dict[str, str] = {}
    named: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                rule = _module_rule(alias.name)
                if rule is not None:
                    add(rule, node.lineno, f"import of {_safe(alias.name)}")
                    continue
                if alias.asname is None and "." in alias.name:
                    add("G1.not_allowed_import", node.lineno, f"import of {_safe(alias.name)}")
                    continue
                aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                add("G1.relative_import", node.lineno, "relative import")
                continue
            module = node.module or ""
            rule = _module_rule(module)
            if rule is not None:
                add(rule, node.lineno, f"import from {_safe(module)}")
                continue
            allowed = _allowed_names(module, hook)
            for alias in node.names:
                if alias.name == "*":
                    add("G1.star_import", node.lineno, f"star import from {_safe(module)}")
                elif allowed is not None and alias.name not in allowed:
                    add(
                        "G1.name_not_allowed",
                        node.lineno,
                        f"{_safe(module)}.{_safe(alias.name)} is not on the allow-list",
                    )
                else:
                    named[alias.asname or alias.name] = f"{module}.{alias.name}"
                    if module == SDK_MODULE:
                        sdk_names[alias.asname or alias.name] = alias.name
    return aliases, sdk_names, named


# --- G2 / G3 / G4 names, attributes, calls ----------------------------------------------------


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _looks_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


def _str_const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _check_names(
    tree: ast.Module,
    hook: HookInfo,
    aliases: dict[str, str],
    sdk_names: dict[str, str],
    add: Any,
) -> None:
    sdk_aliases = {a for a, m in aliases.items() if m == SDK_MODULE}
    module_aliases = set(aliases)
    direct = _direct_uses(tree)
    receivers = _receivers(tree, module_aliases)
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 1)
        if isinstance(node, ast.Name):
            _check_name(node, hook, sdk_names, add)
            if node.id in _CALL_ONLY and id(node) not in direct:
                add("G2.dynamic_attr", line, f"{_safe(node.id)} may only be called directly")
            if node.id in module_aliases and id(node) not in receivers:
                add("G1.module_value", line, f"module {_safe(node.id)} used as a value")
        elif isinstance(node, ast.Attribute):
            _check_attribute(node, hook, aliases, sdk_aliases, add)
            if node.attr in FORMAT_ATTRS:
                add("G2.format_call", line, "format and format_map are not allowed: use an f-string")
        elif isinstance(node, ast.JoinedStr):
            _check_fstring(node, add)
        elif isinstance(node, ast.arg):
            if node.arg.startswith("__"):
                add("G2.dunder", line, "dunder names are not allowed")
        elif isinstance(node, ast.FunctionDef):
            if node.name.startswith("__"):
                add("G2.dunder", line, "dunder names are not allowed")
            if node.decorator_list:
                add("G2.decorator", line, "decorators are not allowed")
        elif isinstance(node, ast.ClassDef):
            add("G2.class_def", line, "class definitions are not allowed")
        elif isinstance(
            node, ast.AsyncFunctionDef | ast.Await | ast.AsyncFor | ast.AsyncWith | ast.Yield | ast.YieldFrom
        ):
            add("G2.async_syntax", line, "async, await and yield are not allowed")
        elif isinstance(node, ast.Global | ast.Nonlocal):
            add("G4.global_write", line, "global and nonlocal are not allowed")
        elif isinstance(node, ast.Call):
            _check_call(node, hook, add)
        elif isinstance(node, ast.Subscript):
            _check_subscript(node, add)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _looks_secret(node.value):
                add("G3.secret_literal", line, "a secret-looking literal (value not shown)")
            _check_string(node.value, line, add)
        elif isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign | ast.Delete):
            _check_stores(node, module_aliases, add)


_CALL_ONLY = frozenset({"pow", "iter", "range"})


def _direct_uses(tree: ast.Module) -> set[int]:
    """ids of the Name nodes that are the called function of a Call, for the few built-ins that
    are safe only when called directly with arguments the gate can check."""
    direct: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _CALL_ONLY:
            direct.add(id(node.func))
    return direct


def _receivers(tree: ast.Module, module_aliases: set[str]) -> set[int]:
    """ids of the Name nodes that are exactly `alias` in a read of `alias.attr`: the only way a
    module object may appear. (Which attr is allowed is checked by `_check_attribute`.)"""
    out: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Name)
            and node.value.id in module_aliases
        ):
            out.add(id(node.value))
    return out


def _check_string(text: str, line: int, add: Any) -> None:
    """A string that could steer a formatter: field traversals, dunders, `%*d` and huge widths."""
    if "__" in text or _FORMAT_FIELD.search(text) is not None:
        add("G2.format_string", line, "a string that looks like a format-field traversal or a dunder")
    elif _PCT_WIDTH.search(text) is not None:
        add("G2.format_string", line, "a format width that could allocate too much")


def _check_fstring(node: ast.JoinedStr, add: Any) -> None:
    """f"{x:>{w}}" and f"{x:>999999999}" pad to a size the data (or the author) picks."""
    for part in node.values:
        spec = part.format_spec if isinstance(part, ast.FormattedValue) else None
        if spec is None:
            continue
        for item in ast.walk(spec):
            if isinstance(item, ast.FormattedValue):
                add("G6.iteration_bound", node.lineno, "a format width must be a literal")
            elif isinstance(item, ast.Constant) and isinstance(item.value, str) and _SPEC_WIDTH.search(item.value):
                add("G6.iteration_bound", node.lineno, "a format width could allocate too much")


def _check_name(node: ast.Name, hook: HookInfo, sdk_names: dict[str, str], add: Any) -> None:
    ident = node.id
    if ident in BANNED_NAMES:
        add("G2.banned_name", node.lineno, f"{_safe(ident)} is not allowed")
    elif ident.startswith("__"):
        add("G2.dunder", node.lineno, "dunder names are not allowed")
    elif ident in IO_NAMES:
        add("G4.io_call", node.lineno, f"{_safe(ident)} is I/O: use the SDK logger")
    elif ident in NONDETERMINISTIC_NAMES:
        add("G4.nondeterministic_call", node.lineno, f"{_safe(ident)} differs between runs")
    elif ident in TOKEN_NAMES:
        add("G3.raw_token_name", node.lineno, f"{_safe(ident)}: hooks get typed input only")
    if sdk_names.get(ident) in hook.sdk_io and hook.kind == "pure":
        add("G4.sdk_io", node.lineno, f"{_safe(ident)} does I/O: not allowed in a pure hook")


def _check_attribute(
    node: ast.Attribute,
    hook: HookInfo,
    aliases: dict[str, str],
    sdk_aliases: set[str],
    add: Any,
) -> None:
    attr = node.attr
    line = node.lineno
    from_sdk = isinstance(node.value, ast.Name) and node.value.id in sdk_aliases
    if attr.startswith("__"):
        add("G2.dunder", line, "dunder attributes are not allowed")
    elif attr.startswith("_"):
        add("G2.private_attr", line, "private attributes are not allowed")
    elif attr in INTROSPECTION_ATTRS or (attr.startswith("model_") and attr not in ALLOWED_MODEL_ATTRS):
        add("G2.introspection_attr", line, f"{_safe(attr)} is not allowed")
    elif attr in NONDETERMINISTIC_ATTRS and not from_sdk:
        add("G4.nondeterministic_call", line, f"{_safe(attr)} differs between runs: pass it in")
    elif attr in ("headers", "cookies", "claims", "authorization", "access_token", "id_token",
                  "refresh_token"):
        add("G3.raw_token_name", line, f"{_safe(attr)}: hooks get typed input only")
    if isinstance(node.value, ast.Name):
        module = aliases.get(node.value.id)
        if module is not None:
            allowed = _allowed_names(module, hook)
            if allowed is not None and attr not in allowed and not attr.startswith("_"):
                add("G1.name_not_allowed", line, f"{_safe(module)}.{_safe(attr)} is not on the allow-list")
            if from_sdk and attr in hook.sdk_io and hook.kind == "pure":
                add("G4.sdk_io", line, f"{_safe(attr)} does I/O: not allowed in a pure hook")


def _check_call(node: ast.Call, hook: HookInfo, add: Any) -> None:
    func = node.func
    line = node.lineno
    if isinstance(func, ast.Name) and func.id == "pow":
        if len(node.args) != 2 or node.keywords:
            add("G6.iteration_bound", line, "pow takes exactly two arguments (no modulus form)")
        elif not _small_exponent(node.args[1]):
            add("G6.iteration_bound", line, "pow needs a small constant exponent")
    if isinstance(func, ast.Attribute) and func.attr in ("get", "pop", "setdefault") and node.args:
        _check_key(_str_const(node.args[0]), line, add)


def _check_key(key: str | None, line: int, add: Any) -> None:
    if key is None:
        return
    lowered = key.lower()
    if key in IDENTITY_KEYS:
        add("G3.raw_claims", line, f"raw token claim {_safe(key)}: use the Principal from the SDK")
    elif lowered in HEADER_KEYS:
        add("G3.raw_header", line, f"raw request header {_safe(lowered)}")


def _check_subscript(node: ast.Subscript, add: Any) -> None:
    _check_key(_str_const(node.slice), node.lineno, add)


def _check_stores(
    node: ast.Assign | ast.AugAssign | ast.AnnAssign | ast.Delete,
    module_aliases: set[str],
    add: Any,
) -> None:
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
        value = node.value
        for target in targets:
            text = _str_const(value)
            if (
                isinstance(target, ast.Name)
                and text is not None
                and len(text) >= 6
                and any(w in target.id.lower() for w in SECRET_WORDS)
            ):
                add("G3.secret_literal", node.lineno, f"a literal assigned to {_safe(target.id)} (value not shown)")
    elif isinstance(node, ast.AugAssign | ast.AnnAssign):
        targets = [node.target]
    elif isinstance(node, ast.Delete):
        targets = list(node.targets)
    pending = list(targets)
    while pending:
        target = pending.pop()
        if isinstance(target, ast.Tuple | ast.List):
            pending.extend(target.elts)
            continue
        if isinstance(target, ast.Starred):
            pending.append(target.value)
            continue
        if not isinstance(target, ast.Attribute | ast.Subscript):
            continue
        root = _root_name(target)
        if root == "data":
            add("G4.input_write", node.lineno, "the input model is read-only")
        elif root in module_aliases:
            add("G4.module_write", node.lineno, f"writing to {_safe(root)}")


# --- G5 contract -------------------------------------------------------------------------------


def _own_nodes(func: ast.FunctionDef) -> list[ast.AST]:
    """Nodes of the function without descending into nested functions, lambdas or classes."""
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


def _terminates(stmts: list[ast.stmt]) -> bool:
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, ast.Return | ast.Raise):
        return True
    if isinstance(last, ast.If):
        return bool(last.orelse) and _terminates(last.body) and _terminates(last.orelse)
    if isinstance(last, ast.Try):
        if last.finalbody and _terminates(last.finalbody):
            return True
        branches = [last.body, *[h.body for h in last.handlers]]
        if last.orelse:
            branches[0] = [*last.body, *last.orelse]
        return all(_terminates(b) for b in branches)
    if isinstance(last, ast.With):
        return _terminates(last.body)
    return False


def _is_not_implemented(func: ast.FunctionDef) -> bool:
    body = [
        s
        for s in func.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) and not isinstance(s, ast.Pass)
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Raise):
        return False
    exc = body[0].exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"


def _return_problem(value: ast.expr | None, hook: HookInfo, local_defs: set[str]) -> str | None:
    if value is None:
        return "a bare return"
    if isinstance(value, ast.IfExp):
        return _return_problem(value.body, hook, local_defs) or _return_problem(
            value.orelse, hook, local_defs
        )
    if isinstance(value, ast.Name):
        return None  # a variable: its value is checked when the model is built
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Attribute):
            return None  # a method of something that came from the input or a model
        if isinstance(func, ast.Name) and (func.id == hook.output_model or func.id in local_defs):
            return None
        return f"a call to {_safe(getattr(func, 'id', 'something'))}, not the output model"
    return "a value that is not the output model"


def _check_contract(func: ast.FunctionDef, hook: HookInfo, add: Any) -> None:
    own = _own_nodes(func)
    local_defs = {n.name for n in ast.walk(func) if isinstance(n, ast.FunctionDef) and n is not func}
    if _is_not_implemented(func):
        add("G5.not_implemented", func.lineno, "the body is still the stub: write the logic")
        return
    returns = [n for n in own if isinstance(n, ast.Return)]
    for ret in returns:
        problem = _return_problem(ret.value, hook, local_defs)
        if problem is not None:
            add("G5.return_type", ret.lineno, f"{problem}; return {_safe(hook.output_model)}(...)")
    if not _terminates(func.body):
        add("G5.missing_return", func.lineno, "the function can end without returning")
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == hook.output_model
        ):
            _check_output_call(node, hook, add)
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "data"
            and not node.attr.startswith("_")
            and node.attr not in hook.input_fields
            and node.attr != "model_dump"
        ):
            add(
                "G5.unknown_input_field",
                node.lineno,
                f"{_safe(hook.input_model)} has no field {_safe(node.attr)}",
            )


def _check_output_call(node: ast.Call, hook: HookInfo, add: Any) -> None:
    if node.args:
        add("G5.output_positional", node.lineno, "build the output model with keyword arguments")
    if any(k.arg is None for k in node.keywords) or any(isinstance(a, ast.Starred) for a in node.args):
        return  # ** or * expansion: checked by the model at run time
    given = {k.arg for k in node.keywords if k.arg is not None}
    for name in sorted(given - hook.output_names):
        add("G5.output_fields", node.lineno, f"{_safe(hook.output_model)} has no field {_safe(name)}")
    for name in sorted(hook.required_output - given):
        add("G5.output_fields", node.lineno, f"{_safe(hook.output_model)} needs the field {_safe(name)}")


# --- G6 complexity -----------------------------------------------------------------------------


def _const_int(node: ast.AST) -> int | None:
    """A small constant integer expression, or None. Never evaluates anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _const_int(node.operand)
        return -inner if inner is not None else None
    if isinstance(node, ast.BinOp):
        left, right = _const_int(node.left), _const_int(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Pow) and 0 <= right <= 64 and abs(left) <= 10**6:
            return int(left**right)
    return None


def _iterations(iterable: ast.AST) -> int:
    """How many times a `for` over this iterable can run, when that is knowable from literals."""
    if isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Name) and iterable.func.id == "range":
        values = [_const_int(a) for a in iterable.args]
        if not iterable.args or len(iterable.args) > 3 or any(v is None for v in values):
            return 1
        ints = [v for v in values if v is not None]
        start, stop, step = (0, ints[0], 1) if len(ints) == 1 else (ints[0], ints[1], ints[2] if len(ints) == 3 else 1)
        if step == 0:
            return 1
        return max(0, -(-(stop - start) // step)) if step > 0 else max(0, -(-(start - stop) // -step))
    if isinstance(iterable, ast.List | ast.Tuple | ast.Set):
        return max(1, len(iterable.elts))
    return 1


def _loop_stats(node: ast.AST, depth: int, product: int, stats: dict[str, int]) -> None:
    """Deepest loop nesting and largest product of literal iteration counts along any path."""
    loops: list[tuple[ast.AST, int]] = []
    if isinstance(node, ast.For):
        loops.append((node.iter, _iterations(node.iter)))
    elif isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
        loops.extend((g.iter, _iterations(g.iter)) for g in node.generators)
    for _, count in loops:
        depth += 1
        product *= max(1, count)
    if loops:
        stats["depth"] = max(stats["depth"], depth)
        stats["product"] = max(stats["product"], product)
    if isinstance(node, ast.While):
        depth += 1
        stats["depth"] = max(stats["depth"], depth)
    for child in ast.iter_child_nodes(node):
        _loop_stats(child, depth, product, stats)


def _recursion_problems(tree: ast.AST, hook_func: ast.FunctionDef | None) -> list[tuple[int, str]]:
    """Recursion in any form the syntax shows: a function that mentions itself (or an alias of itself,
    or a function that mentions it) anywhere in its body, a nested function that calls one of its own
    parameters (the Y-combinator form) and a nested function that calls a subscript or a call result."""
    problems: list[tuple[int, str]] = []
    defs: dict[str, ast.AST] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            defs[n.name] = n
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    defs[t.id] = n.value
    changed = True
    while changed:  # `g = f` makes g another name of f
        changed = False
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) and n.value.id in defs:
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id not in defs:
                        defs[t.id] = defs[n.value.id]
                        changed = True
    graph = {
        name: {x.id for x in ast.walk(node) if isinstance(x, ast.Name) and x.id in defs}
        for name, node in defs.items()
    }
    if _has_cycle(graph):
        problems.append((getattr(tree, "lineno", 1), "a function refers to itself, directly or not"))
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.Lambda) or fn is hook_func:
            continue
        a = fn.args
        params = {x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs)}
        params |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            callee = call.func
            if isinstance(callee, ast.Name) and callee.id in params:
                problems.append((call.lineno, "a function calls its own parameter (hidden recursion)"))
            elif isinstance(callee, ast.Subscript | ast.Call):
                problems.append((call.lineno, "a function calls a computed callable (hidden recursion)"))
    return problems


def _has_cycle(graph: dict[str, set[str]]) -> bool:
    state: dict[str, int] = {}
    for start in graph:
        if state.get(start):
            continue
        stack: list[tuple[str, list[str]]] = [(start, sorted(graph.get(start, ())))]
        state[start] = 1
        while stack:
            node, pending = stack[-1]
            if not pending:
                state[node] = 2
                stack.pop()
                continue
            nxt = pending.pop()
            if state.get(nxt) == 1:
                return True
            if not state.get(nxt):
                state[nxt] = 1
                stack.append((nxt, sorted(graph.get(nxt, ()))))
    return False


def _check_complexity(
    tree: ast.Module,
    func: ast.FunctionDef | None,
    hook: HookInfo,
    lines: list[str],
    markers: tuple[int, int] | None,
    add: Any,
) -> None:
    limits = hook.limits
    root: ast.AST = func if func is not None else tree
    nodes = sum(1 for _ in ast.walk(root))
    if nodes > limits["max_ast_nodes"]:
        add("G6.nodes", getattr(root, "lineno", 1), f"{nodes} nodes; the budget is {limits['max_ast_nodes']}")
    if markers is not None and markers[1] - markers[0] - 1 > limits["max_body_lines"]:
        add("G6.body_lines", markers[0] + 1, f"more than {limits['max_body_lines']} lines")
    grow = _Growth(_sequence_names(root, hook), root)
    looped = _inside_loops(root)
    stats = {"depth": 0, "product": 1}
    _loop_stats(root, 0, 1, stats)
    if stats["depth"] > limits["max_loop_depth"]:
        add("G6.loop_depth", getattr(root, "lineno", 1), f"loops nested deeper than {limits['max_loop_depth']}")
    if stats["product"] > limits["max_iterations"]:
        add("G6.iteration_bound", getattr(root, "lineno", 1), "loops over literal ranges could run too long")
    for node in ast.walk(root):
        if isinstance(node, ast.While):
            add("G6.while_loop", node.lineno, "while loops are not allowed")
        elif isinstance(node, ast.BinOp):
            _check_blowup(node.op, node.left, node.right, node.lineno, grow, hook, add)
        elif isinstance(node, ast.AugAssign):
            _check_blowup(node.op, node.target, node.value, node.lineno, grow, hook, add)
            if id(node) in looped and isinstance(node.op, ast.Add) and _same_name(node.target, node.value):
                add("G6.iteration_bound", node.lineno, "a value that doubles itself in a loop")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str | bytes)
            and len(node.value) > limits["max_string"]
        ):
            add("G6.literal_size", node.lineno, f"a literal longer than {limits['max_string']}")
    for node in ast.walk(root):
        if id(node) in looped:
            if isinstance(node, ast.BinOp) and (
                (isinstance(node.op, ast.Mult) and (_seqish(node.left, grow.names, hook) or _seqish(node.right, grow.names, hook)))
                or (isinstance(node.op, ast.Add) and _same_name(node.left, node.right))
            ):
                add("G6.iteration_bound", node.lineno, "a sequence repeated or doubled inside a loop")
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.BinOp):
                self_ref = any(
                    isinstance(t, ast.Name) and isinstance(node.value.op, ast.Add)
                    and (_same_name(t, node.value.left) and _same_name(t, node.value.right))
                    for t in node.targets
                )
                if self_ref:
                    add("G6.iteration_bound", node.lineno, "a value that doubles itself in a loop")
    for line, message in _recursion_problems(tree, func):
        add("G6.recursion", line, message)


_STR_METHODS = frozenset(
    """join strip lstrip rstrip lower upper title capitalize casefold replace split rsplit splitlines
    ljust rjust center zfill encode decode copy partition rpartition removeprefix removesuffix
    swapcase translate expandtabs""".split()
)
_SEQ_BUILTINS = frozenset({"str", "list", "tuple", "sorted", "reversed"})
_CONSUMERS = frozenset(
    {"sum", "max", "min", "sorted", "list", "tuple", "set", "frozenset", "dict", "any", "all",
     "enumerate", "zip", "map", "filter", "len"}
)


def _seqish(node: ast.AST, names: set[str], hook: HookInfo) -> bool:
    """True when the expression is, by its shape, a string, bytes, list or tuple (best effort: the gate
    has no types, so a sequence hidden behind a call to a hook-local function is not seen)."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str | bytes)
    if isinstance(node, ast.JoinedStr | ast.List | ast.Tuple | ast.ListComp):
        return True
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id in _SEQ_BUILTINS
        return isinstance(f, ast.Attribute) and f.attr in _STR_METHODS
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) and node.value.id == "data" and node.attr in hook.string_fields
    if isinstance(node, ast.Subscript):
        return _seqish(node.value, names, hook)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Mod):
        return _seqish(node.left, names, hook)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _seqish(node.left, names, hook) or _seqish(node.right, names, hook)
    if isinstance(node, ast.IfExp):
        return _seqish(node.body, names, hook) or _seqish(node.orelse, names, hook)
    return False


def _sequence_names(root: ast.AST, hook: HookInfo) -> set[str]:
    """Names that are assigned a sequence-shaped value anywhere (flow-insensitive, to a fixed point)."""
    names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for n in ast.walk(root):
            pairs: list[tuple[ast.expr, ast.expr | None]] = []
            if isinstance(n, ast.Assign):
                pairs = [(t, n.value) for t in n.targets]
            elif isinstance(n, ast.AnnAssign | ast.AugAssign):
                pairs = [(n.target, n.value)]
            for target, value in pairs:
                if (
                    isinstance(target, ast.Name)
                    and value is not None
                    and target.id not in names
                    and _seqish(value, names, hook)
                ):
                    names.add(target.id)
                    changed = True
    return names


def _same_name(a: ast.AST, b: ast.AST) -> bool:
    return isinstance(a, ast.Name) and isinstance(b, ast.Name) and a.id == b.id


def _inside_loops(root: ast.AST) -> set[int]:
    """ids of every node inside a `for`/`while` body or a comprehension."""
    out: set[int] = set()
    for node in ast.walk(root):
        if isinstance(node, ast.For | ast.While | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            for inner in ast.walk(node):
                if inner is not node:
                    out.add(id(inner))
    return out


class _Growth:
    """Sequence-shaped names, and the ones that already are the result of a repetition."""

    def __init__(self, names: set[str], root: ast.AST) -> None:
        self.names = names
        self.repeated: set[str] = set()
        for n in ast.walk(root):
            value = n.value if isinstance(n, ast.Assign) else None
            if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mult):
                self.repeated.update(t.id for t in n.targets if isinstance(t, ast.Name))  # type: ignore[attr-defined]
            if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Mult) and isinstance(n.target, ast.Name):
                self.repeated.add(n.target.id)


def _small_exponent(node: ast.AST) -> bool:
    value = _const_int(node)
    if value is not None:
        return -64 <= value <= 64
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, float)
        and not isinstance(node.value, bool)
        and abs(node.value) <= 64
    )


def _check_blowup(
    op: ast.operator, left: ast.expr, right: ast.expr, line: int, grow: _Growth, hook: HookInfo, add: Any
) -> None:
    small = hook.limits["max_small"]
    if isinstance(op, ast.Mult):
        for sequence, count in ((left, right), (right, left)):
            n = _const_int(count)
            if _seqish(sequence, grow.names, hook):
                if n is None or abs(n) > small:
                    add("G6.iteration_bound", line, "a string or list repeated a number of times the gate cannot bound")
                elif n > 1 and (
                    (isinstance(sequence, ast.Name) and sequence.id in grow.repeated)
                    or (isinstance(sequence, ast.BinOp) and isinstance(sequence.op, ast.Mult))
                ):
                    add("G6.iteration_bound", line, "a repeated sequence repeated again")
    elif isinstance(op, ast.Pow):
        if not _small_exponent(right):
            add("G6.iteration_bound", line, "** needs a constant exponent between -64 and 64")
    elif isinstance(op, ast.LShift):
        n = _const_int(right)
        if n is None or not 0 <= n <= 64:
            add("G6.iteration_bound", line, "<< needs a constant shift of at most 64")


def _origin(node: ast.AST, aliases: dict[str, str], named: dict[str, str]) -> str | None:
    """"module.name" for a read of an allowed `from m import name` name or of `alias.name`."""
    if isinstance(node, ast.Name):
        return named.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        module = aliases.get(node.value.id)
        return f"{module}.{node.attr}" if module is not None else None
    return None


def _bounded(node: ast.AST, small: int) -> bool:
    """A size the gate can bound: a small literal, `len(...)`, or sums/min of those."""
    value = _const_int(node)
    if value is not None:
        return abs(value) <= small
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "len":
            return True
        if node.func.id == "min":
            return any(_bounded(a, small) for a in node.args)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub):
        return _bounded(node.left, small) and _bounded(node.right, small)
    return False


def _repeat_has_count(call: ast.Call, small: int) -> bool:
    times: ast.expr | None = call.args[1] if len(call.args) >= 2 else None
    for kw in call.keywords:
        if kw.arg == "times":
            times = kw.value
    return times is not None and _bounded(times, small)


def _infinite(node: ast.AST, aliases: dict[str, str], named: dict[str, str], small: int) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Name):
        if f.id == "iter":
            return len(node.args) != 1 or bool(node.keywords)
        if f.id == "range":
            return not node.args or any(not _bounded(a, small) for a in node.args)
    return _origin(f, aliases, named) == "itertools.repeat" and not _repeat_has_count(node, small)


def _check_bounds(
    tree: ast.Module, hook: HookInfo, aliases: dict[str, str], named: dict[str, str], add: Any
) -> None:
    """M-1: a runtime timeout cannot stop a thread, so what could run for ever or allocate without
    limit is refused here, before the code ever runs."""
    small = hook.limits["max_small"]
    counted: set[int] = set()  # ids of `repeat` references that are called with a count
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and _origin(node.func, aliases, named) == "itertools.repeat"
            and _repeat_has_count(node, small)
        ):
            counted.add(id(node.func))
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 1)
        if (
            isinstance(node, ast.Name | ast.Attribute)
            and _origin(node, aliases, named) == "itertools.repeat"
            and id(node) not in counted
        ):
            add("G6.unbounded", line, "repeat needs a literal or len()-based count")
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "iter" and (len(node.args) != 1 or node.keywords):
            add("G6.unbounded", line, "iter with a sentinel can run for ever")
        elif isinstance(f, ast.Name) and f.id == "range":
            if not node.args or any(not _bounded(a, small) for a in node.args):
                add("G6.unbounded", line, f"range bounds must be literals up to {small} or len(...)")
        elif isinstance(f, ast.Name) and f.id in _CONSUMERS:
            for arg in node.args:
                if any(_infinite(inner, aliases, named, small) for inner in ast.walk(arg)):
                    add("G6.unbounded", line, f"{f.id} over an iterator that may not end")
        elif (
            isinstance(f, ast.Attribute)
            and f.attr in SIZE_METHODS
            and (not node.args or not _bounded(node.args[0], small))
        ):
            add("G6.unbounded", line, f"{f.attr} needs a literal size up to {small}")


# --- project level (G7) and the CLI ------------------------------------------------------------


GUARDED_NAMES = frozenset({"conftest.py", "sitecustomize.py", "usercustomize.py", "alembic.ini"})
SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)


def is_guarded_path(rel: str) -> bool:
    """Files that run code or change what runs outside app/ and tests/: migrations, dependency lists,
    images, compose files, pytest/site hooks (at any depth) and `.pth` files. G7 hashes the generated
    ones and rejects new ones."""
    name = rel.rsplit("/", 1)[-1]
    return (
        rel.startswith("alembic/")
        or name in GUARDED_NAMES
        or name.endswith(".pth")
        or (name.startswith("requirements") and name.endswith(".txt"))
        or name.startswith("Dockerfile")
        or (name.startswith("docker-compose") and name.endswith((".yml", ".yaml")))
    )


def _load_json(root: Path, rel: str) -> dict[str, Any] | None:
    try:
        data = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _walk_py(root: Path, top: str) -> list[str]:
    out: list[str] = []
    base = root / top
    if not base.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(".py"):
                out.append(Path(dirpath, name).relative_to(root).as_posix())
    return out


def check_project(
    root: Path, only_hooks: list[str] | None = None
) -> tuple[list[Finding], list[str]]:
    """All gates for a generated project. Returns (findings, names of the hooks checked)."""
    findings: list[Finding] = []
    manifest = _load_json(root, MANIFEST_PATH)
    zones = _load_json(root, ZONES_PATH)
    if manifest is None or zones is None or manifest.get("version") != 1:
        findings.append(Finding("G7.manifest", MANIFEST_PATH, 1, "platform/hooks.json or platform/zones.json is missing or unreadable"))
        return findings, []
    hooks = [hook_from_manifest(manifest, raw) for raw in manifest.get("hooks", [])]
    checked: list[str] = []
    for hook in hooks:
        if only_hooks and hook.name not in only_hooks:
            continue
        checked.append(hook.name)
        findings.extend(_check_hook_file(root, hook))
    declared = {h.file for h in hooks}
    findings.extend(_check_hook_folder(root, declared, manifest))
    findings.extend(_check_generated(root, manifest))
    findings.extend(_check_guarded_strays(root, manifest))
    findings.extend(_check_outside(root, zones, manifest))
    return sorted(findings, key=lambda f: (f.file, f.line, f.rule)), checked


def _check_hook_file(root: Path, hook: HookInfo) -> list[Finding]:
    path = root / hook.file
    if path.is_symlink():
        return [Finding("G7.symlink", hook.file, 1, "the stub is a symbolic link")]
    try:
        raw = path.read_bytes()
    except OSError:
        return [Finding("G0.file_missing", hook.file, 1, f"the stub of {_safe(hook.name)} is missing")]
    return check_source(raw, hook, hook.file)


def _check_hook_folder(root: Path, declared: set[str], manifest: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    locked = set(manifest.get("locked_sha256", {}))
    base = root / HOOK_DIR
    if not base.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            full = Path(dirpath, name)
            rel = full.relative_to(root).as_posix()
            if full.is_symlink():
                out.append(Finding("G7.symlink", rel, 1, "symbolic links are not allowed here"))
            elif rel not in declared and rel not in locked and name != ".gitkeep":
                if name.endswith(".pyc"):
                    continue
                out.append(Finding("G7.undeclared_file", rel, 1, "no declared hook owns this file"))
    return out


def _check_generated(root: Path, manifest: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    expected: dict[str, str] = {
        **manifest.get("generated_sha256", {}),
        **manifest.get("locked_sha256", {}),
        **manifest.get("guarded_sha256", {}),
    }
    for rel, digest in sorted(expected.items()):
        path = root / rel
        try:
            actual = sha256_text(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            out.append(Finding("G7.generated_missing", rel, 1, "the file is missing or unreadable"))
            continue
        if actual != digest:
            out.append(Finding("G7.generated_modified", rel, 1, "the file differs from what the platform generated"))
    return out


def _check_guarded_strays(root: Path, manifest: dict[str, Any]) -> list[Finding]:
    """A guarded file (see `is_guarded_path`) the platform did not generate, anywhere in the project."""
    known = {**manifest.get("generated_sha256", {}), **manifest.get("locked_sha256", {}), **manifest.get("guarded_sha256", {})}
    out: list[Finding] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath, name)
            rel = full.relative_to(root).as_posix()
            if not is_guarded_path(rel):
                continue
            if full.is_symlink():
                out.append(Finding("G7.symlink", rel, 1, "symbolic links are not allowed here"))
            elif rel not in known:
                out.append(Finding("G7.guarded_new_file", rel, 1, "the platform did not generate this guarded file"))
    return out


def _check_outside(root: Path, zones: dict[str, Any], manifest: dict[str, Any]) -> list[Finding]:
    known = set(zones.get("zones", {}))
    prefixes = tuple(manifest.get("custom_prefixes", []))
    out: list[Finding] = []
    for top in ("app", "tests"):
        for rel in _walk_py(root, top):
            if rel not in known and not rel.startswith(prefixes):
                out.append(Finding("G7.outside_manifest", rel, 1, "not in platform/zones.json and not in a custom zone"))
    return out


def _hook_for_file(manifest: dict[str, Any], rel: str) -> HookInfo | None:
    for raw in manifest.get("hooks", []):
        if raw["file"] == rel:
            return hook_from_manifest(manifest, raw)
    return None


def check_files(root: Path, files: list[str]) -> tuple[list[Finding], list[str]]:
    """Edit precondition for tools that write a stub: check these files only (G0-G6, frame)."""
    manifest = _load_json(root, MANIFEST_PATH)
    if manifest is None or manifest.get("version") != 1:
        return [Finding("G7.manifest", MANIFEST_PATH, 1, "platform/hooks.json is missing or unreadable")], []
    findings: list[Finding] = []
    checked: list[str] = []
    for given in files:
        try:
            rel = Path(given).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            findings.append(Finding("G0.zone", "<outside>", 1, "the file is outside the project"))
            continue
        hook = _hook_for_file(manifest, rel)
        if hook is None:
            findings.append(Finding("G0.zone", rel, 1, "not the stub of a declared hook"))
            continue
        checked.append(hook.name)
        findings.extend(_check_hook_file(root, hook))
    return findings, checked


def report(findings: list[Finding], checked: list[str]) -> dict[str, Any]:
    failed = {f.gate for f in findings}
    return {
        "ok": not findings,
        "gate_version": GATE_VERSION,
        "hooks": checked,
        "gates": {
            g: {"status": "fail" if g in failed else "pass", "means": GATE_MEANING[g]} for g in GATES
        },
        "findings": [f.as_dict() for f in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.platform_gate", description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    parser.add_argument("--file", action="append", default=[], help="check only this stub file")
    parser.add_argument("--hook", action="append", default=[], help="check only this hook")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.file:
            findings, checked = check_files(root, args.file)
        else:
            findings, checked = check_project(root, args.hook or None)
    except Exception as exc:  # the gate could not run: never report that as a pass
        sys.stderr.write(f"gate error: {type(exc).__name__}\n")
        return 2
    sys.stdout.write(json.dumps(report(findings, checked), indent=2, sort_keys=True) + "\n")
    summary = f"{len(findings)} finding(s) in {len(checked)} hook(s)"
    sys.stderr.write(("PASS: " if not findings else "FAIL: ") + summary + "\n")
    for f in findings:
        sys.stderr.write(f"  {f.rule} {f.file}:{f.line} {f.message}\n")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
