"""Effectful hooks (B2-10, H2/H3, CO-3): off by default, trusted authors only, budgets, gates."""

import copy
import json
import sys
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest

from app.core import hook_gates as gates
from app.core.generator import InvalidSpecError, generate
from app.core.spec_models import Spec
from app.core.validation import validate

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures" / "specs"
BUDGET_SRC = (
    ROOT.parent / "app/core/generator/features/hooks/templates/app/platform_sdk/budget.py.tpl"
)


def data() -> dict[str, Any]:
    return copy.deepcopy(json.loads((FIXTURES / "hooks_effects.json").read_text(encoding="utf-8")))


def spec_with(change: Any = None) -> Spec:
    d = data()
    if change is not None:
        change(d)
    return Spec.model_validate(d)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


# --- off by default / opt-in (fail closed) -----------------------------------------------------


def test_the_example_is_valid_and_generates_the_effect_files() -> None:
    assert validate(spec_with()) == []
    files = generate(spec_with())
    assert {"app/platform_sdk/effects.py", "app/platform_sdk/budget.py"} <= set(files)
    manifest = json.loads(files["platform/hooks.json"])
    assert manifest["effects"]["trusted_authors_only"] is True
    assert manifest["hooks"][0]["effects"] == ["email", "notification"]
    assert {"send_email", "notify"} <= set(manifest["sdk_io"])  # I/O: refused in pure hooks


@pytest.mark.parametrize("how", ["absent", "disabled"])
def test_effects_without_the_opt_in_are_refused(how: str) -> None:
    def change(d: dict[str, Any]) -> None:
        if how == "absent":
            del d["hook_effects"]
        else:
            d["hook_effects"]["enabled"] = False

    spec = spec_with(change)
    assert ("hooks[0].effects", "effects_not_enabled") in codes(spec)
    with pytest.raises(InvalidSpecError):
        generate(spec)


def test_without_hook_effects_nothing_effectful_is_generated() -> None:
    def change(d: dict[str, Any]) -> None:
        d["hook_effects"] = None
        d["hooks"][0]["effects"] = []
        d["hooks"][0]["effect_budget"] = None

    files = generate(spec_with(change))
    assert "app/platform_sdk/effects.py" not in files
    assert "effects" not in json.loads(files["platform/hooks.json"])
    assert "Effectful hooks are ON" not in files["README.md"]


def test_the_owner_must_confirm_trusted_authors() -> None:
    def change(d: dict[str, Any]) -> None:
        d["hook_effects"]["trusted_authors_only"] = False

    assert ("hook_effects.trusted_authors_only", "required") in codes(spec_with(change))


@pytest.mark.parametrize("author", ["ai", "external"])
def test_ai_or_outside_authored_hooks_are_refused_when_effects_are_on(author: str) -> None:
    def change(d: dict[str, Any]) -> None:
        d["hooks"][0]["author"] = author

    assert ("hooks[0].author", "untrusted_author") in codes(spec_with(change))

    def other_hook(d: dict[str, Any]) -> None:  # even a pure hook, once the project has effects on
        d["hook_effects"]["enabled"] = True
        d["hooks"][0]["effects"] = []
        d["hooks"][0]["effect_budget"] = None
        d["hooks"][0]["author"] = author

    assert ("hooks[0].author", "untrusted_author") in codes(spec_with(other_hook))


def test_readme_states_the_trusted_authors_rule() -> None:
    readme = generate(spec_with())["README.md"]
    assert "Effectful hooks are ON in this project (trusted authors only)" in readme
    assert "refused until the Cycle 3 sandbox exists" in readme


def test_effect_types_providers_and_ranges() -> None:
    def bad_type(d: dict[str, Any]) -> None:
        d["hooks"][0]["effects"] = ["email", "shell"]

    assert ("hooks[0].effects[1]", "invalid_value") in codes(spec_with(bad_type))

    def no_providers(d: dict[str, Any]) -> None:
        d["providers"]["enabled"] = False

    assert ("hooks[0].effects[0]", "needs_providers") in codes(spec_with(no_providers))

    def webhook(d: dict[str, Any]) -> None:
        d["hooks"][0]["effects"] = ["webhook"]

    found = codes(spec_with(webhook))
    assert ("hooks[0].effects[0]", "needs_webhooks") in found
    assert ("hook_effects.webhook_hosts", "required") in found

    def hosts(d: dict[str, Any]) -> None:
        d["hook_effects"]["webhook_hosts"] = ["10.0.0.1", "https://x.test"]

    assert {p for p, _ in codes(spec_with(hosts))} >= {
        "hook_effects.webhook_hosts[0]",
        "hook_effects.webhook_hosts[1]",
    }

    def ranges(d: dict[str, Any]) -> None:
        d["hooks"][0]["effect_budget"] = {"calls_per_effect": 0, "payload_bytes": 10**9, "outbound_per_minute": 0}

    found = {c for p, c in codes(spec_with(ranges))}
    assert "over_ceiling" in found

    def only_effect_kind(d: dict[str, Any]) -> None:
        d["hooks"][0]["kind"] = "pure"

    assert ("hooks[0].effects", "invalid_value") in codes(spec_with(only_effect_kind))


def test_after_commit_effects_cannot_fail_the_write() -> None:
    def change(d: dict[str, Any]) -> None:
        d["hooks"][0]["failure_policy"] = "fail_closed"
        d["hooks"][0]["fallback"] = None

    assert ("hooks[0].failure_policy", "invalid_value") in codes(spec_with(change))


# --- gates -------------------------------------------------------------------------------------

