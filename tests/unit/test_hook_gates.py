"""Gates G0-G7 for custom hooks: a table of bad bodies (each with the rule it must trigger), good bodies
that must pass, stub-integrity attacks, project-level checks and the command line.

The gate reads source with `ast` only; these tests also prove it never runs what it checks.
"""

import ast
import json
import os
import random
import textwrap
from pathlib import Path
from typing import Any

import pytest

from app.core import hook_gates as gates
from app.core.generator import generate
from app.core.generator.zones import merge_regenerated
from tests.unit.test_generator import load_spec

FILES = generate(load_spec("hooks_invoice"))
MANIFEST: dict[str, Any] = json.loads(FILES["platform/hooks.json"])
GUARD = gates.hook_from_manifest(MANIFEST, MANIFEST["hooks"][0])  # match_invoice, pure
EFFECT = gates.hook_from_manifest(MANIFEST, MANIFEST["hooks"][1])  # notify_approved, effect
GUARD_STUB = FILES["app/custom/hooks/match_invoice.py"]
EFFECT_STUB = FILES["app/custom/hooks/notify_approved.py"]
OK = "return MatchResult(allowed=True)"


def with_body(stub: str, body: str, *, indent: bool = True) -> str:
    """The stub with its marked region replaced by `body` (indented four spaces unless raw)."""
    lines = stub.split("\n")
    start = next(i for i, line in enumerate(lines) if "<agent:body" in line)
    end = next(i for i, line in enumerate(lines) if "</agent:body>" in line)
    text = textwrap.dedent(body).strip("\n")
    new = [("    " + line if line.strip() and indent else line) for line in text.split("\n")]
    return "\n".join([*lines[: start + 1], *new, *lines[end:]])


def rules(source: str | bytes, hook: gates.HookInfo = GUARD) -> set[str]:
    return {f.rule for f in gates.check_source(source, hook, hook.file)}


def check(body: str, hook: gates.HookInfo = GUARD, *, stub: str = GUARD_STUB) -> set[str]:
    return rules(with_body(stub, body), hook)


# --- the stub itself ---------------------------------------------------------------------------


def test_an_untouched_stub_is_only_unimplemented() -> None:
    assert rules(GUARD_STUB) == {"G5.not_implemented"}
    assert rules(EFFECT_STUB, EFFECT) == {"G5.not_implemented"}


def test_every_rule_in_the_table_belongs_to_a_gate() -> None:
    assert {r.split(".")[0] for r in gates.RULES} == set(gates.GATES)
    assert all(gates.RULES.values())


# --- bad bodies: (case id, body, rule that must be reported) ----------------------------------

