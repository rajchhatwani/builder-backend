"""Audit B1-039: closed-run results frozen, auto_match reports truncation, matcher off the loop, dispatcher config validated."""

import sys
import time
import types
from datetime import date

from app.core.generator import generate
from tests.unit.test_money_reconciliation import _spec as _recon_spec

R = "app/money/reconciliation/"


def _recon() -> dict[str, str]:
    return generate(_recon_spec())


def _auto(svc: str) -> str:
    return svc.split("async def auto_match(")[1].split("async def manual_match(")[0]


def test_closed_run_results_use_the_frozen_summary() -> None:
    svc = _recon()[R + "service.py"]
    body = svc.split("async def _results(")[1].split("async def results(")[0]
    assert 'run.status == "closed"' in body and "run.summary" in body


def test_auto_match_reports_entries_truncated() -> None:
    files = _recon()
    assert "entries_truncated" in files[R + "schemas.py"].split("class AutoMatchOut")[1]
    auto = _auto(files[R + "service.py"])
    assert "_truncated =" not in auto and "entries_truncated=" in auto


def test_matcher_runs_off_the_event_loop() -> None:
    assert "to_thread" in _auto(_recon()[R + "service.py"])


def test_matcher_exact_pass_does_not_rescan_used_entries() -> None:
    mod = types.ModuleType("matcher_b1039")
    sys.modules["matcher_b1039"] = mod
    exec(compile(_recon()[R + "matcher.py"], "matcher.py", "exec"), mod.__dict__)  # noqa: S102
    lines = [mod.Item(f"l{i}", date(2026, 1, 1), 100, None, i) for i in range(4000)]
    entries = [mod.Item(f"e{i}", date(2026, 1, 1), 100, None, i) for i in range(4000)]
    t = time.perf_counter()
    assert len(mod.match(lines, entries, 0)) == 4000
    assert time.perf_counter() - t < 1.0


def test_dispatcher_validates_config_up_front() -> None:
    from tests.unit.test_notifications_feature import spec_with

    src = generate(spec_with())["app/notifications/dispatcher.py"]
    start = src.split("def start_dispatcher(")[1].split("async def stop_dispatcher")[0]
    assert "poll_seconds()" in start and "lease_seconds()" in start
    run = src.split("async def run_forever(")[1].split("def start_dispatcher")[0]
    assert run.index("poll_seconds()") < run.index("while not stop.is_set()")
    assert "lease_seconds()" in src.split("async def _main(")[1]