FILES = generate(spec_with())
MANIFEST: dict[str, Any] = json.loads(FILES["platform/hooks.json"])
EFFECT = gates.hook_from_manifest(MANIFEST, MANIFEST["hooks"][0])
STUB = FILES["app/custom/hooks/announce_order.py"]


def with_body(body: str) -> str:
    lines = STUB.split("\n")
    start = next(i for i, line in enumerate(lines) if "<agent:body" in line)
    end = next(i for i, line in enumerate(lines) if "</agent:body>" in line)
    new = ["    " + line for line in textwrap.dedent(body).strip("\n").split("\n")]
    return "\n".join([*lines[: start + 1], *new, *lines[end:]])


def rules(body: str, hook: gates.HookInfo = EFFECT) -> set[str]:
    return {f.rule for f in gates.check_source(with_body(body), hook, hook.file)}


def test_an_effect_hook_may_use_the_sdk_effect_functions() -> None:
    body = """
    from app.platform_sdk import send_email, notify

    ok = send_email("a@example.com", "hi", "body")
    notify("welcome", data.reference, {"name": "x"})
    return AnnounceResult(sent=ok)
    """
    assert rules(body) == set()


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ("import socket", "G1.banned_import"),
        ("import subprocess", "G1.banned_import"),
        ("import httpx", "G1.network_import"),
        ("import urllib.request", "G1.network_import"),
        ("import smtplib", "G1.network_import"),
        ("import requests", "G1.network_import"),
        ("from app.providers import client", "G1.layer_import"),
        ("from app.webhooks import egress", "G1.layer_import"),
    ],
)
def test_effect_hooks_cannot_reach_the_network_directly(line: str, rule: str) -> None:
    assert rule in rules(f"{line}\nreturn AnnounceResult(sent=True)")


def test_a_pure_hook_cannot_use_effect_functions() -> None:
    pure = gates.hook_from_manifest(MANIFEST, {**MANIFEST["hooks"][0], "kind": "pure"})
    body = "from app.platform_sdk import send_email\nsend_email('a@b.c', 's', 'b')\nreturn AnnounceResult(sent=True)"
    assert "G4.sdk_io" in rules(body, pure)


def test_effect_function_names_do_not_leak_a_secret_shape() -> None:
    body = 'from app.platform_sdk import send_email\nsend_email("a@b.c", "s", "api_key=sk_' 'live_abcdefghijklmnop")\nreturn AnnounceResult(sent=True)'
    assert rules(body)  # the secret-in-string gate still applies to effectful hooks


# --- the budget ledger -------------------------------------------------------------------------


def load_budget() -> Any:
    module = types.ModuleType("hook_budget_under_test")
    sys.modules[module.__name__] = module  # dataclasses look the module up
    exec(compile(BUDGET_SRC.read_text(encoding="utf-8"), str(BUDGET_SRC), "exec"), module.__dict__)  # pure: no imports of the platform
    return module


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def ledger() -> tuple[Any, Any, Clock]:
    mod = load_budget()
    clock = Clock()
    return mod, mod.Ledger(clock), clock


def limits(mod: Any, **kw: Any) -> Any:
    base = {"effects": frozenset({"email", "sms"}), "wall_seconds": 1.1, "calls_per_effect": 2,
            "payload_bytes": 100, "outbound_per_minute": 3}
    return mod.EffectLimits(**{**base, **kw})


def code_of(mod: Any, fn: Any) -> str:
    with pytest.raises(mod.OverBudget) as info:
        fn()
    return str(info.value.code)


def test_calls_per_effect_type_per_invocation(ledger: Any) -> None:
    mod, led, clock = ledger
    lim, calls = limits(mod, outbound_per_minute=50), {}
    led.charge("h", lim, calls, "email", 10, clock.now)
    led.charge("h", lim, calls, "email", 10, clock.now)
    assert code_of(mod, lambda: led.charge("h", lim, calls, "email", 10, clock.now)) == "calls"
    led.charge("h", lim, calls, "sms", 10, clock.now)  # another effect type has its own count
    led.charge("h", lim, {}, "email", 10, clock.now)  # a new invocation starts again


def test_payload_wall_clock_and_undeclared_effects(ledger: Any) -> None:
    mod, led, clock = ledger
    lim = limits(mod)
    assert code_of(mod, lambda: led.charge("h", lim, {}, "email", 101, clock.now)) == "payload"
    assert code_of(mod, lambda: led.charge("h", lim, {}, "webhook", 1, clock.now)) == "not_declared"
    assert code_of(mod, lambda: led.charge("h", None, {}, "email", 1, clock.now)) == "not_declared"
    started = clock.now
    clock.now += 2.0
    assert code_of(mod, lambda: led.charge("h", lim, {}, "email", 1, started)) == "wall_clock"


def test_outbound_per_minute_window_slides(ledger: Any) -> None:
    mod, led, clock = ledger
    lim = limits(mod, calls_per_effect=10)
    for _ in range(3):
        led.charge("h", lim, {}, "email", 1, clock.now)
    assert code_of(mod, lambda: led.charge("h", lim, {}, "email", 1, clock.now)) == "rate"
    led.charge("other", lim, {}, "email", 1, clock.now)  # per hook
    clock.now += 61
    led.charge("h", lim, {}, "email", 1, clock.now)


def test_a_refused_call_is_not_counted(ledger: Any) -> None:
    mod, led, clock = ledger
    lim, calls = limits(mod, calls_per_effect=10), {}
    for _ in range(5):
        with pytest.raises(mod.OverBudget):
            led.charge("h", lim, calls, "email", 500, clock.now)
    assert calls == {}
    for _ in range(3):
        led.charge("h", lim, calls, "email", 1, clock.now)