BAD: list[tuple[str, str, str]] = [
    # G1 imports
    ("import_os", "import os\n" + OK, "G1.banned_import"),
    ("import_os_alias", "import os as o\n" + OK, "G1.banned_import"),
    ("from_os_import", "from os import path\n" + OK, "G1.banned_import"),
    ("import_subprocess", "import subprocess\n" + OK, "G1.banned_import"),
    ("import_socket", "import socket\n" + OK, "G1.banned_import"),
    ("import_sys", "import sys\n" + OK, "G1.banned_import"),
    ("import_ctypes", "import ctypes\n" + OK, "G1.banned_import"),
    ("import_importlib", "import importlib\n" + OK, "G1.banned_import"),
    ("from_importlib", "from importlib import import_module\n" + OK, "G1.banned_import"),
    ("import_pickle", "import pickle\n" + OK, "G1.banned_import"),
    ("import_shelve", "import shelve\n" + OK, "G1.banned_import"),
    ("import_marshal", "import marshal\n" + OK, "G1.banned_import"),
    ("import_builtins", "import builtins\n" + OK, "G1.banned_import"),
    ("from_builtins", "from builtins import eval\n" + OK, "G1.banned_import"),
    ("import_two_one_bad", "import json, os\n" + OK, "G1.banned_import"),
    ("dotted_os", "import os.path\n" + OK, "G1.banned_import"),
    ("import_requests", "import requests\n" + OK, "G1.network_import"),
    ("import_httpx", "import httpx\n" + OK, "G1.network_import"),
    ("import_urllib_request", "import urllib.request\n" + OK, "G1.network_import"),
    ("from_urllib", "from urllib import request\n" + OK, "G1.network_import"),
    ("star_import", "from math import *\n" + OK, "G1.star_import"),
    ("star_import_sdk", "from app.platform_sdk import *\n" + OK, "G1.star_import"),
    ("relative_import", "from . import helpers\n" + OK, "G1.relative_import"),
    ("unknown_library", "import yaml\n" + OK, "G1.not_allowed_import"),
    ("app_layer", "from app.db import session_factory\n" + OK, "G1.layer_import"),
    ("app_models", "from app.models.invoices import Invoice\n" + OK, "G1.layer_import"),
    ("sdk_private_name", "from app.platform_sdk import _internal\n" + OK, "G1.name_not_allowed"),
    ("sdk_leaks_module", "from app.platform_sdk import os\n" + OK, "G1.name_not_allowed"),
    ("sdk_attr_leak", "import app.platform_sdk as sdk\nsdk.os\n" + OK, "G1.name_not_allowed"),
    ("module_name_not_allowed", "from math import sys\n" + OK, "G1.name_not_allowed"),
    ("module_attr_leak", "import statistics\nstatistics.sys\n" + OK, "G1.name_not_allowed"),
    ("dotted_unaliased_allowed_root", "import collections.abc\n" + OK, "G1.not_allowed_import"),
    (
        "import_in_try",
        "try:\n    import os\nexcept ImportError:\n    pass\n" + OK,
        "G1.banned_import",
    ),
    ("import_in_nested_function", "def f():\n    import subprocess\n" + OK, "G1.banned_import"),
    ("import_in_branch", "if data.amount:\n    import socket\n" + OK, "G1.banned_import"),
    ("import_in_lambda_default", "f = (lambda m=__import__('os'): m)\n" + OK, "G2.banned_name"),
    ("dataclasses_exec", "import dataclasses\n" + OK, "G1.banned_import"),
    ("operator_attrgetter", "import operator\n" + OK, "G1.banned_import"),
    ("typing_extensions", "import typing_extensions\n" + OK, "G1.banned_import"),
    ("contextlib", "import contextlib\n" + OK, "G1.banned_import"),
    ("logging_stdlib", "import logging\n" + OK, "G1.banned_import"),
    ("asyncio", "import asyncio\n" + OK, "G1.banned_import"),
    ("threading", "import threading\n" + OK, "G1.banned_import"),
    ("pathlib", "from pathlib import Path\n" + OK, "G1.banned_import"),
    ("typing_get_hints", "from typing import get_type_hints\n" + OK, "G1.name_not_allowed"),
    ("string_formatter", "from string import Formatter\n" + OK, "G1.name_not_allowed"),
    # G2 names and calls
    ("dunder_import_call", "__import__('os')\n" + OK, "G2.banned_name"),
    ("dunder_import_attr", "__import__('os').system('x')\n" + OK, "G2.banned_name"),
    ("getattr_builtins", "getattr(__builtins__, 'eval')\n" + OK, "G2.banned_name"),
    ("getattr_concat", "getattr(data, 'inv' + 'oice_no')\n" + OK, "G2.banned_name"),
    ("getattr_variable", "name = 'amount'\ngetattr(data, name)\n" + OK, "G2.banned_name"),
    ("getattr_dunder_literal", "getattr(data, '__class__')\n" + OK, "G2.banned_name"),
    ("hasattr_dynamic", "hasattr(data, str(1))\n" + OK, "G2.banned_name"),
    ("string_built_eval", "n = 'ev' + 'al'\ngetattr(data, n)\n" + OK, "G2.banned_name"),
    ("eval_call", "eval('1')\n" + OK, "G2.banned_name"),
    ("exec_call", "exec('x = 1')\n" + OK, "G2.banned_name"),
    ("compile_call", "compile('1', 'x', 'eval')\n" + OK, "G2.banned_name"),
    ("open_call", "open('/etc/passwd')\n" + OK, "G2.banned_name"),
    ("eval_alias", "f = eval\nf('1')\n" + OK, "G2.banned_name"),
    ("eval_in_list", "[eval][0]('1')\n" + OK, "G2.banned_name"),
    ("lambda_import", "(lambda: __import__('os'))()\n" + OK, "G2.banned_name"),
    ("setattr_call", "setattr(data, 'amount', 1)\n" + OK, "G2.banned_name"),
    ("globals_call", "globals()['x'] = 1\n" + OK, "G2.banned_name"),
    ("locals_call", "locals()\n" + OK, "G2.banned_name"),
    ("vars_call", "vars(data)\n" + OK, "G2.banned_name"),
    ("dir_call", "dir(data)\n" + OK, "G2.banned_name"),
    ("type_call", "type(data)\n" + OK, "G2.banned_name"),
    ("object_name", "object\n" + OK, "G2.banned_name"),
    ("super_name", "super\n" + OK, "G2.banned_name"),
    ("breakpoint_call", "breakpoint()\n" + OK, "G2.banned_name"),
    ("dunder_class", "data.__class__\n" + OK, "G2.dunder"),
    ("subclasses_walk", "().__class__.__bases__[0].__subclasses__()\n" + OK, "G2.dunder"),
    ("dunder_dict", "data.__dict__\n" + OK, "G2.dunder"),
    ("dunder_name_variable", "__x = 1\n" + OK, "G2.dunder"),
    ("dunder_function_name", "def __sneaky__():\n    return 1\n" + OK, "G2.dunder"),
    ("dunder_argument", "f = lambda __a: __a\n" + OK, "G2.dunder"),
    ("private_attribute", "data._private\n" + OK, "G2.private_attr"),
    ("generator_frame", "(i for i in []).gi_frame\n" + OK, "G2.introspection_attr"),
    ("frame_globals", "x = (i for i in []).gi_frame.f_back.f_globals\n" + OK, "G2.introspection_attr"),
    ("mro_walk", "data.mro\n" + OK, "G2.introspection_attr"),
    ("format_attr_traversal", "'{0.__class__}'.format(data)\n" + OK, "G2.format_call"),
    ("format_dynamic_receiver", "fmt = '{x}'\nfmt.format(x=1)\n" + OK, "G2.format_call"),
    ("format_map", "'{x}'.format_map({'x': 1})\n" + OK, "G2.format_call"),
    ("format_index", "'{0[0]}'.format(['a'])\n" + OK, "G2.format_call"),
    ("format_bound_method", "f = '{0.__class__}'.format\n" + OK, "G2.format_call"),
    ("getattr_via_reduce", "from functools import reduce\nreduce(getattr, ['amount'], data)\n" + OK, "G2.banned_name"),
    ("getattr_via_map", "list(map(getattr, [data], ['amount']))\n" + OK, "G2.banned_name"),
    ("pow_via_map", "list(map(pow, [2], [data.amount]))\n" + OK, "G2.dynamic_attr"),
    ("fullwidth_eval_name", "\uff45val('1')\n" + OK, "G2.banned_name"),
    ("match_statement_class_pattern", "match data:\n    case eval(x=1):\n        pass\n" + OK, "G2.banned_name"),
    ("fstring_expression", "x = f\"{__import__('os')}\"\n" + OK, "G2.banned_name"),
    ("annotation_expression", "def f(a: eval('1')):\n    return a\n" + OK, "G2.banned_name"),
    ("exception_traceback_frame", "try:\n    pass\nexcept Exception as e:\n    e.__traceback__.tb_frame\n" + OK, "G2.dunder"),
    ("class_definition", "class A:\n    pass\n" + OK, "G2.class_def"),
    ("class_with_metaclass", "class A(metaclass=type):\n    pass\n" + OK, "G2.class_def"),
    (
        "decorator_on_nested",
        "def helper(f):\n    return f\n@helper\ndef g():\n    return 1\n" + OK,
        "G2.decorator",
    ),
    ("async_function", "async def g():\n    return 1\n" + OK, "G2.async_syntax"),
    ("yield_expression", "def g():\n    yield 1\n" + OK, "G2.async_syntax"),
    ("await_expression", "def g():\n    await x\n" + OK, "G2.async_syntax"),
    # G3 identity
    ("claims_sub", "claims = {}\nclaims['sub']\n" + OK, "G3.raw_claims"),
    ("claims_name", "claims\n" + OK, "G3.raw_token_name"),
    ("sub_via_get", "d = {}\nd.get('sub')\n" + OK, "G3.raw_claims"),
    ("sid_subscript", "d = {}\nd['sid']\n" + OK, "G3.raw_claims"),
    ("issuer_pop", "d = {}\nd.pop('iss')\n" + OK, "G3.raw_claims"),
    ("request_name", "request.headers\n" + OK, "G3.raw_token_name"),
    ("headers_attr", "data.headers\n" + OK, "G3.raw_token_name"),
    ("authorization_header", "h = {}\nh.get('Authorization')\n" + OK, "G3.raw_header"),
    ("cookie_header", "h = {}\nh['cookie']\n" + OK, "G3.raw_header"),
    ("api_key_header", "h = {}\nh.get('X-Api-Key')\n" + OK, "G3.raw_header"),
    ("access_token_name", "access_token = 1\n" + OK, "G3.raw_token_name"),
    ("jwt_name", "jwt\n" + OK, "G3.raw_token_name"),
    ("aws_key_literal", "k = 'AKIAABCDEFGHIJKLMNOP'\n" + OK, "G3.secret_literal"),
    ("stripe_key_literal", "k = 'sk_live_abcdefgh12345678'\n" + OK, "G3.secret_literal"),
    ("jwt_literal", "k = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig'\n" + OK, "G3.secret_literal"),
    ("password_assignment", "password = 'hunter22'\n" + OK, "G3.secret_literal"),
    ("private_key_literal", "k = '-----BEGIN RSA PRIVATE KEY-----'\n" + OK, "G3.secret_literal"),
    ("hex_literal", "k = '" + "ab12" * 10 + "'\n" + OK, "G3.secret_literal"),
    # G4 purity
    ("print_call", "print(data.amount)\n" + OK, "G4.io_call"),
    ("input_call", "input()\n" + OK, "G4.io_call"),
    ("global_statement", "global counter\ncounter = 1\n" + OK, "G4.global_write"),
    ("nonlocal_statement", "def f():\n    nonlocal x\n" + OK, "G4.global_write"),
    ("module_attribute_write", "import math\nmath.pi = 3\n" + OK, "G4.module_write"),
    ("module_subscript_write", "import json\njson.loads.cache = {}\n" + OK, "G4.module_write"),
    ("input_attribute_write", "data.amount = 1\n" + OK, "G4.input_write"),
    ("input_augmented_write", "data.amount += 1\n" + OK, "G4.input_write"),
    ("input_delete", "del data.amount\n" + OK, "G4.input_write"),
    ("time_import", "import time\n" + OK, "G4.nondeterministic_import"),
    ("random_import", "import random\n" + OK, "G4.nondeterministic_import"),
    ("from_random", "from random import random\n" + OK, "G4.nondeterministic_import"),
    ("secrets_import", "import secrets\n" + OK, "G4.nondeterministic_import"),
    ("datetime_now", "import datetime\ndatetime.datetime.now()\n" + OK, "G4.nondeterministic_call"),
    ("date_today", "from datetime import date\ndate.today()\n" + OK, "G4.nondeterministic_call"),
    ("utcnow", "from datetime import datetime\ndatetime.utcnow()\n" + OK, "G4.nondeterministic_call"),
    ("id_call", "id(data)\n" + OK, "G4.nondeterministic_call"),
    ("hash_call", "hash(data.invoice_no)\n" + OK, "G4.nondeterministic_call"),
    ("sdk_find_rows_in_pure", "from app.platform_sdk import find_rows\nfind_rows('Invoice')\n" + OK, "G4.sdk_io"),
    ("sdk_now_in_pure", "from app.platform_sdk import now\nnow()\n" + OK, "G4.sdk_io"),
    ("sdk_alias_now_in_pure", "import app.platform_sdk as sdk\nsdk.now()\n" + OK, "G4.sdk_io"),
    # G5 contract
    ("return_none", "return None", "G5.return_type"),
    ("bare_return", "return", "G5.return_type"),
    ("return_dict", "return {'allowed': True}", "G5.return_type"),
    ("return_constant", "return True", "G5.return_type"),
    ("return_other_call", "from decimal import Decimal\nreturn Decimal(1)", "G5.return_type"),
    ("return_in_branch_wrong", "if data.amount:\n    return 1\nreturn MatchResult(allowed=True)", "G5.return_type"),
    ("no_return", "x = 1", "G5.missing_return"),
    ("if_without_else", "if data.amount > 0:\n    return MatchResult(allowed=True)", "G5.missing_return"),
    (
        "loop_then_end",
        "for line in [1, 2]:\n    return MatchResult(allowed=True)",
        "G5.missing_return",
    ),
    ("only_raises_not_implemented", "raise NotImplementedError", "G5.not_implemented"),
    ("unknown_output_field", "return MatchResult(allowed=True, bogus=1)", "G5.output_fields"),
    ("missing_output_field", "return MatchResult()", "G5.output_fields"),
    ("positional_output", "return MatchResult(True)", "G5.output_positional"),
    ("unknown_input_field", "x = data.nope\n" + OK, "G5.unknown_input_field"),
    # G6 complexity
    ("while_loop", "while data.amount:\n    break\n" + OK, "G6.while_loop"),
    ("while_true", "while True:\n    pass\n" + OK, "G6.while_loop"),
    ("direct_recursion", "def f(n):\n    return f(n - 1)\n" + OK, "G6.recursion"),
    (
        "mutual_recursion",
        "def a(n):\n    return b(n)\ndef b(n):\n    return a(n)\n" + OK,
        "G6.recursion",
    ),
    (
        "four_nested_loops",
        "for a in [1]:\n for b in [1]:\n  for c in [1]:\n   for d in [1]:\n    pass\n" + OK,
        "G6.loop_depth",
    ),
    (
        "loop_comprehension_depth",
        "x = [1 for a in [1] for b in [1] for c in [1] for d in [1]]\n" + OK,
        "G6.loop_depth",
    ),
    (
        "literal_range_product",
        "for a in range(5000):\n    for b in range(5000):\n        pass\n" + OK,
        "G6.iteration_bound",
    ),
    ("single_huge_range", "for a in range(10**7):\n    pass\n" + OK, "G6.iteration_bound"),
    ("repeated_string", "x = 'ab' * 10**8\n" + OK, "G6.iteration_bound"),
    ("repeated_list", "x = [0] * 5_000_000\n" + OK, "G6.iteration_bound"),
    ("huge_power", "x = 2 ** 100000\n" + OK, "G6.iteration_bound"),
    ("dynamic_power", "x = data.amount ** data.amount\n" + OK, "G6.iteration_bound"),
    ("pow_call", "x = pow(2, data.amount)\n" + OK, "G6.iteration_bound"),
    ("too_many_nodes", "\n".join(f"x{i} = {i} + {i}" for i in range(400)) + "\n" + OK, "G6.nodes"),
    ("too_many_lines", "\n".join(f"x{i} = 1" for i in range(205)) + "\n" + OK, "G6.body_lines"),
    ("huge_literal", "x = '" + "a b " * 800 + "'\n" + OK, "G6.literal_size"),
]


