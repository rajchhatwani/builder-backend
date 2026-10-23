"""File storage end to end: generate a storage project, `docker compose up` the real stack (API,
PostgreSQL, a real ClamAV daemon and a real S3-compatible server) and drive it over HTTP the way a
client would.

Proves what the in-process tests (stand-in scanner, in-memory bucket) cannot: that the generated
S3 adapter really talks to an S3 server (multipart upload, streaming download, presigned links,
deletion), that the scanner client really speaks to clamd (the EICAR test file is caught, nothing
reaches the bucket, an outage refuses uploads), that the compose file wires it all up, and that the
maintenance command works. The S3 server is SeaweedFS (MinIO's community edition no longer publishes
images); AWS S3 itself is not exercised here. Skipped when `docker compose` is unavailable.
"""

import hashlib
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import httpx
import pytest
from botocore.config import Config

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
PASSWORD = "Correct-horse-battery-1"
ACCESS_KEY = "e2eaccess" + secrets.token_hex(4)
SECRET_KEY = secrets.token_hex(20)
BUCKET = "e2e-uploads"
# The standard antivirus test string, assembled from pieces so this file is not itself flagged.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    not docker_compose_available(), reason="docker compose is not available"
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Stack:
    root: Path
    project: str
    api: str
    store_port: int

    def compose(self, *args: str, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", "-p", self.project, *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    def sql(self, statement: str) -> str:
        result = self.compose(
            "exec", "-T", "db", "psql", "-U", "app", "-d", "app", "-At", "-c", statement
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def s3(self) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=f"http://127.0.0.1:{self.store_port}",
            region_name="us-east-1",
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def objects(self) -> list[str]:
        listing = self.s3().list_objects_v2(Bucket=BUCKET)
        return sorted(item["Key"] for item in listing.get("Contents", []))


def stack_spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "storage_s3.json").read_text(encoding="utf-8"))
    spec["storage"].update(
        {
            "backend": "minio",
            "region": None,
            "bucket": BUCKET,
            "max_file_mb": 10,
            "user_quota_mb": None,
        }
    )
    # No mail server in this stack: sign-up needs no email confirmation.
    spec["auth"]["registration"] = {"email_verification_required": False}
    spec["auth"]["password_reset"] = {"email_magic_link": False}
    spec["auth"]["smtp"] = None
    spec["auth"]["app_url"] = None
    return spec


PROBE = '''\
"""Runs inside the API container: the generated S3 adapter against the real store."""
import asyncio
import hashlib
import io
import json
import sys

from app.storage import config
from app.storage.backend import ObjectMissing, S3Backend


async def main(phase: str) -> None:
    settings = config.get_storage_settings()
    settings.check()
    backend = S3Backend(settings)
    data = b"probe-data-" * 200_000  # 2.2 MB: more than one chunk, less than a multipart part
    key = f"{config.KEY_PREFIX}/_/probe/object"
    if phase == "put":
        await backend.check()
        await backend.put(key, io.BytesIO(data), sha256=hashlib.sha256(data).hexdigest())
        assert await backend.exists(key)
        got = b"".join([chunk async for chunk in backend.stream(key)])
        assert got == data, "streamed bytes differ"
        url = backend.presign(key, filename_header='attachment; filename="probe.bin"', ttl=60)
        print(json.dumps({"url": url, "sha256": hashlib.sha256(data).hexdigest()}))
    else:
        await backend.delete(key)
        assert not await backend.exists(key)
        try:
            async for _ in backend.stream(key):
                raise AssertionError("a deleted object streamed")
        except ObjectMissing:
            pass
        print(json.dumps({"deleted": True}))


asyncio.run(main(sys.argv[1]))
'''

OVERRIDE = """\
services:
  objectstore:
    ports:
      - "127.0.0.1:${STORE_PORT}:8333"
"""


def wait_for(check: Callable[[], bool], seconds: float, what: str = "condition") -> None:
    deadline = time.time() + seconds
    last: Exception | None = None
    while time.time() < deadline:
        try:
            if check():
                return
        except (httpx.HTTPError, AssertionError, KeyError) as exc:
            last = exc
        time.sleep(1)
    raise AssertionError(f"timed out waiting for {what}: {last}")


