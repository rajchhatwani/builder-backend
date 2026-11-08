"""A-008 (B2-6): a generated zip never contains a credential. Every fixture spec is generated and zipped the way
the download does, and every file is scanned for credential shapes. Fake secrets are written split so no real
-looking secret sits in this repository. A planted secret proves the scan can fail."""

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.generator.archive import build_zip
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
SPECS = sorted(p.stem for p in FIXTURES.glob("*.json"))

PATTERNS = {
    "stripe_live_key": re.compile(r"\b[sr]k_live_[A-Za-z0-9]{10,}"),
    "stripe_test_secret": re.compile(r"\bsk_test_[A-Za-z0-9]{16,}"),
    "stripe_webhook_secret": re.compile(r"\bwhsec_[A-Za-z0-9]{16,}"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"),
    "bearer_literal": re.compile(r"Bearer\s+[A-Za-z0-9._-]{30,}"),
    "jwt_literal": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}
# Split so this file itself holds none of them.
FAKES = {
    "stripe_live_key": "sk_" "live_" "4eC39HqLyjWDarjtT1zdp7dc",
    "aws_access_key": "AKIA" "IOSFODNN7EXAMPLE",
    "private_key_block": "-----BEGIN " "RSA PRIVATE KEY-----",
    "github_token": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "anthropic_key": "sk-" "ant-api03-" "abcdefghijklmnop1234",
}


def _findings(archive: bytes) -> list[tuple[str, str]]:
    """Credential-shaped strings in the shipped files. The generated `tests/` folder is skipped on purpose:
    its redaction tests plant canary credentials to prove they never reach a log or a response."""
    hits = []
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for info in z.infolist():
            if info.filename.split("/")[1:2] == ["tests"]:
                continue
            text = z.read(info).decode("utf-8", errors="replace")
            hits += [(info.filename, name) for name, rx in PATTERNS.items() if rx.search(text)]
    return hits


def test_the_scan_catches_every_planted_secret_shape() -> None:
    for name, fake in FAKES.items():
        zipped = build_zip("proj", {"app/config.py": f'KEY = "{fake}"\n'})
        assert _findings(zipped) == [("proj/app/config.py", name)], name


@pytest.mark.parametrize("name", SPECS)
def test_a_generated_zip_holds_no_credential(name: str) -> None:
    spec = Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if validate(spec):
        pytest.skip(f"{name} is not a valid spec (intentionally invalid fixture)")
    zipped = build_zip(spec.project.slug, generate(spec))
    assert _findings(zipped) == []


def _with_secret(name: str, where: str, fake: str) -> Spec:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    if where == "notification_body":
        data["notifications"]["types"][0]["templates"][0]["body"] = f"token {fake}"
    elif where == "provider_field":
        data["providers"]["providers"][0]["api_key"] = fake
    return Spec.model_validate(data)


@pytest.mark.parametrize("fake", [FAKES["stripe_live_key"], FAKES["aws_access_key"], FAKES["github_token"]])
def test_a_credential_in_the_spec_is_refused_so_it_cannot_reach_the_zip(fake: str) -> None:
    spec = _with_secret("notifications_orders", "notification_body", fake)
    codes = {i.code for i in validate(spec)}
    assert codes & {"secret_in_spec", "secret_value", "secret_like"}, codes