@pytest.mark.parametrize(("case", "body", "rule"), BAD, ids=[c[0] for c in BAD])
def test_a_bad_body_is_rejected_with_its_rule_id(case: str, body: str, rule: str) -> None:
    found = check(body)
    assert rule in found, f"{case}: expected {rule}, got {sorted(found)}"


def test_the_table_covers_every_body_level_rule() -> None:
    covered = {rule for _, _, rule in BAD} | {r for _, _, rules_ in BAD_V2 for r in rules_}
    structural = {
        "G0.syntax", "G0.encoding", "G0.size", "G0.file_missing", "G0.zone", "G0.signature",
        "G0.markers", "G0.structure", "G5.function", "G5.signature", "G7.manifest",
        "G7.undeclared_file", "G7.outside_manifest", "G7.generated_missing",
        "G7.generated_modified", "G7.frame_changed", "G7.symlink", "G7.guarded_new_file",
    }
    assert set(gates.RULES) - covered - structural - {"G6.nesting"} == set(), "a rule has no test case"
    assert len(BAD) >= 40


# --- good bodies -------------------------------------------------------------------------------

GOOD: list[tuple[str, str]] = [
    ("plain_allow", OK),
    (
        "worked_example_style",
        """
        from decimal import Decimal
        from app.platform_sdk import pct_diff

        reasons = []
        if data.amount <= 0:
            reasons.append("amount must be positive")
        if data.po_amount <= 0:
            reasons.append("no purchase order amount")
        elif pct_diff(data.amount, data.po_amount) > Decimal("2"):
            reasons.append("more than 2 percent away from the purchase order")
        if reasons:
            return MatchResult(allowed=False, reason="; ".join(reasons))
        return MatchResult(allowed=True)
        """,
    ),
    (
        "stdlib_mix",
        """
        import itertools
        import json
        import math
        import statistics

        words = data.invoice_no.lower().split("-")
        counts = {w: sum(1 for _ in g) for w, g in itertools.groupby(sorted(words))}
        mean = statistics.mean([len(w) for w in words]) if words else 0
        text = json.dumps({"n": len(counts), "mean": math.floor(mean)})
        return MatchResult(allowed=len(text) > 0, reason=f"{len(counts)} words")
        """,
    ),
    (
        "try_except_and_raise",
        """
        try:
            value = int(data.invoice_no.split("-")[-1])
        except ValueError:
            return MatchResult(allowed=False, reason="invoice number has no digits")
        if value < 0:
            raise ValueError("negative")
        return MatchResult(allowed=True)
        """,
    ),
    (
        "nested_helper_and_lambda",
        """
        def score(n):
            return n * 2

        ordered = sorted([3, 1, 2], key=lambda n: -score(n))
        return MatchResult(allowed=ordered[0] == 6)
        """,
    ),
    (
        "if_else_both_return",
        """
        if data.amount > 0:
            return MatchResult(allowed=True)
        else:
            return MatchResult(allowed=False, reason="no")
        """,
    ),
    (
        "loops_within_bounds",
        """
        total = 0
        for a in range(100):
            for b in range(100):
                total += a * b
        return MatchResult(allowed=total > 0)
        """,
    ),
    (
        "sdk_log_and_helpers",
        """
        from app.platform_sdk import clamp, is_blank, log, slugify

        log.info("checking", invoice=slugify(data.invoice_no))
        if is_blank(data.invoice_no):
            return MatchResult(allowed=False, reason="blank")
        return MatchResult(allowed=clamp(1, 0, 2) == 1)
        """,
    ),
    (
        "sdk_alias_module",
        """
        import app.platform_sdk as sdk

        sdk.log.info("hello")
        return MatchResult(allowed=True)
        """,
    ),
    (
        "model_dump_and_fields",
        """
        values = data.model_dump()
        return MatchResult(allowed=values["amount"] == data.amount)
        """,
    ),
    ("kwargs_expansion", "extra = {'reason': 'ok'}\nreturn MatchResult(allowed=True, **extra)"),
    ("conditional_return", "return MatchResult(allowed=True) if data.amount else MatchResult(allowed=False)"),
    (
        "with_local_variable_named_query",
        "query = data.invoice_no.lower()\nreturn MatchResult(allowed=bool(query))",
    ),
]


