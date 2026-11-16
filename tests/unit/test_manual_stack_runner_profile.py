"""F-0409: manual_stack.sh must wire the optional runner profile so down/reset also stop it."""
import re
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2] / "scripts" / "manual_stack.sh").read_text()


def test_down_and_reset_include_runner_profile():
    for pat in (r"dc_all down --remove-orphans", r"dc_all down -v --remove-orphans"):
        assert re.search(pat, SCRIPT), pat
    assert re.search(r"dc_all\(\).*--profile runner", SCRIPT)


def test_up_honours_runner_token_and_port_checked():
    assert "BB_RUNNER_TOKEN" in SCRIPT
    assert re.search(r'PORTS="[^"]*\b8790\b', SCRIPT)
