"""Key providers for data-at-rest encryption (P6). No cloud SDK: a KMS is reached through a file
or a command (e.g. a KMS CLI wrapper) that hands back data keys.

A keyring has several keys for DEcrypt and exactly one active key for ENcrypt. Every new
ciphertext carries the key id (`v2:<keyid>:<fernet token>`), so a key can be rotated without
guessing which one a row used.

Key material format for the file and command providers (one key per line, '#' comments allowed):

    <keyid> <urlsafe-base64 of 32 random bytes>

The FIRST line is the active key; the others stay available for decrypt until `reencrypt_all`
has moved every row. The env provider derives key id `env0` from SECRET_KEY exactly as before.
"""

import base64
import binascii
import os
import re
import shlex
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
COMMAND_TIMEOUT_SECONDS = 10.0


class KeyProviderError(RuntimeError):
    """Configuration or key-material problem. Messages never carry key material."""


@dataclass(frozen=True)
class KeyRing:
    active_id: str
    keys: dict[str, Fernet]

    def __post_init__(self) -> None:
        if self.active_id not in self.keys:
            raise KeyProviderError("the active key id is not in the keyring")
        for kid in self.keys:
            if not KEY_ID.fullmatch(kid):
                raise KeyProviderError("key ids must match [A-Za-z0-9_-]{1,32}")


def parse_key_lines(text: str) -> KeyRing:
    keys: dict[str, Fernet] = {}
    active: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2 or not KEY_ID.fullmatch(parts[0]):
            raise KeyProviderError("malformed key line (expected '<keyid> <base64 key>')")
        kid, b64 = parts
        try:
            raw_key = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        except (binascii.Error, ValueError):
            raise KeyProviderError(f"key {kid!r} is not valid base64") from None
        if len(raw_key) != 32:
            raise KeyProviderError(f"key {kid!r} must be 32 bytes")
        if kid in keys:
            raise KeyProviderError(f"duplicate key id {kid!r}")
        keys[kid] = Fernet(base64.urlsafe_b64encode(raw_key))
        active = active or kid
    if active is None:
        raise KeyProviderError("no keys found")
    return KeyRing(active, keys)


def new_key_b64() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


class KeyProvider:
    name = "base"

    def load(self) -> KeyRing:  # pragma: no cover - interface
        raise NotImplementedError


class EnvKeyProvider(KeyProvider):
    """SECRET_KEY -> HKDF-SHA256 (no salt, label builder-auth-secrets-v1), key id `env0`.
    Byte-identical to the pre-v2 derivation so existing tokens keep decrypting."""

    name = "env"

    def __init__(self, fernet_factory: Callable[[], Fernet]) -> None:
        self._factory = fernet_factory

    def load(self) -> KeyRing:
        return KeyRing("env0", {"env0": self._factory()})


class FileKeyProvider(KeyProvider):
    name = "file"

    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> KeyRing:
        p = Path(self.path)
        try:
            st = p.stat()
        except OSError:
            raise KeyProviderError("key file is not readable") from None
        if not stat.S_ISREG(st.st_mode):
            raise KeyProviderError("key file is not a regular file")
        if st.st_mode & 0o077:
            raise KeyProviderError("key file must not be accessible by group or others (chmod 600)")
        return parse_key_lines(p.read_text())


class CommandKeyProvider(KeyProvider):
    """Runs a configured command (no shell) whose stdout is the key lines, e.g. a wrapper that
    calls a KMS CLI to decrypt a wrapped data key. The output is never logged."""

    name = "command"

    def __init__(
        self, command: str, timeout: float = COMMAND_TIMEOUT_SECONDS, extra_env: tuple[str, ...] = ()
    ) -> None:
        self.argv = shlex.split(command)
        self.timeout = timeout
        self.extra_env = tuple(n for n in extra_env if n)

    def _env(self) -> dict[str, str]:
        """S-3: PATH and HOME only, plus operator-named extras; never the API's secrets."""
        names = ("PATH", "HOME", *self.extra_env)
        return {n: os.environ[n] for n in names if n in os.environ}

    def load(self) -> KeyRing:
        if not self.argv:
            raise KeyProviderError("key_provider_command is empty")
        try:
            done = subprocess.run(  # noqa: S603 - argv list, shell=False, operator-configured
                self.argv, capture_output=True, timeout=self.timeout, check=False, text=True,
                env=self._env(),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise KeyProviderError("the key command could not be run") from None
        if done.returncode != 0:
            raise KeyProviderError("the key command failed")
        return parse_key_lines(done.stdout)


class FakeKms(KeyProvider):
    """In-memory KMS for tests: `rotate()` makes a new active key and keeps the old ones."""

    name = "fake"

    def __init__(self, *key_ids: str) -> None:
        self._ids: list[str] = []
        self._material: dict[str, str] = {}
        for kid in key_ids or ("k1",):
            self.add(kid)

    def add(self, key_id: str) -> None:
        self._material[key_id] = new_key_b64()
        self._ids.insert(0, key_id)

    rotate = add

    def drop(self, key_id: str) -> None:
        self._ids.remove(key_id)
        del self._material[key_id]

    def load(self) -> KeyRing:
        return parse_key_lines("\n".join(f"{k} {self._material[k]}" for k in self._ids))


def build_provider(
    kind: str,
    *,
    path: str | None,
    command: str | None,
    env_fernet: Callable[[], Fernet],
    command_env: str = "",
) -> KeyProvider:
    if kind == "env":
        return EnvKeyProvider(env_fernet)
    if kind == "file":
        if not path:
            raise KeyProviderError("key_provider=file needs key_provider_file")
        return FileKeyProvider(path)
    if kind == "command":
        if not command:
            raise KeyProviderError("key_provider=command needs key_provider_command")
        return CommandKeyProvider(command, extra_env=tuple(command_env.replace(",", " ").split()))
    raise KeyProviderError(f"unknown key provider {kind!r}")