@pytest.mark.parametrize(("case", "body"), GOOD, ids=[c[0] for c in GOOD])
def test_a_good_body_passes_every_gate(case: str, body: str) -> None:
    found = gates.check_source(with_body(GUARD_STUB, body), GUARD, GUARD.file)
    assert found == [], f"{case}: {[f.as_dict() for f in found]}"


def test_an_effect_body_may_read_rows_and_the_clock() -> None:
    body = """
    from app.platform_sdk import find_rows, log, now

    rows = find_rows("Invoice", invoice_no=data.invoice_no, limit=5)
    log.info("notified", at=now().isoformat(), same=len(rows))
    return NotifyResult(sent=True)
    """
    assert gates.check_source(with_body(EFFECT_STUB, body), EFFECT, EFFECT.file) == []


def test_clock_and_randomness_modules_are_refused_for_effects_too() -> None:
    body = "import time\nreturn NotifyResult(sent=True)"
    assert "G4.nondeterministic_import" in rules(with_body(EFFECT_STUB, body), EFFECT)
    assert "G4.nondeterministic_call" in rules(
        with_body(EFFECT_STUB, "import datetime\ndatetime.datetime.now()\nreturn NotifyResult(sent=True)"), EFFECT
    )


# --- the stub frame (G0 / G7) ------------------------------------------------------------------


def test_the_body_markers_must_be_intact() -> None:
    no_close = GUARD_STUB.replace("    # </agent:body>\n", "")
    two_close = with_body(GUARD_STUB, OK + "\n# </agent:body>", indent=False).replace(
        "\n# </agent:body>", "\n    # </agent:body>"
    )
    spoof = with_body(GUARD_STUB, "# <agent:body hook=other>\n" + OK)
    reordered = GUARD_STUB.replace("    # <agent:body hook=match_invoice>\n", "").replace(
        "    # </agent:body>", "    # </agent:body>\n    # <agent:body hook=match_invoice>"
    )
    for source in (no_close, two_close, spoof, reordered):
        assert "G0.markers" in rules(source)


def test_the_signature_line_cannot_change() -> None:
    renamed = GUARD_STUB.replace("(data: MatchInput)", "(data: MatchInput, extra: int = 1)")
    other_type = GUARD_STUB.replace("-> MatchResult", "-> dict")
    no_comment = GUARD_STUB.replace("  # platform:signature (fixed)", "")
    for source in (renamed, other_type, no_comment):
        found = rules(source)
        assert "G0.signature" in found
    assert "G5.signature" in rules(renamed)


def test_editing_outside_the_body_is_caught() -> None:
    header_import = GUARD_STUB.replace("\n\n\ndef ", "\nimport math\n\n\ndef ")
    extra_header_comment = GUARD_STUB.replace("# platform:hook", "# changed platform:hook")
    code_after = GUARD_STUB + "\nx = 1\n"
    decorator = GUARD_STUB.replace("def match_invoice", "@staticmethod\ndef match_invoice")
    for source in (header_import, extra_header_comment, code_after, decorator):
        assert "G7.frame_changed" in rules(source), source


def test_code_that_leaves_the_function_is_caught() -> None:
    escaped = with_body(GUARD_STUB, "return MatchResult(allowed=True)\nimport os\nos.system('x')", indent=False)
    escaped = escaped.replace("return MatchResult(allowed=True)", "    return MatchResult(allowed=True)", 1)
    found = rules(escaped)
    assert "G0.structure" in found and "G1.banned_import" in found


def test_a_second_top_level_function_is_caught() -> None:
    body = "    return MatchResult(allowed=True)\ndef other():\n    return 1"
    assert "G0.structure" in rules(with_body(GUARD_STUB, body, indent=False))


def test_syntax_errors_and_bad_text_are_reported_not_raised() -> None:
    assert "G0.syntax" in check("return (")
    assert "G0.syntax" in check("x = = 1")
    assert "G0.syntax" in check("def f(:\n    pass")
    assert "G0.encoding" in rules(b"\xff\xfe" + GUARD_STUB.encode())
    assert "G0.encoding" in rules(b"\xef\xbb\xbf" + GUARD_STUB.encode())
    assert "G0.encoding" in rules(GUARD_STUB.replace("raise NotImplementedError", "x = 1\x00"))
    assert "G0.encoding" in rules(GUARD_STUB.replace("\n    raise", "\r    raise"))
    assert "G0.encoding" in rules(GUARD_STUB.replace("\n    raise", "\n    x = 1\u2028    raise"))
    assert "G0.encoding" in rules("# -*- coding: unicode_escape -*-\n" + GUARD_STUB)
    assert "G0.size" in rules(with_body(GUARD_STUB, "# " + "a" * 70000 + "\n" + OK))
    assert "G0.encoding" in rules("\ud800")


def test_a_parser_bomb_does_not_crash_the_gate() -> None:
    deep = "x = " + "(" * 3000 + "1" + ")" * 3000
    nested = "x = " + "[" * 400 + "]" * 400
    for body in (deep, nested, "x = " + "-" * 5000 + "1"):
        found = rules(with_body(GUARD_STUB, body + "\n" + OK))
        assert found  # reported as something, never raised


