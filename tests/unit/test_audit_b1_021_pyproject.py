"""pyproject must agree with what gate/pre-commit enforce and with the code's imports."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_ruff_config_matches_gate_rules():
    lint = PROJECT["tool"]["ruff"]["lint"]
    assert set(lint["select"]) == {"E", "W", "F"}
    assert "E501" in lint.get("ignore", [])


def test_mcp_lower_bound_ships_mcpserver():
    dep = next(d for d in PROJECT["project"]["dependencies"] if d.startswith("mcp"))
    m = re.match(r"mcp>=(\d+)\.", dep)
    assert m and int(m.group(1)) >= 2