def build_stack(tmp_path_factory: pytest.TempPathFactory) -> Stack:
    root = tmp_path_factory.mktemp("storagestack")
    for path, content in generate(Spec.model_validate(stack_spec())).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    (root / "tests" / "e2e_probe.py").write_text(PROBE, encoding="utf-8", newline="\n")
    api_port, store_port = free_port(), free_port()
    (root / "docker-compose.override.yml").write_text(OVERRIDE, encoding="utf-8")
    (root / ".env").write_text(
        "\n".join(
            [
                f"API_PORT={api_port}",
                f"STORE_PORT={store_port}",
                "AUTH_JWT_SECRET=" + secrets.token_hex(32),
                f"STORAGE_ACCESS_KEY_ID={ACCESS_KEY}",
                f"STORAGE_SECRET_ACCESS_KEY={SECRET_KEY}",
                # Presigned links are fetched from this machine: they must name the published port.
                f"STORAGE_PUBLIC_ENDPOINT_URL=http://127.0.0.1:{store_port}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    running = Stack(
        root=root,
        project=f"storagestack{secrets.token_hex(3)}",
        api=f"http://127.0.0.1:{api_port}",
        store_port=store_port,
    )
    up = running.compose("up", "-d", "--build", "--wait", "--wait-timeout", "900")
    if up.returncode != 0:
        logs = running.compose("logs", "--tail", "60").stdout
        running.compose("down", "-v", "--remove-orphans")
        raise AssertionError(f"compose up failed:\n{up.stdout}\n{up.stderr}\n{logs}")
    return running


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """The stack is built for this module and removed afterwards. For quick iteration set
    STORAGE_STACK_STATE to a file name: the first run builds the stack and leaves it running,
    later runs reuse it (remove it with `docker compose -p <project> down -v`)."""
    global ACCESS_KEY, SECRET_KEY
    state = os.environ.get("STORAGE_STACK_STATE")
    if state and Path(state).exists():
        saved = json.loads(Path(state).read_text(encoding="utf-8"))
        ACCESS_KEY, SECRET_KEY = (
            saved["access_key"],
            saved["secret_key"],
        )  # those the stack runs with
        yield Stack(Path(saved["root"]), saved["project"], saved["api"], saved["store_port"])
        return
    running = build_stack(tmp_path_factory)
    if state:
        Path(state).write_text(
            json.dumps(
                {
                    "root": str(running.root),
                    "project": running.project,
                    "api": running.api,
                    "store_port": running.store_port,
                    "access_key": ACCESS_KEY,
                    "secret_key": SECRET_KEY,
                }
            ),
            encoding="utf-8",
        )
        yield running
        return
    try:
        yield running
    finally:
        running.compose("down", "-v", "--remove-orphans")


@dataclass
class Person:
    stack: Stack
    headers: dict[str, str]
    email: str

    def http(self) -> httpx.Client:
        return httpx.Client(base_url=self.stack.api, headers=self.headers, timeout=120)


def register(stack: Stack, email: str, roles: list[str]) -> Person:
    with httpx.Client(base_url=stack.api, timeout=30) as http:
        created = http.post("/auth/register", json={"email": email, "password": PASSWORD})
        assert created.status_code in (201, 409), created.text  # 409: a kept stack is reused
        stack.sql(
            f"UPDATE auth_users SET roles = '{json.dumps(roles)}'::jsonb WHERE email = '{email}'"
        )
        login = http.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200, login.text
        return Person(stack, {"Authorization": f"Bearer {login.json()['access_token']}"}, email)


@pytest.fixture(scope="module")
def admin(stack: Stack) -> Person:
    return register(stack, "admin@example.com", ["admin"])


@pytest.fixture(scope="module")
def member(stack: Stack) -> Person:
    return register(stack, "member@example.com", ["member"])


def upload(
    person: Person, data: bytes, name: str = "note.txt", ctype: str = "text/plain"
) -> httpx.Response:
    with person.http() as http:
        return http.post("/files", files={"file": (name, data, ctype)})


def row(stack: Stack, file_id: str, column: str) -> str:
    return stack.sql(f"SELECT {column} FROM stor_files WHERE id = '{file_id}'")


# --- tests ----------------------------------------------------------------------------------------


def test_scanner_and_bucket_are_healthy(stack: Stack, admin: Person) -> None:
    with admin.http() as http:
        status = http.get("/files/status").json()
    assert status["scanner"]["ok"] is True
    assert status["scanner"]["engine"].startswith("ClamAV")
    assert status["bucket"]["ok"] is True
    assert status["max_file_bytes"] == 10 * 1024 * 1024


def test_a_clean_file_is_scanned_stored_and_comes_back_intact(stack: Stack, member: Person) -> None:
    data = b"Quarterly numbers: 1, 2, 3\n" * 100
    created = upload(member, data)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "clean" and body["sha256"] == hashlib.sha256(data).hexdigest()
    key = row(stack, body["id"], "storage_key")
    assert key in stack.objects()
    stored = stack.s3().head_object(Bucket=BUCKET, Key=key)
    assert stored["ContentType"] == "application/octet-stream"  # the bucket never decides the type
    assert row(stack, body["id"], "scan_engine").startswith("ClamAV")

    with member.http() as http:
        download = http.get(f"/files/{body['id']}/download")
    assert download.status_code == 200 and download.content == data
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["content-disposition"].startswith("attachment;")


def test_the_eicar_test_file_is_caught_and_never_reaches_the_bucket(
    stack: Stack, member: Person
) -> None:
    before = stack.objects()
    response = upload(member, EICAR, name="harmless.txt")
    assert response.status_code == 422
    assert response.json()["code"] == "malware_detected"
    assert "Eicar" not in response.text  # the detection name stays in the audit trail
    assert stack.objects() == before
    detections = stack.sql(
        "SELECT data->>'detection' FROM stor_audit_log WHERE event = 'upload.rejected' "
        "AND data->>'reason' = 'malware_detected' ORDER BY at DESC LIMIT 1"
    )
    assert "eicar" in detections.lower(), detections
    # ClamAV looks inside archives: the same test file in a zip is caught too.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("readme.txt", "nothing to see here")
        archive.writestr("docs/eicar.com", EICAR)
    zipped = upload(member, buffer.getvalue(), name="holiday.zip", ctype="application/zip")
    assert zipped.status_code == 422 and zipped.json()["code"] == "malware_detected"
    assert stack.objects() == before


def test_a_large_file_goes_through_multipart_upload_and_round_trips(
    stack: Stack, member: Person
) -> None:
    data = secrets.token_bytes(9 * 1024 * 1024)  # above boto3's 8 MB multipart threshold
    created = upload(member, data, name="big.bin", ctype="application/octet-stream")
    assert created.status_code == 201, created.text
    file_id = created.json()["id"]
    with member.http() as http:
        download = http.get(f"/files/{file_id}/download")
    assert hashlib.sha256(download.content).hexdigest() == hashlib.sha256(data).hexdigest()
    # Over the limit: refused while the body is still arriving. The server may hang up before the
    # client has finished sending, so a cut connection counts as the same refusal.
    try:
        refused = upload(member, secrets.token_bytes(10 * 1024 * 1024 + 300_000), name="huge.bin")
    except httpx.TransportError:
        pass
    else:
        assert refused.status_code == 413 and refused.json()["code"] == "file_too_large"


def test_the_generated_adapter_works_against_the_real_store(stack: Stack) -> None:
    put = stack.compose("exec", "-T", "api", "python", "-m", "tests.e2e_probe", "put")
    assert put.returncode == 0, put.stdout + put.stderr
    info = json.loads(put.stdout.strip().splitlines()[-1])
    # A browser follows this link: no credentials, only the signature in the URL.
    fetched = httpx.get(info["url"], timeout=30)
    assert fetched.status_code == 200
    assert hashlib.sha256(fetched.content).hexdigest() == info["sha256"]
    assert fetched.headers["content-disposition"] == 'attachment; filename="probe.bin"'
    assert fetched.headers["content-type"] == "application/octet-stream"
    tampered_url = info["url"].replace("X-Amz-Signature=", "X-Amz-Signature=0")
    assert httpx.get(tampered_url, timeout=30).status_code in (400, 403)
    gone = stack.compose("exec", "-T", "api", "python", "-m", "tests.e2e_probe", "delete")
    assert gone.returncode == 0, gone.stdout + gone.stderr
    assert httpx.get(info["url"], timeout=30).status_code in (403, 404)


def test_the_bucket_refuses_anonymous_access(stack: Stack) -> None:
    anonymous = httpx.get(f"http://127.0.0.1:{stack.store_port}/{BUCKET}/anything", timeout=10)
    assert anonymous.status_code in (401, 403, 404) and anonymous.status_code != 200
    listing = httpx.get(f"http://127.0.0.1:{stack.store_port}/{BUCKET}", timeout=10)
    assert listing.status_code in (401, 403) or "<Contents>" not in listing.text


def test_an_object_changed_in_the_bucket_is_detected(
    stack: Stack, member: Person, admin: Person
) -> None:
    created = upload(member, b"original content " * 64).json()
    key = row(stack, created["id"], "storage_key")
    original = stack.s3().get_object(Bucket=BUCKET, Key=key)["Body"].read()
    stack.s3().put_object(Bucket=BUCKET, Key=key, Body=bytes(b ^ 1 for b in original))
    with member.http() as http:
        http.get(f"/files/{created['id']}/download")
    wait_for(
        lambda: (
            stack.sql(
                f"SELECT count(*) FROM stor_audit_log WHERE file_id = '{created['id']}' "
                "AND event = 'download.integrity_mismatch'"
            )
            == "1"
        ),
        15,
        "the integrity mismatch to be audited",
    )
    with admin.http() as http:
        trail = http.get(f"/files/{created['id']}/audit").json()
    assert trail["chain_ok"] is True


def test_the_rescan_command_quarantines_a_file_that_is_now_flagged(
    stack: Stack, member: Person
) -> None:
    created = upload(member, b"fine when uploaded " * 64).json()
    file_id = created["id"]
    key = row(stack, file_id, "storage_key")
    # Signatures learn about the file later: the stored bytes now match a detection.
    flagged = EICAR  # the whole file is the test string, which is what the signature matches
    stack.s3().put_object(Bucket=BUCKET, Key=key, Body=flagged)
    stack.sql(
        f"UPDATE stor_files SET sha256 = '{hashlib.sha256(flagged).hexdigest()}', "
        f"size_bytes = {len(flagged)}, scanned_at = now() - interval '60 days' "
        f"WHERE id = '{file_id}'"
    )
    result = stack.compose(
        "run", "--rm", "--no-deps", "api", "python", "-m", "app.storage.maintenance", "--rescan"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert row(stack, file_id, "status") == "quarantined"
    assert row(stack, file_id, "quarantine_reason") == "infected"
    with member.http() as http:
        assert http.get(f"/files/{file_id}/download").status_code == 409
    assert "storage_audit_digest" in result.stdout + result.stderr


def test_without_the_scanner_uploads_are_refused_and_they_recover(
    stack: Stack, member: Person
) -> None:
    before = stack.objects()
    assert stack.compose("stop", "clamav").returncode == 0
    try:
        refused = upload(member, b"cannot be scanned now " * 10)
        assert refused.status_code == 503 and refused.json()["code"] == "scanner_unavailable"
        assert stack.objects() == before  # nothing slipped through unscanned
    finally:
        assert stack.compose("start", "clamav").returncode == 0
    wait_for(
        lambda: upload(member, b"back again " * 10).status_code == 201, 240, "the scanner to return"
    )


def test_delete_removes_the_object_for_good(stack: Stack, member: Person, admin: Person) -> None:
    created = upload(member, b"to be erased " * 64).json()
    key = row(stack, created["id"], "storage_key")
    assert key in stack.objects()
    with member.http() as http:
        assert http.delete(f"/files/{created['id']}").status_code == 204
    assert key not in stack.objects()
    assert row(stack, created["id"], "status") == "deleted"
    assert row(stack, created["id"], "original_name") == ""
    with admin.http() as http:
        trail = http.get(f"/files/{created['id']}/audit").json()
    assert [e["event"] for e in trail["entries"]] == ["upload.accepted", "file.deleted"]
    assert trail["chain_ok"] is True


def test_production_mode_refuses_a_plain_http_endpoint(stack: Stack) -> None:
    result = stack.compose(
        "run", "--rm", "--no-deps", "-e", "APP_ENV=production", "api", "python", "-c",
        "from app.storage import config; config.get_storage_settings().check()",
    )  # fmt: skip
    assert result.returncode != 0
    assert "https" in result.stderr


def test_the_containers_run_without_root_and_the_scanner_has_no_published_port(
    stack: Stack,
) -> None:
    whoami = stack.compose("exec", "-T", "api", "id", "-u")
    assert whoami.stdout.strip() == "10001"
    listing = stack.compose("ps", "--format", "json", "clamav").stdout
    for line in listing.splitlines():
        if line.strip():
            published = json.loads(line).get("Publishers") or []
            assert all(not p.get("PublishedPort") for p in published), published