def test_very_deep_expressions_are_reported_as_too_nested() -> None:
    body = "x = " + " + ".join(["1"] * 3000) + "\n" + OK
    found = rules(with_body(GUARD_STUB, body))
    assert found & {"G6.nesting", "G0.syntax"}, found


def test_findings_never_echo_literals_or_secrets() -> None:
    secret = "sk_live_" + "Zz9Yy8Xx7Ww6Vv5U"
    odd = "q" * 60
    body = f"key = '{secret}'\npassword = 'correct-horse-battery'\nx = data.{odd}\n__import__('{secret}')\n{OK}"
    for f in gates.check_source(with_body(GUARD_STUB, body), GUARD, GUARD.file):
        assert secret not in f.message and "correct-horse" not in f.message and odd not in f.message
    found = rules(with_body(GUARD_STUB, body))
    assert {"G3.secret_literal", "G2.banned_name"} <= found


def test_a_finding_is_machine_readable() -> None:
    found = gates.check_source(with_body(GUARD_STUB, "import os\n" + OK), GUARD, GUARD.file)
    item = next(f for f in found if f.rule == "G1.banned_import")
    assert item.as_dict() == {
        "rule": "G1.banned_import",
        "gate": "G1",
        "file": "app/custom/hooks/match_invoice.py",
        "line": item.line,
        "message": "import of os",
    }
    assert item.line == 8


# --- the gate never runs what it checks --------------------------------------------------------


