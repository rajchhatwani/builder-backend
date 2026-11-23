"""The keyring of regulated mode (generated). The keys are customer-managed: they come from a file or a command,
never from the spec, the database or the generated files. No cloud SDK; a KMS is reached through a command.

  REGULATED_KEY_PROVIDER  file | command | env (default: what the spec chose)
  REGULATED_KEY_FILE      path of the key file (file provider). Must be mode 0600, else it is refused.
  REGULATED_KEY_COMMAND   command (no shell, 10 s timeout) that prints the key lines (command provider)
  SECRET_KEY              the `env` provider derives a key from it (development only: refused in production)

Key lines, one per line ('#' comments allowed):  <keyid> <urlsafe-base64 of 32 random bytes>
The FIRST line is the active key (encrypts); the others only decrypt, until `python -m app.regulated.reencrypt`
has moved every row. Messages never contain key material. The ring is loaded on first use and cached; `reset()`
drops the cache (rotation, tests).

`derive(label)` gives a purpose-bound 32-byte subkey (HKDF-SHA256 over a ring key): the blind index, the token
HMAC and the provider vault master each get their own, so no key is ever used for two purposes."""

import base64
import binascii
import os
import re
import shlex
import stat
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.regulated import settings
from app.regulated.errors import RegulatedError

KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
COMMAND_TIMEOUT_SECONDS = 10.0
DEVELOPMENT_ENVS = frozenset({"local", "dev", "development", "test", "testing", "demo", "preview"})
_TEST_SECRET = "regulated-mode-test-secret-not-for-production"


@dataclass(frozen=True)
class KeyRing:
    active_id: str
    keys: dict[str, bytes]  # key id -> 32 bytes; the first inserted is the active key

    def __post_init__(self) -> None:
        if self.active_id not in self.keys:
            raise RegulatedError("the active key id is not in the keyring")
        for kid, raw in self.keys.items():
            if not KEY_ID.fullmatch(kid):
                raise RegulatedError("key ids must match [A-Za-z0-9_-]{1,32}")
            if len(raw) != 32:
                raise RegulatedError("every key must be 32 bytes")

    def __repr__(self) -> str:  # never print key material
        return f"KeyRing(active={self.active_id!r}, ids={sorted(self.keys)!r})"


def parse_key_lines(text: str) -> KeyRing:
    keys: dict[str, bytes] = {}
    active: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2 or not KEY_ID.fullmatch(parts[0]):
            raise RegulatedError("malformed key line (expected '<keyid> <base64 key>')")
        kid, b64 = parts
        try:
            key = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        except (binascii.Error, ValueError):
            raise RegulatedError(f"key {kid!r} is not valid base64") from None
        if len(key) != 32:
            raise RegulatedError(f"key {kid!r} must be 32 bytes")
        if kid in keys:
            raise RegulatedError(f"duplicate key id {kid!r}")
        keys[kid] = key
        active = active or kid
    if active is None:
        raise RegulatedError("no keys found")
    return KeyRing(active, keys)


def new_key_b64() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _app_env() -> str:
    return os.environ.get("APP_ENV", "").strip().lower()


def _env_ring() -> KeyRing:
    """Development only: a key derived from SECRET_KEY (key id `env0`). Never a customer-managed key."""
    env = _app_env()
    if env not in DEVELOPMENT_ENVS:
        raise RegulatedError("the env key provider is for development only: use REGULATED_KEY_PROVIDER=file or command")
    secret = os.environ.get("SECRET_KEY", "").strip() or (_TEST_SECRET if env == "test" else "")
    if not secret:
        raise RegulatedError("SECRET_KEY is not set (the env key provider needs it)")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"regulated-env-key-v1").derive(secret.encode())
    return KeyRing("env0", {"env0": key})


def _file_ring(path: str) -> KeyRing:
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        raise RegulatedError("key file is not readable") from None
    if not stat.S_ISREG(st.st_mode):
        raise RegulatedError("key file is not a regular file")
    if st.st_mode & 0o077:
        raise RegulatedError("key file must not be accessible by group or others (chmod 600)")
    try:
        return parse_key_lines(p.read_text())
    except (OSError, ValueError):  # unreadable, or not text (UnicodeDecodeError); RegulatedError is raised by the parser itself
        raise RegulatedError("key file is not readable") from None


def _command_ring(command: str) -> KeyRing:
    argv = shlex.split(command)
    if not argv:
        raise RegulatedError("REGULATED_KEY_COMMAND is empty")
    env = {n: os.environ[n] for n in ("PATH", "HOME") if n in os.environ}  # never the API's secrets
    try:
        done = subprocess.run(  # noqa: S603 - argv list, shell=False, operator-configured
            argv, capture_output=True, timeout=COMMAND_TIMEOUT_SECONDS, check=False, text=True, env=env
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RegulatedError("the key command could not be run") from None
    if done.returncode != 0:
        raise RegulatedError("the key command failed")
    return parse_key_lines(done.stdout)


def load_ring() -> KeyRing:
    provider = os.environ.get("REGULATED_KEY_PROVIDER", "").strip().lower() or settings.KEY_PROVIDER
    if provider == "env":
        return _env_ring()
    if provider == "file":
        path = os.environ.get("REGULATED_KEY_FILE", "").strip()
        if not path:
            if _app_env() == "test":
                return _env_ring()  # the generated tests only; any other environment must name a key file
            raise RegulatedError("REGULATED_KEY_FILE is not set")
        return _file_ring(path)
    if provider == "command":
        command = os.environ.get("REGULATED_KEY_COMMAND", "").strip()
        if not command:
            if _app_env() == "test":
                return _env_ring()
            raise RegulatedError("REGULATED_KEY_COMMAND is not set")
        return _command_ring(command)
    raise RegulatedError("REGULATED_KEY_PROVIDER must be file, command or env")


_lock = threading.Lock()
_ring: KeyRing | None = None


def get_ring() -> KeyRing:
    global _ring
    ring = _ring
    if ring is None:
        with _lock:
            if _ring is None:
                _ring = load_ring()
            ring = _ring
    return ring


def reset() -> None:
    """Forget the loaded ring: the next use reads the provider again (after a rotation)."""
    global _ring
    with _lock:
        _ring = None


def check_boot() -> None:
    """Start-up check: the keyring must load (a missing or unsafe key file stops the process)."""
    get_ring()


def derive(label: str, key_id: str | None = None) -> bytes:
    """A purpose-bound 32-byte subkey of ring key `key_id` (default: the active key)."""
    ring = get_ring()
    kid = key_id or ring.active_id
    key = ring.keys.get(kid)
    if key is None:
        raise RegulatedError("unknown key id")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"regulated:" + label.encode()).derive(key)


def vault_version(key_id: str) -> int:
    """A stable version number (1..999999) for a ring key, used by the provider credential vault."""
    import zlib

    return zlib.crc32(key_id.encode()) % 999_999 + 1


def vault_masters() -> tuple[int, dict[int, str]]:
    """The provider vault's master keys, one per ring key (version, urlsafe text), derived from the keyring.
    The vault master is NOT stored anywhere: rotating the ring keeps every credential readable."""
    ring = get_ring()
    out: dict[int, str] = {}
    for kid in ring.keys:
        version = vault_version(kid)
        if version in out:
            raise RegulatedError("two key ids collide in the provider vault version space: rename one")
        out[version] = base64.urlsafe_b64encode(derive("provider-vault", kid)).decode()
    return vault_version(ring.active_id), out
