from pathlib import Path

import yaml

CFG = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"


def _hooks():
    data = yaml.safe_load(CFG.read_text())
    return {h["id"]: h for r in data["repos"] for h in r["hooks"]}


def test_ruff_hook_matches_gate_rules():
    hooks = _hooks()
    args = " ".join(hooks["ruff"].get("args", []))
    assert "--select=E,W,F" in args
    assert "--ignore=E501" in args
    assert hooks["ruff"].get("files") == "^app/"


def test_no_repo_wide_ruff_format_hook():
    assert "ruff-format" not in _hooks()