def test_checking_a_body_never_executes_it(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    body = f"open({str(marker)!r}, 'w').write('x')\nexec('x = 1')\n__import__('os').system('touch {marker}')\n{OK}"
    assert rules(with_body(GUARD_STUB, body))
    assert not marker.exists()


def test_the_gate_source_has_no_eval_exec_or_dynamic_import() -> None:
    tree = ast.parse(Path(gates.__file__).read_text(encoding="utf-8"))
    names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attrs = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not names & {"eval", "exec", "compile", "__import__"}
    assert not attrs & {"import_module", "run_path", "load_module", "exec_module", "system", "popen"}
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported <= {"argparse", "ast", "hashlib", "json", "os", "re", "sys", "dataclasses", "pathlib", "typing"}


def test_random_mutations_never_crash_the_gate() -> None:
    rng = random.Random(20261101)
    pool = [OK, "import os", "x = (", "return", "for i in range(3):", "lambda: 1", "'''", "\t", "del x", "@a", "x[", "# </agent:body>"]
    for _ in range(300):
        lines = [rng.choice(pool) for _ in range(rng.randint(0, 6))]
        source = with_body(GUARD_STUB, "\n".join(lines) or "pass", indent=rng.random() < 0.7)
        if rng.random() < 0.2:
            raw = bytearray(source.encode())
            raw[rng.randrange(len(raw))] = rng.randrange(256)
            source = bytes(raw).decode("utf-8", "replace")
        assert isinstance(gates.check_source(source, GUARD, GUARD.file), list)


# --- the project level (G7) and the command line -----------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for path, content in FILES.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return tmp_path


def good_project(root: Path) -> None:
    (root / GUARD.file).write_text(with_body(GUARD_STUB, OK), encoding="utf-8")
    body = "from app.platform_sdk import log\nlog.info('x')\nreturn NotifyResult(sent=True)"
    (root / EFFECT.file).write_text(with_body(EFFECT_STUB, body), encoding="utf-8")


def project_rules(root: Path) -> set[str]:
    found, _ = gates.check_project(root)
    return {f.rule for f in found}


def test_a_fresh_project_reports_only_the_unimplemented_stubs(project: Path) -> None:
    assert project_rules(project) == {"G5.not_implemented"}


def test_a_project_with_good_bodies_passes_all_gates(project: Path) -> None:
    good_project(project)
    found, checked = gates.check_project(project)
    assert found == [] and checked == ["match_invoice", "notify_approved"]
    result = gates.report(found, checked)
    assert result["ok"] is True and {g["status"] for g in result["gates"].values()} == {"pass"}


def test_the_hook_zone_rejects_stray_files_and_links(project: Path) -> None:
    good_project(project)
    (project / "app/custom/hooks/helper.py").write_text("x = 1\n", encoding="utf-8")
    (project / "app/custom/hooks/sub").mkdir()
    (project / "app/custom/hooks/sub/deep.py").write_text("x = 1\n", encoding="utf-8")
    os.symlink(project / GUARD.file, project / "app/custom/hooks/link.py")
    found, _ = gates.check_project(project)
    files = {(f.rule, f.file) for f in found}
    assert ("G7.undeclared_file", "app/custom/hooks/helper.py") in files
    assert ("G7.undeclared_file", "app/custom/hooks/sub/deep.py") in files
    assert ("G7.symlink", "app/custom/hooks/link.py") in files


def test_a_stub_that_is_a_symlink_or_missing_is_reported(project: Path) -> None:
    good_project(project)
    target = project / GUARD.file
    real = project / "elsewhere.py"
    real.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.unlink()
    os.symlink(real, target)
    (project / EFFECT.file).unlink()
    found = project_rules(project)
    assert {"G7.symlink", "G0.file_missing"} <= found


def test_generated_files_cannot_be_changed_or_removed(project: Path) -> None:
    good_project(project)
    (project / "app/hooks_gen/registry.py").write_text("HOOKS = {}\n", encoding="utf-8")
    (project / "app/platform_sdk/helpers.py").unlink()
    (project / "app/custom/hooks/__init__.py").write_text("import os\n", encoding="utf-8")
    found, _ = gates.check_project(project)
    files = {(f.rule, f.file) for f in found}
    assert ("G7.generated_modified", "app/hooks_gen/registry.py") in files
    assert ("G7.generated_missing", "app/platform_sdk/helpers.py") in files
    assert ("G7.generated_modified", "app/custom/hooks/__init__.py") in files


def test_files_outside_the_manifest_are_reported_but_custom_zones_are_free(project: Path) -> None:
    good_project(project)
    (project / "app/stray.py").write_text("x = 1\n", encoding="utf-8")
    (project / "tests/test_stray.py").write_text("x = 1\n", encoding="utf-8")
    (project / "app/custom_routers/mine.py").write_text("x = 1\n", encoding="utf-8")
    (project / "tests/custom").mkdir()
    (project / "tests/custom/test_mine.py").write_text("x = 1\n", encoding="utf-8")
    found, _ = gates.check_project(project)
    outside = {f.file for f in found if f.rule == "G7.outside_manifest"}
    assert outside == {"app/stray.py", "tests/test_stray.py"}


def test_a_missing_or_broken_manifest_fails_closed(project: Path) -> None:
    (project / "platform/hooks.json").write_text("{not json", encoding="utf-8")
    assert project_rules(project) == {"G7.manifest"}
    (project / "platform/hooks.json").unlink()
    assert project_rules(project) == {"G7.manifest"}


def test_the_copy_in_a_generated_project_is_byte_identical() -> None:
    assert FILES["app/platform_gate.py"] == Path(gates.__file__).read_text(encoding="utf-8")


def run_cli(root: Path, *args: str) -> tuple[int, dict[str, Any], str]:
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gates.main(["--root", str(root), *args])
    return code, (json.loads(out.getvalue()) if out.getvalue() else {}), err.getvalue()


def test_cli_exit_codes_json_and_summary(project: Path) -> None:
    good_project(project)
    code, report, summary = run_cli(project)
    assert code == 0 and report["ok"] is True and summary.startswith("PASS")
    (project / GUARD.file).write_text(with_body(GUARD_STUB, "import os\n" + OK), encoding="utf-8")
    code, report, summary = run_cli(project)
    assert code == 1 and report["ok"] is False and summary.startswith("FAIL")
    assert report["gates"]["G1"]["status"] == "fail" and report["gates"]["G0"]["status"] == "pass"
    assert report["gate_version"] == 2 and set(report["gates"]) == set(gates.GATES)
    assert all(len(g["means"]) > 20 for g in report["gates"].values())
    first = report["findings"][0]
    assert set(first) == {"rule", "gate", "file", "line", "message"}
    assert "G1.banned_import" in summary


def test_cli_can_check_one_file_or_one_hook(project: Path) -> None:
    good_project(project)
    (project / GUARD.file).write_text(with_body(GUARD_STUB, "import os\n" + OK), encoding="utf-8")
    code, report, _ = run_cli(project, "--hook", "notify_approved")
    assert code == 0 and report["hooks"] == ["notify_approved"]
    code, report, _ = run_cli(project, "--file", str(project / GUARD.file))
    assert code == 1 and report["hooks"] == ["match_invoice"]
    code, report, _ = run_cli(project, "--file", str(project / "app/main.py"))
    assert code == 1 and report["findings"][0]["rule"] == "G0.zone"
    code, report, _ = run_cli(project, "--file", "/etc/passwd")
    assert code == 1 and report["findings"][0]["rule"] == "G0.zone"


def test_cli_exits_two_when_it_cannot_run(project: Path) -> None:
    manifest = json.loads((project / "platform/hooks.json").read_text(encoding="utf-8"))
    del manifest["hooks"][0]["signature"]
    (project / "platform/hooks.json").write_text(json.dumps(manifest), encoding="utf-8")
    code, _, summary = run_cli(project)
    assert code == 2 and "KeyError" in summary


def test_the_module_runs_as_a_script(project: Path) -> None:
    import subprocess
    import sys

    good_project(project)
    result = subprocess.run(
        [sys.executable, "-m", "app.platform_gate", "--root", str(project)],
        cwd=project, capture_output=True, text=True, timeout=60, env={"PATH": os.environ.get("PATH", "")},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True


# --- regenerating on top of an existing project ------------------------------------------------


def test_regenerating_never_overwrites_a_custom_file_that_exists() -> None:
    mine = with_body(GUARD_STUB, OK)
    existing = {GUARD.file: mine, "app/hooks_gen/contracts.py": "old", "README.md": "mine"}
    write, kept = merge_regenerated(existing, FILES)
    assert GUARD.file not in write and GUARD.file in kept
    assert write["app/hooks_gen/contracts.py"] == FILES["app/hooks_gen/contracts.py"]  # generated: replaced
    assert EFFECT.file in write  # a stub that does not exist yet is created
    assert "app/custom/hooks/__init__.py" in write
    assert {p for p in kept} == {GUARD.file}
    again, kept_again = merge_regenerated({**existing, **{k: v for k, v in write.items()}}, FILES)
    assert GUARD.file in kept_again and EFFECT.file in kept_again
    assert GUARD.file not in again and EFFECT.file not in again


# --- gate v2: SENTINEL B1-8 probes (B-1, B-2, M-1) and attacker-style bypass attempts ----------

CANARY = 'out = c.sys.modules["os"].popen("echo RCE_$SENTINEL_CANARY; id -u").read()\n'
# (case id, body, rule ids that must ALL be reported)
BAD_V2: list[tuple[str, str, set[str]]] = [
    # SENTINEL probes, verbatim
    ("sentinel_b1_alias_rce", "import calendar\nc = calendar\n" + CANARY + "return MatchResult(allowed=True, reason=out)", {"G1.module_value"}),
    ("sentinel_b1_getattr_calendar", 'import calendar\ns = getattr(calendar, "sys")\n' + OK, {"G2.banned_name", "G1.module_value"}),
    ("sentinel_b1_getattr_json", 'import json\ngetattr(json, "codecs")\n' + OK, {"G2.banned_name", "G1.module_value"}),
    ("sentinel_b1_textwrap_re", 'import textwrap\nt = textwrap\nt.re.compile("x")\n' + OK, {"G1.module_value"}),
    ("sentinel_b1_typing_list", "import typing\n[typing][0].sys\n" + OK, {"G1.module_value"}),
    ("sentinel_b1_uuid_alias", "import uuid\nu = uuid\nu.os\n" + OK, {"G1.module_value"}),
    (
        "sentinel_b2_format_environ",
        'getattr("{0.__init__.__globals__[sys].modules[os].environ[SENTINEL_CANARY]}", "format")(data)\n' + OK,
        {"G2.banned_name", "G2.format_string"},
    ),
    ("sentinel_m1_redos", 'import re\nre.match(r"(a+)+$", "a" * 32 + "b")\n' + OK, {"G1.banned_import"}),
    ("sentinel_m1_iter_sentinel_loop", "for _ in iter(int, 1):\n    pass\n" + OK, {"G6.unbounded"}),
    ("sentinel_m1_count", "import itertools\nfor n in itertools.count():\n    pass\n" + OK, {"G1.name_not_allowed"}),
    ("sentinel_m1_from_count", "from itertools import count\n" + OK, {"G1.name_not_allowed"}),
    ("sentinel_m1_factorial", "import math\nmath.factorial(10**6)\n" + OK, {"G1.name_not_allowed"}),
    ("sentinel_m1_comb", "from math import comb\n" + OK, {"G1.name_not_allowed"}),
    ("sentinel_m1_perm", "import math\nmath.perm(10**5, 10**4)\n" + OK, {"G1.name_not_allowed"}),
    # 25 new attempts
    ("new01_closure_cell", "def f():\n    return data\nf.__closure__[0].cell_contents\n" + OK, {"G2.dunder", "G2.introspection_attr"}),
    ("new02_cell_contents_public", "def f():\n    return data\nx = f.cell_contents\n" + OK, {"G2.introspection_attr"}),
    ("new03_function_globals", "def f():\n    return 1\nf.__globals__\n" + OK, {"G2.dunder"}),
    ("new04_generator_frame_globals", "g = (i for i in [1])\ng.gi_frame.f_globals\n" + OK, {"G2.introspection_attr"}),
    ("new05_type_mro", "type(data).__mro__\n" + OK, {"G2.banned_name", "G2.dunder"}),
    ("new06_model_fields_on_input", "data.model_fields\n" + OK, {"G2.introspection_attr"}),
    ("new07_model_construct", "data.model_construct()\n" + OK, {"G2.introspection_attr"}),
    ("new08_input_alias_model_validate", "d = data\nd.model_validate({})\n" + OK, {"G2.introspection_attr"}),
    ("new09_input_alias_model_config", "d = data\nd.model_config\n" + OK, {"G2.introspection_attr"}),
    ("new10_input_alias_json_schema", "d = data\nd.model_json_schema()\n" + OK, {"G2.introspection_attr"}),
    ("new11_sdk_facade_as_value", "import app.platform_sdk as sdk\ns = sdk\ns.os\n" + OK, {"G1.module_value"}),
    ("new12_sdk_logger_class", "from app.platform_sdk import log\nlog.bind().__class__\n" + OK, {"G2.dunder"}),
    ("new13_str_format_through_type", "str.format('{0.a}', data)\n" + OK, {"G2.format_call", "G2.format_string"}),
    ("new14_format_field_string", "x = '{0.a}'\nx\n" + OK, {"G2.format_string"}),
    ("new15_escaped_dunder_string", "x = '\\x5f\\x5fclass'\nx\n" + OK, {"G2.format_string"}),
    ("new16_percent_width", "'%999999999d' % 1\n" + OK, {"G2.format_string"}),
    ("new17_fstring_dynamic_width", "f'{1:>{data.amount}}'\n" + OK, {"G6.iteration_bound"}),
    ("new18_string_times_huge", "x = data.invoice_no * 10**9\nx\n" + OK, {"G6.iteration_bound"}),
    ("new19_shift_dynamic", "x = 1 << data.amount\nx\n" + OK, {"G6.iteration_bound"}),
    ("new20_pow_augassign", "x = 7\nx **= data.amount\n" + OK, {"G6.iteration_bound"}),
    ("new21_y_combinator", "def f(g, n):\n    return g(g, n - 1)\nf(f, 3)\n" + OK, {"G6.recursion"}),
    ("new22_alias_recursion", "def f(n):\n    return h(n)\nh = f\nf(1)\n" + OK, {"G6.recursion"}),
    ("new23_repeat_without_count", "from itertools import repeat\nsum(repeat(1))\n" + OK, {"G6.unbounded"}),
    ("new24_ljust_huge", "'x'.ljust(10**10)\n" + OK, {"G6.unbounded"}),
    ("new25_dynamic_range", "for i in range(int(data.amount)):\n    pass\n" + OK, {"G6.unbounded"}),
    # a few more families, kept in the table because they were found while probing
    ("more_walrus_alias", "import calendar\n(c := calendar)\n" + OK, {"G1.module_value"}),
    ("more_dict_alias", "import json\nx = {'m': json}\nx\n" + OK, {"G1.module_value"}),
    ("more_comprehension_alias", "import calendar, json\nx = [m for m in (calendar, json)]\n" + OK, {"G1.module_value"}),
    ("more_function_argument_alias", "import calendar\ndef f(m):\n    return m.sys\nf(calendar)\n" + OK, {"G1.module_value"}),
    ("more_with_alias", "import calendar\nwith calendar as c:\n    pass\n" + OK, {"G1.module_value"}),
    ("more_fullwidth_alias", "import calendar\nc = \uff43alendar\nc\n" + OK, {"G1.module_value"}),
    ("more_lambda_returns_alias", "import calendar\nf = lambda: calendar\nf().sys\n" + OK, {"G1.module_value"}),
    ("more_typing_attr", "import typing\ntyping.sys\n" + OK, {"G1.name_not_allowed"}),
    ("more_lambda_self_call", "f = lambda n: f(n - 1)\nf(3)\n" + OK, {"G6.recursion"}),
    ("more_container_recursion", "fs = []\ndef f():\n    return fs[0]()\nfs.append(f)\nf()\n" + OK, {"G6.recursion"}),
    ("more_repeat_huge_count", "from itertools import repeat\nlist(repeat(1, 10**9))\n" + OK, {"G6.unbounded"}),
    ("more_bytes_alloc", "bytes(10**10)\n" + OK, {"G2.banned_name"}),
    ("more_to_bytes_huge", "(1).to_bytes(10**10, 'big')\n" + OK, {"G6.unbounded"}),
    ("more_sum_iter_sentinel", "sum(iter(int, 1))\n" + OK, {"G6.unbounded"}),
    ("more_pow_three_args", "pow(3, 5, 7)\n" + OK, {"G6.iteration_bound"}),
    ("more_pow_big_exponent", "pow(3, 1000)\n" + OK, {"G6.iteration_bound"}),
    ("more_decimal_power", "from decimal import Decimal\nx = Decimal(2) ** Decimal(10**9)\n" + OK, {"G6.iteration_bound"}),
    ("more_double_in_loop", "x = [1]\nfor i in range(40):\n    x = x + x\n" + OK, {"G6.iteration_bound"}),
    ("more_repeat_in_loop", "x = [1]\nfor i in range(40):\n    x = x * 1000\n" + OK, {"G6.iteration_bound"}),
    ("more_repeat_twice", "x = [0] * 90000\ny = x * 90000\n" + OK, {"G6.iteration_bound"}),
    ("more_hasattr", "hasattr(data, 'amount')\n" + OK, {"G2.banned_name"}),
    ("more_format_builtin", "format(data.amount, '>10')\n" + OK, {"G2.banned_name"}),
    ("more_format_map_attr", "d = {'a': 1}\n'x'.format_map(d)\n" + OK, {"G2.format_call"}),
    ("more_re_via_from", "from re import compile\n" + OK, {"G1.banned_import"}),
    ("more_regex_module", "import regex\n" + OK, {"G1.banned_import"}),
    ("more_fractions_removed", "from fractions import Fraction\n" + OK, {"G1.not_allowed_import"}),
    ("more_difflib_removed", "import difflib\n" + OK, {"G1.not_allowed_import"}),
]
V2_NEW = [c for c in BAD_V2 if c[0].startswith("new")]


@pytest.mark.parametrize(("case", "body", "expected"), BAD_V2, ids=[c[0] for c in BAD_V2])
def test_a_v2_bad_body_is_rejected_with_its_rule_ids(case: str, body: str, expected: set[str]) -> None:
    found = check(body)
    assert expected <= found, f"{case}: expected {sorted(expected)}, got {sorted(found)}"


def test_there_are_25_new_bypass_attempts_and_the_sentinel_probes() -> None:
    assert len(V2_NEW) == 25
    assert len([c for c in BAD_V2 if c[0].startswith("sentinel")]) == 14


GOOD_V2: list[tuple[str, str]] = [
    ("module_attribute_call", "import calendar\nreturn MatchResult(allowed=calendar.isleap(2024))"),
    ("module_alias_function", "import math as m\nreturn MatchResult(allowed=m.floor(2.5) == 2)"),
    ("from_import_function", "from calendar import monthrange\nreturn MatchResult(allowed=monthrange(2024, 2)[1] == 29)"),
    ("datetime_class_chain", "import datetime\nreturn MatchResult(allowed=datetime.date(2024, 1, 1).year == 2024)"),
    ("range_len_and_literals", "n = 0\nfor i in range(len(data.invoice_no)):\n    n += i\nfor j in range(0, 100, 5):\n    n += j\nreturn MatchResult(allowed=n > 0)"),
    ("small_power_and_shift", "x = data.amount ** 2 + 2 ** 10 + (1 << 8)\nreturn MatchResult(allowed=x > 0)"),
    ("small_repeat", "line = '-' * 20 + [0, 1] * 3 == [] and 'x' or ''\nreturn MatchResult(allowed=bool(line))"),
    ("repeat_with_count", "from itertools import repeat\nreturn MatchResult(allowed=sum(repeat(1, 5)) == 5)"),
    ("fstring_with_literal_width", "return MatchResult(allowed=True, reason=f'{data.invoice_no:>10}')"),
    ("join_strip_and_split", "return MatchResult(allowed=True, reason=' '.join(data.invoice_no.strip().split('-')))"),
    ("one_argument_iter", "it = iter([1, 2])\nreturn MatchResult(allowed=next(it) == 1)"),
    ("decimal_arithmetic", "from decimal import Decimal\nreturn MatchResult(allowed=Decimal('1.10') * 3 > data.amount)"),
    ("sorted_with_key_lambda", "rows = sorted(['b', 'a'], key=lambda s: s)\nreturn MatchResult(allowed=rows[0] == 'a')"),
    ("percent_format_small", "return MatchResult(allowed=True, reason='%s-%d' % (data.invoice_no, 3))"),
    ("nested_helper_no_recursion", "def a(n):\n    return n + 1\ndef b(n):\n    return a(n) + 1\nreturn MatchResult(allowed=b(1) == 3)"),
]


@pytest.mark.parametrize(("case", "body"), GOOD_V2, ids=[c[0] for c in GOOD_V2])
def test_a_v2_good_body_still_passes(case: str, body: str) -> None:
    found = gates.check_source(with_body(GUARD_STUB, body), GUARD, GUARD.file)
    assert found == [], f"{case}: {[f.as_dict() for f in found]}"


def test_no_allowed_name_is_a_module_and_none_reaches_one_through_public_attributes() -> None:
    """The allow-lists hold functions, classes and constants only. This is the check that made calendar,
    uuid, textwrap, typing, statistics, functools and json safe to keep behind `module.name`."""
    import importlib
    import types

    def modules_below(obj: object, path: str, seen: set[int], depth: int, out: list[str]) -> None:
        if depth > 4 or id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, types.ModuleType):
            out.append(path)
            return
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                value = getattr(obj, name)
            except Exception:
                continue
            modules_below(value, f"{path}.{name}", seen, depth + 1, out)

    leaks: list[str] = []
    for module, names in gates.ALLOWED_MODULES.items():
        mod = importlib.import_module(module)
        for name in sorted(names):
            assert hasattr(mod, name), f"{module}.{name} does not exist"
            modules_below(getattr(mod, name), f"{module}.{name}", set(), 0, leaks)
    assert leaks == []
    for banned in ("re", "regex", "fractions", "difflib"):
        assert banned not in gates.ALLOWED_MODULES


def test_modules_that_expose_other_modules_are_only_usable_as_module_dot_name() -> None:
    import importlib
    import types

    exposing = [
        m for m in gates.ALLOWED_MODULES
        if any(isinstance(getattr(importlib.import_module(m), n), types.ModuleType) for n in dir(importlib.import_module(m)))
    ]
    assert {"calendar", "uuid", "textwrap", "typing", "statistics", "json", "functools"} & set(exposing) >= {
        "calendar", "uuid", "textwrap", "typing", "statistics", "json"
    }
    for module in exposing:
        short = module.split(".")[-1]
        body = f"import {module} as m\nx = m\n" + OK
        assert "G1.module_value" in check(body), module
        leaked = [n for n in dir(importlib.import_module(module)) if isinstance(getattr(importlib.import_module(module), n), types.ModuleType) and not n.startswith("_")]
        for name in leaked:
            assert "G1.name_not_allowed" in check(f"import {module} as m\nm.{name}\n" + OK), f"{short}.{name}"


def test_the_runtime_executor_is_bounded_and_not_the_default_one() -> None:
    text = (Path(gates.__file__).parent / "generator/features/hooks/templates/app/hooks_gen/runtime.py.tpl").read_text("utf-8")
    assert "run_in_executor(_EXECUTOR" in text and "run_in_executor(None" not in text
    assert "MAX_HOOK_THREADS = 4" in text and "NOT stopped" in text


# --- G7 widening: alembic, dependencies, images, compose, conftest/site hooks, .pth ------------


def test_guarded_paths() -> None:
    yes = ["alembic/env.py", "alembic/versions/0001.py", "requirements.txt", "requirements-dev.txt", "Dockerfile",
           "Dockerfile.prod", "docker-compose.yml", "docker-compose.prod.yml", "conftest.py", "tests/conftest.py",
           "app/sub/conftest.py", "sitecustomize.py", "x/usercustomize.py", "evil.pth", "a/b/evil.pth"]
    no = ["app/main.py", "README.md", "tests/test_x.py", "app/custom/hooks/h.py", "docs/requirements_notes.md"]
    assert all(gates.is_guarded_path(p) for p in yes)
    assert not any(gates.is_guarded_path(p) for p in no)


def test_a_fresh_project_hashes_its_guarded_files() -> None:
    guarded = set(MANIFEST["guarded_sha256"])
    assert any(p.startswith("alembic/") for p in guarded)
    assert "Dockerfile" in guarded and any(p.startswith("requirements") for p in guarded)
    assert "tests/conftest.py" in guarded or "conftest.py" in guarded
    assert all(gates.is_guarded_path(p) for p in guarded)


def test_editing_a_guarded_file_fails_g7(project: Path) -> None:
    good_project(project)
    for rel in sorted(MANIFEST["guarded_sha256"]):
        path = project / rel
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "\n# tampered\n", encoding="utf-8")
        found, _ = gates.check_project(project)
        assert ("G7.generated_modified", rel) in {(f.rule, f.file) for f in found}, rel
        path.write_text(original, encoding="utf-8")
    assert project_rules(project) == set()


