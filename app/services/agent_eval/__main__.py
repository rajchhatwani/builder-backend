"""CLI: `python -m app.services.agent_eval <command>`.

  run              deterministic run of every fixed task (needs Docker; shells out to the api test)
  compare REPORT   compare a report json with tests/agent_eval/baseline.json
  live             real-provider run (refused unless a BYO key is configured; not wired yet)
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from app.services.agent_eval import report as rep
from app.services.agent_eval.runner import BASELINE, EvalError, run_live


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", default="agent_eval_report.json")
    c = sub.add_parser("compare")
    c.add_argument("report")
    c.add_argument("--baseline", default=str(BASELINE))
    lv = sub.add_parser("live")
    lv.add_argument("--api-key-env", default="AGENT_EVAL_BYO_KEY")
    a = p.parse_args(argv)
    if a.cmd == "run":
        env = {**os.environ, "AGENT_EVAL_REPORT": str(Path(a.out).resolve())}
        code = subprocess.call([sys.executable, "-m", "pytest", "tests/api/test_agent_eval.py", "-q"], env=env)
        if code == 0 or Path(a.out).exists():
            return _compare(a.out, str(BASELINE))
        return code
    if a.cmd == "compare":
        return _compare(a.report, a.baseline)
    try:
        asyncio.run(run_live(os.environ.get(a.api_key_env)))
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _compare(report_path: str, baseline_path: str) -> int:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    regressions = rep.compare(report, baseline)
    print(rep.markdown(report, regressions))
    return 1 if regressions or report["summary"]["passed"] != report["summary"]["tasks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