def test_a_removed_guarded_file_fails_g7(project: Path) -> None:
    good_project(project)
    (project / "Dockerfile").unlink()
    found, _ = gates.check_project(project)
    assert ("G7.generated_missing", "Dockerfile") in {(f.rule, f.file) for f in found}


@pytest.mark.parametrize(
    "rel",
    ["alembic/versions/9999_evil.py", "alembic/evil.sql", "requirements-evil.txt", "Dockerfile.evil",
     "docker-compose.evil.yml", "conftest.py", "app/conftest.py", "tests/unit/conftest.py", "sitecustomize.py",
     "app/custom/usercustomize.py", "evil.pth", "deep/er/evil.pth"],
)
def test_a_new_guarded_file_fails_g7(project: Path, rel: str) -> None:
    good_project(project)
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("import os\n", encoding="utf-8")
    found, _ = gates.check_project(project)
    assert ("G7.guarded_new_file", rel) in {(f.rule, f.file) for f in found}


def test_a_virtualenv_inside_the_project_is_not_scanned(project: Path) -> None:
    good_project(project)
    (project / ".venv/lib").mkdir(parents=True)
    (project / ".venv/lib/site.pth").write_text("x\n", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules/conftest.py").write_text("x\n", encoding="utf-8")
    assert project_rules(project) == set()
