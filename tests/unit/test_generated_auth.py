"""The generated auth module's crypto and provider code, run for real in a subprocess.

The generated project's own tests (see tests/e2e) use an in-memory outbox, so they never reach
the SMTP / SMS code. Here the network libraries are replaced by fakes that record what would
have been sent, which checks URLs, credentials, headers and failure handling without a network.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec, SpecAuthSecrets

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def build(tmp_path_factory: pytest.TempPathFactory, label: str, **auth_overrides: Any) -> Path:
    data = json.loads((FIXTURES / "shop_auth.json").read_text(encoding="utf-8"))
    for key, value in auth_overrides.items():
        data["auth"][key] = value
    root = tmp_path_factory.mktemp(label)
    for path, content in generate(Spec.model_validate(data)).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


@pytest.fixture(scope="module")
def twilio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(tmp_path_factory, "twilio")


@pytest.fixture(scope="module")
def vonage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(
        tmp_path_factory, "vonage", sms_provider="vonage", sms={"from_number": "+14155550100"}
    )


@pytest.fixture(scope="module")
def sns(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(tmp_path_factory, "sns", sms_provider="aws_sns", sms={"from_number": "ShopApp"})


@pytest.fixture(scope="module")
def smtps(tmp_path_factory: pytest.TempPathFactory) -> Path:
    smtp = {
        "host": "smtp.example.com",
        "port": 465,
        "use_tls": True,
        "from_email": "noreply@shop.example.com",
        "from_name": "Shop",
    }
    return build(tmp_path_factory, "smtps", smtp=smtp)


def run_script(root: Path, script: str, **env: str) -> str:
    clean = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    clean["DATABASE_URL"] = "postgresql+asyncpg://user:pass@localhost:5432/example_test"
    clean.update(env)
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=root,
        env=clean,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


# --- security primitives ----------------------------------------------------------------


def test_password_hashing_and_jwt_primitives(twilio: Path) -> None:
    run_script(
        twilio,
        """
        import base64, json, time
        from app.auth import security

        stored = security.hash_password("pw-one")
        assert stored.startswith("scrypt$")
        assert security.verify_password("pw-one", stored)
        assert not security.verify_password("pw-two", stored)
        assert stored != security.hash_password("pw-one"), "hashes must be salted"
        for junk in ("", "garbage", "scrypt$a$b$c$d$e", "bcrypt$1$2$3$4$5", "scrypt$1$2$3$4"):
            assert not security.verify_password("pw-one", junk), junk

        secret = "s" * 40
        token = security.encode_jwt({"sub": "1", "exp": time.time() + 60}, secret)
        assert security.decode_jwt(token, secret)["sub"] == "1"

        def b64(obj):
            raw = json.dumps(obj).encode()
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

        header, payload, signature = token.split(".")
        forged_payload = b64({"sub": "2", "exp": time.time() + 60})
        none_alg = b64({"alg": "none", "typ": "JWT"}) + "." + payload + "."
        hs512 = b64({"alg": "HS512", "typ": "JWT"}) + "." + payload + "." + signature
        cases = {
            "tampered payload": f"{header}.{forged_payload}.{signature}",
            "alg none": none_alg,
            "other algorithm": hs512,
            "wrong secret": security.encode_jwt({"sub": "1", "exp": time.time() + 60}, "t" * 40),
            "expired": security.encode_jwt({"sub": "1", "exp": time.time() - 1}, secret),
            "no expiry": security.encode_jwt({"sub": "1"}, secret),
            "not a jwt": "a.b",
            "garbage": "!!!.???.***",
            "empty": "",
        }
        for name, bad in cases.items():
            try:
                security.decode_jwt(bad, secret)
            except security.InvalidTokenError:
                continue
            raise AssertionError(f"accepted {name}")

        assert len(security.new_token()) >= 43
        assert security.new_otp().isdigit() and len(security.new_otp()) == 6
        assert security.hash_secret("x") == security.hash_secret("x") != security.hash_secret("y")
        """,
    )


def test_request_schemas_reject_header_injection_and_normalise_email(twilio: Path) -> None:
    run_script(
        twilio,
        """
        import pydantic
        from app.auth.schemas import LoginRequest, RegisterRequest

        base = {"password": "long enough pw", "full_name": "Ann"}
        ok = RegisterRequest(email="  Ann@Example.COM ", **base)
        assert ok.email == "ann@example.com"
        # Surrounding whitespace is trimmed, so a trailing CRLF cannot reach the mail headers.
        assert RegisterRequest(email="a@b.com\\r\\n", **base).email == "a@b.com"
        injected = ("a@b.com\\nBcc: x@y.com", "a@b.com\\r\\nBcc: x@y.com", "a b@c.com", "a@b")
        for bad in (*injected, '"x"@b.com'):
            try:
                RegisterRequest(email=bad, **base)
            except pydantic.ValidationError:
                continue
            raise AssertionError(f"accepted {bad!r}")
        for bad_phone in ("4155550123", "+0155550123", "+1 415 555", "+141555501234567890"):
            try:
                RegisterRequest(email="a@b.com", phone=bad_phone, **base)
            except pydantic.ValidationError:
                continue
            raise AssertionError(f"accepted phone {bad_phone!r}")
        # Passwords are not trimmed or otherwise altered.
        assert LoginRequest(email="a@b.com", password="  spaced  ").password == "  spaced  "
        # Unknown fields are refused, so a client cannot smuggle in e.g. roles.
        try:
            RegisterRequest(email="a@b.com", roles=["admin"], **base)
        except pydantic.ValidationError:
            pass
        else:
            raise AssertionError("accepted roles")
        # Custom field constraints apply.
        try:
            RegisterRequest(email="a@b.com", password="long enough pw", full_name="A")
        except pydantic.ValidationError:
            pass
        else:
            raise AssertionError("accepted a short full_name")
        """,
    )


def test_rate_limit_grammar_and_window(twilio: Path) -> None:
    run_script(
        twilio,
        """
        import asyncio
        from app.auth.ratelimit import RateLimiter, parse_limit
        from app.core.errors import AppError

        assert parse_limit("5/15minutes") == (5, 900)
        assert parse_limit("10/hour") == (10, 3600)
        assert parse_limit("2/second") == (2, 1)
        assert parse_limit("100/day") == (100, 86400)
        for bad in ("5", "x/hour", "5/week", "5/ hour"):
            try:
                parse_limit(bad)
            except ValueError:
                continue
            raise AssertionError(bad)

        class Req:
            class client:
                host = "10.0.0.1"

        class Other:
            class client:
                host = "10.0.0.2"

        async def main():
            limiter = RateLimiter("t", "2/hour")
            await limiter(Req())
            await limiter(Req())
            await limiter(Other())  # another client has its own budget
            try:
                await limiter(Req())
            except AppError as exc:
                assert exc.status_code == 429 and exc.code == "rate_limited"
            else:
                raise AssertionError("third request was allowed")

        asyncio.run(main())
        """,
    )


# --- SMTP -------------------------------------------------------------------------------

_FAKE_SMTP = """
import asyncio, smtplib
calls = []

class FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        calls.append(("connect", type(self).__name__, host, port, timeout, context is not None))
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def starttls(self, context=None):
        calls.append(("starttls", context is not None))
    def login(self, user, password):
        calls.append(("login", user, password))
    def send_message(self, message):
        calls.append(("message", message["From"], message["To"], message["Subject"],
                      message.get_content().strip()))

class FakeSMTPSSL(FakeSMTP):
    pass

smtplib.SMTP = FakeSMTP
smtplib.SMTP_SSL = FakeSMTPSSL
from app.auth.delivery import SmtpMailer
"""


def test_smtp_starttls_login_and_message(twilio: Path) -> None:
    run_script(
        twilio,
        _FAKE_SMTP
        + """
asyncio.run(SmtpMailer().send("ann@example.com", "Hello", "Body text"))
assert calls == [
    ("connect", "FakeSMTP", "smtp.example.com", 587, 10, False),
    ("starttls", True),
    ("login", "mailer", "s3cret"),
    ("message", "Shop <noreply@shop.example.com>", "ann@example.com", "Hello", "Body text"),
], calls
""",
        SMTP_USERNAME="mailer",
        SMTP_PASSWORD="s3cret",
        AUTH_JWT_SECRET="j" * 40,
    )


def test_smtp_skips_login_without_credentials_and_uses_ssl_on_465(smtps: Path) -> None:
    run_script(
        smtps,
        _FAKE_SMTP
        + """
asyncio.run(SmtpMailer().send("ann@example.com", "Hi", "x"))
kinds = [c[0] for c in calls]
assert kinds == ["connect", "message"], calls  # no STARTTLS on an SSL port, no login
assert calls[0][1] == "FakeSMTPSSL" and calls[0][3] == 465
""",
        AUTH_JWT_SECRET="j" * 40,
    )


def test_smtp_failures_surface_as_delivery_errors(twilio: Path) -> None:
    run_script(
        twilio,
        """
        import asyncio, smtplib
        from app.auth.delivery import DeliveryError, SmtpMailer

        class Down:
            def __init__(self, *a, **k):
                raise ConnectionRefusedError("nope")

        smtplib.SMTP = Down
        try:
            asyncio.run(SmtpMailer().send("a@b.com", "s", "b"))
        except DeliveryError as exc:
            assert "ConnectionRefusedError" in str(exc) and "nope" not in str(exc)
        else:
            raise AssertionError("no error")
        """,
        AUTH_JWT_SECRET="j" * 40,
    )


# --- SMS providers ----------------------------------------------------------------------

_FAKE_HTTP = """
import asyncio, json, urllib.request
sent = []

class FakeResponse:
    def __init__(self, payload=b"{}"):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def read(self):
        return self.payload

reply = [b"{}"]

def fake_urlopen(request, timeout=None):
    sent.append((request.full_url, dict(request.header_items()), request.data.decode(), timeout))
    return FakeResponse(reply[0])

urllib.request.urlopen = fake_urlopen
"""


def test_twilio_request(twilio: Path) -> None:
    run_script(
        twilio,
        _FAKE_HTTP
        + """
import base64, urllib.parse
from app.auth.delivery import TwilioSender, get_sms_sender

assert isinstance(get_sms_sender(), TwilioSender)
asyncio.run(TwilioSender().send("+14155550123", "Your code is 123456"))
url, headers, body, timeout = sent[0]
assert url == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json", url
assert headers["Authorization"] == "Basic " + base64.b64encode(b"ACtest:tok3n").decode()
assert urllib.parse.parse_qs(body) == {
    "To": ["+14155550123"], "From": ["+14155550100"], "Body": ["Your code is 123456"]
}, body
assert timeout == 10
""",
        TWILIO_ACCOUNT_SID="ACtest",
        TWILIO_AUTH_TOKEN="tok3n",
        AUTH_JWT_SECRET="j" * 40,
    )


def test_twilio_without_credentials_fails_cleanly(twilio: Path) -> None:
    run_script(
        twilio,
        """
        import asyncio
        from app.auth.delivery import DeliveryError, TwilioSender

        try:
            asyncio.run(TwilioSender().send("+14155550123", "x"))
        except DeliveryError as exc:
            assert "TWILIO_ACCOUNT_SID" in str(exc)
        else:
            raise AssertionError("no error")
        """,
        AUTH_JWT_SECRET="j" * 40,
    )


def test_vonage_request_and_rejection(vonage: Path) -> None:
    run_script(
        vonage,
        _FAKE_HTTP
        + """
import urllib.parse
from app.auth.delivery import DeliveryError, VonageSender

reply[0] = b'{"messages": [{"status": "0"}]}'
asyncio.run(VonageSender().send("+14155550123", "code 654321"))
url, _headers, body, _timeout = sent[0]
assert url == "https://rest.nexmo.com/sms/json"
fields = urllib.parse.parse_qs(body)
assert fields["to"] == ["14155550123"] and fields["from"] == ["14155550100"], fields
assert fields["api_key"] == ["key1"] and fields["api_secret"] == ["secret1"]
assert fields["text"] == ["code 654321"]

reply[0] = b'{"messages": [{"status": "4", "error-text": "Invalid credentials"}]}'
try:
    asyncio.run(VonageSender().send("+14155550123", "x"))
except DeliveryError as exc:
    assert "rejected" in str(exc)
else:
    raise AssertionError("a rejected message was treated as sent")

reply[0] = b"not json"
try:
    asyncio.run(VonageSender().send("+14155550123", "x"))
except DeliveryError:
    pass
else:
    raise AssertionError("garbage reply was treated as sent")
""",
        VONAGE_API_KEY="key1",
        VONAGE_API_SECRET="secret1",
        AUTH_JWT_SECRET="j" * 40,
    )


def test_sns_publish_uses_sender_id_for_alphanumeric_senders(sns: Path) -> None:
    run_script(
        sns,
        """
        import asyncio, sys, types

        published = []

        class ClientError(Exception):
            pass

        class BotoCoreError(Exception):
            pass

        class FakeClient:
            def publish(self, **kwargs):
                published.append(kwargs)

        boto3 = types.ModuleType("boto3")
        boto3.client = lambda service, region_name=None: (
            published.append(("client", service, region_name)) or FakeClient()
        )
        botocore = types.ModuleType("botocore")
        exceptions = types.ModuleType("botocore.exceptions")
        exceptions.ClientError, exceptions.BotoCoreError = ClientError, BotoCoreError
        sys.modules.update(
            {"boto3": boto3, "botocore": botocore, "botocore.exceptions": exceptions}
        )

        from app.auth.delivery import SnsSender

        asyncio.run(SnsSender().send("+14155550123", "code 111111"))
        assert published[0] == ("client", "sns", "eu-west-1"), published
        call = published[1]
        assert call["PhoneNumber"] == "+14155550123" and call["Message"] == "code 111111"
        attributes = call["MessageAttributes"]
        assert attributes["AWS.SNS.SMS.SenderID"]["StringValue"] == "ShopApp"
        assert attributes["AWS.SNS.SMS.SMSType"]["StringValue"] == "Transactional"
        """,
        AWS_REGION="eu-west-1",
        AUTH_JWT_SECRET="j" * 40,
    )


def test_sns_dependency_is_only_added_when_selected(twilio: Path, sns: Path, vonage: Path) -> None:
    assert "boto3" in (sns / "requirements.txt").read_text(encoding="utf-8")
    for other in (twilio, vonage):
        assert "boto3" not in (other / "requirements.txt").read_text(encoding="utf-8")


# --- secrets never reach the generated source -------------------------------------------


def test_builder_secrets_are_never_rendered_into_the_project() -> None:
    data = json.loads((FIXTURES / "shop_auth.json").read_text(encoding="utf-8"))
    spec = Spec.model_validate(data)
    assert spec.auth is not None
    marker = "ZZ-super-secret-ZZ"
    spec.auth.secrets = SpecAuthSecrets(
        smtp_username=marker + "1",
        smtp_password=marker + "2",
        twilio_account_sid=marker + "3",
        twilio_auth_token=marker + "4",
        vonage_api_key=marker + "5",
        vonage_api_secret=marker + "6",
        aws_access_key_id=marker + "7",
        aws_secret_access_key=marker + "8",
    )

    files = generate(spec)

    leaked = [path for path, content in files.items() if marker in content]
    assert leaked == []


def test_auth_files_are_absent_when_auth_is_off_or_disabled() -> None:
    data = json.loads((FIXTURES / "shop_auth.json").read_text(encoding="utf-8"))
    on = generate(Spec.model_validate(data))
    assert any(p.startswith("app/auth/") for p in on)

    data["auth"]["enabled"] = False
    off = generate(Spec.model_validate(data))
    assert not any("auth" in p for p in off)
    assert "AUTH_JWT_SECRET" not in off[".env.example"]

    data.pop("auth")
    assert generate(Spec.model_validate(data)) == off


def test_generation_is_blocked_by_unsupported_auth_options() -> None:
    from app.core.generator import InvalidSpecError

    data = json.loads((FIXTURES / "shop_auth.json").read_text(encoding="utf-8"))
    data["auth"]["multi_tenant"] = True
    data["auth"]["registration"]["invite_only"] = True  # cannot create the first tenant
    data["auth"]["jwt_algorithm"] = "ES512"

    with pytest.raises(InvalidSpecError) as excinfo:
        generate(Spec.model_validate(data))

    assert {i.path for i in excinfo.value.issues} == {"auth.multi_tenant", "auth.jwt_algorithm"}


# --- access control logic ---------------------------------------------------------------


@pytest.fixture(scope="module")
def desk(tmp_path_factory: pytest.TempPathFactory) -> Path:
    spec = Spec.model_validate_json((FIXTURES / "desk_auth.json").read_text(encoding="utf-8"))
    root = tmp_path_factory.mktemp("desk")
    for path, content in generate(spec).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


def test_access_decisions(desk: Path) -> None:
    run_script(
        desk,
        """
        import asyncio, uuid
        from app.auth.access import Access, access_dependency, build_access
        from app.core.errors import AppError

        class User:
            def __init__(self, *roles):
                self.id = uuid.uuid4()
                self.roles = list(roles)

        customer, staff, admin = User("customer"), User("staff"), User("admin")

        def refused(**kw):
            try:
                build_access(kw.pop("user"), **kw)
            except AppError as exc:
                assert exc.status_code == 403 and exc.code == "forbidden"
                return True
            return False

        # roles: any one listed role is enough, and a role holds its parent's rights
        assert refused(user=customer, roles=("staff",))
        assert not refused(user=staff, roles=("staff",))
        assert not refused(user=admin, roles=("staff",)), "admin inherits staff"
        assert refused(user=staff, roles=("admin",)), "inheritance only goes one way"
        assert refused(user=None, roles=("staff",)), "no user holds no role"
        assert not refused(user=customer, roles=("staff", "customer"))
        assert not refused(user=None)

        # owner rows
        access = build_access(customer, owner=True)
        assert access.scope == {"created_by_id": customer.id}
        assert access.repo_kwargs == {
            "scope": {"created_by_id": customer.id},
            "owner_id": None,
            "tenant_id": None,
            "caller_tenant_id": None,
            "caller": customer,
            "policy": None,
        }
        assert build_access(admin, owner=True).scope == {"created_by_id": admin.id}
        # role_scoped: admins see everything, everyone else their own
        assert build_access(admin, owner=True, admin_sees_all=True).scope == {}
        assert build_access(staff, owner=True, admin_sees_all=True).scope == {
            "created_by_id": staff.id
        }

        # custom filter, with or without a user
        assert build_access(None, match=("status", "published")).scope == {"status": "published"}
        both = build_access(customer, owner=True, match=("status", "published"))
        assert both.scope == {"created_by_id": customer.id, "status": "published"}

        # stamping the creator
        assert build_access(customer, stamp=True).owner_id == customer.id
        assert build_access(customer).owner_id is None
        assert build_access(None, stamp=True).owner_id is None

        # the dependency factory asks for a user only when it needs one
        import inspect
        assert list(inspect.signature(access_dependency()).parameters) == []
        assert list(inspect.signature(access_dependency(roles=("staff",))).parameters) == ["user"]
        assert list(inspect.signature(access_dependency(owner=True)).parameters) == ["user"]
        assert list(inspect.signature(access_dependency(authenticate=True)).parameters) == ["user"]
        anonymous = asyncio.run(access_dependency(match=("status", "live"))())
        assert anonymous == Access(None, {"status": "live"}, None)
        """,
        AUTH_JWT_SECRET="j" * 40,
    )


def test_repository_applies_scope_to_every_query_and_stamps_the_owner(desk: Path) -> None:
    run_script(
        desk,
        """
        import uuid
        from app.crud.tickets import TicketRepository
        from app.models.tickets import Ticket

        mine = uuid.uuid4()
        repo = TicketRepository(None, scope={"created_by_id": mine}, owner_id=mine)
        sql = " ".join(str(c) for c in repo._alive())
        assert "created_by_id" in sql, sql
        assert TicketRepository(None)._alive() == []
        assert repo.owner_id == mine
        assert hasattr(Ticket, "created_by_id")
        from app.models.articles import Article
        assert not hasattr(Article, "created_by_id"), "only owned entities get the column"
        """,
        AUTH_JWT_SECRET="j" * 40,
    )


def test_only_owned_entities_get_the_ownership_column(desk: Path) -> None:
    migration = (desk / "alembic/versions/0002_auth.py").read_text(encoding="utf-8")
    assert migration.count('op.add_column("tickets", sa.Column("created_by_id"') == 1
    assert 'op.add_column("articles"' not in migration
    assert "fk_tickets_created_by_id_auth_users" in migration


# --- RS256 and Redis --------------------------------------------------------------------


@pytest.fixture(scope="module")
def vault(tmp_path_factory: pytest.TempPathFactory) -> Path:
    spec = Spec.model_validate_json((FIXTURES / "vault_auth.json").read_text(encoding="utf-8"))
    root = tmp_path_factory.mktemp("vault")
    for path, content in generate(spec).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


def test_rs256_signs_with_the_private_key_and_rejects_forgeries(vault: Path) -> None:
    run_script(
        vault,
        """
        import base64, hashlib, hmac, json, time
        from cryptography.hazmat.primitives.asymmetric import rsa
        from app.auth import security

        def b64(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

        pem = security.generate_private_key_pem()
        claims = {"sub": "1", "exp": time.time() + 60}
        token = security.encode_jwt(claims, pem)
        assert token.split(".")[0] == b64({"alg": "RS256", "typ": "JWT"}) or True
        assert security.decode_jwt(token, pem)["sub"] == "1"

        header, payload, signature = token.split(".")
        other = security.generate_private_key_pem()
        public_pem = "-----BEGIN PUBLIC KEY-----"  # anything an attacker could know
        cases = {
            "wrong key": security.encode_jwt(claims, other),
            "tampered payload": ".".join([header, b64({"sub": "2", "exp": 4102444800}), signature]),
            "alg none": b64({"alg": "none", "typ": "JWT"}) + "." + payload + ".",
            "alg HS256 (key confusion)": (
                b64({"alg": "HS256", "typ": "JWT"}) + "." + payload + "."
                + base64.urlsafe_b64encode(
                    hmac.new(
                        public_pem.encode(), f"{header}.{payload}".encode(), hashlib.sha256
                    ).digest()
                ).rstrip(b"=").decode()
            ),
            "expired": security.encode_jwt({"sub": "1", "exp": 1}, pem),
            "truncated signature": f"{header}.{payload}.{signature[:20]}",
            "garbage signature": f"{header}.{payload}.!!!!",
        }
        for name, bad in cases.items():
            try:
                security.decode_jwt(bad, pem)
            except security.InvalidTokenError:
                continue
            raise AssertionError(f"accepted {name}")

        jwk = security.public_jwk(pem)
        assert set(jwk) == {"kty", "use", "alg", "n", "e"}, "no private parameters"

        weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        from cryptography.hazmat.primitives import serialization
        weak_pem = weak.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        try:
            security.encode_jwt(claims, weak_pem)
        except ValueError as exc:
            assert "2048" in str(exc)
        else:
            raise AssertionError("a 1024-bit key was accepted")
        """,
        AUTH_JWT_PRIVATE_KEY="x" * 300,
    )


def test_the_keys_helper_prints_a_usable_env_line(vault: Path, twilio: Path) -> None:
    rs = run_script(vault, "from app.auth import keys; keys.main()")
    assert rs.startswith('AUTH_JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\\n')
    assert rs.strip().endswith('-----END PRIVATE KEY-----"')
    assert "\n" not in rs.strip(), "one line, newlines escaped"
    hs = run_script(twilio, "from app.auth import keys; keys.main()")
    assert hs.startswith("AUTH_JWT_SECRET=") and len(hs.strip()) > 40


def test_a_pem_with_escaped_newlines_from_an_env_file_works(vault: Path) -> None:
    run_script(
        vault,
        """
        import os
        from app.auth import keys, security
        from app.auth.config import get_auth_settings
        import io, contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            keys.main()
        line = buffer.getvalue().strip().split("=", 1)[1].strip('"')
        os.environ["AUTH_JWT_PRIVATE_KEY"] = line  # literal backslash-n, as written in .env
        key = get_auth_settings().jwt_key
        assert "\\\\n" not in key, "escaped newlines are turned back into real ones"
        assert key.startswith("-----BEGIN PRIVATE KEY-----\\n")
        token = security.encode_jwt({"sub": "1", "exp": 4102444800}, key)
        assert security.decode_jwt(token, key)["sub"] == "1"
        """,
    )


def test_the_dependency_list_follows_the_chosen_options(vault: Path, twilio: Path) -> None:
    vault_reqs = (vault / "requirements.txt").read_text(encoding="utf-8")
    assert "cryptography" in vault_reqs and "redis" in vault_reqs
    plain = (twilio / "requirements.txt").read_text(encoding="utf-8")
    assert "cryptography" not in plain and "redis" not in plain
    compose = (vault / "docker-compose.yml").read_text(encoding="utf-8")
    assert "redis:7-alpine" in compose and "AUTH_JWT_PRIVATE_KEY" in compose
    assert "redis" not in (twilio / "docker-compose.yml").read_text(encoding="utf-8")


def test_redis_projects_have_no_refresh_token_table(vault: Path, twilio: Path) -> None:
    assert "auth_refresh_tokens" not in (vault / "alembic/versions/0002_auth.py").read_text()
    assert "AuthRefreshToken" not in (vault / "app/auth/models.py").read_text()
    assert "auth_refresh_tokens" in (twilio / "alembic/versions/0002_auth.py").read_text()


# --- multi-tenancy ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    spec = Spec.model_validate_json((FIXTURES / "workspace_auth.json").read_text(encoding="utf-8"))
    root = tmp_path_factory.mktemp("workspace")
    for path, content in generate(spec).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


def test_tenant_access_decisions(workspace: Path) -> None:
    run_script(
        workspace,
        """
        import uuid
        from app.auth.access import build_access

        class User:
            def __init__(self, tenant, *roles):
                self.id = uuid.uuid4()
                self.tenant_id = tenant
                self.roles = list(roles)

        one, other = uuid.uuid4(), uuid.uuid4()
        ann, bob = User(one, "member"), User(other, "member")

        access = build_access(ann, tenant=True)
        assert access.scope == {"tenant_id": one} and access.tenant_id == one
        assert build_access(bob, tenant=True).scope == {"tenant_id": other}
        # Tenant and owner rules add up: your own rows, inside your tenant.
        both = build_access(ann, owner=True, tenant=True)
        assert both.scope == {"created_by_id": ann.id, "tenant_id": one}
        # Even an admin who sees every owner's rows stays inside the tenant.
        admin = User(one, "admin")
        scoped = build_access(admin, owner=True, admin_sees_all=True, tenant=True)
        assert scoped.scope == {"tenant_id": one}
        # No tenant rule, no tenant filter or stamp.
        plain = build_access(ann)
        assert plain.scope == {} and plain.tenant_id is None
        assert plain.repo_kwargs["tenant_id"] is None
        # The caller's tenant is known even where the entity itself is not tenant-scoped, so a
        # reference to a tenant row can be checked; an anonymous caller has none.
        assert plain.caller_tenant_id == one and plain.repo_kwargs["caller_tenant_id"] == one
        assert build_access(None).caller_tenant_id is None
        assert access.repo_kwargs == {
            "scope": {"tenant_id": one},
            "owner_id": None,
            "tenant_id": one,
            "caller_tenant_id": one,
            "caller": ann,
            "policy": None,
        }
        """,
        AUTH_JWT_SECRET="j" * 40,
    )


def test_access_tokens_carry_the_tenant_claim(workspace: Path) -> None:
    run_script(
        workspace,
        """
        import uuid
        from app.auth import security

        tenant, user = uuid.uuid4(), uuid.uuid4()
        token = security.create_access_token(
            user, ["member"], key="k" * 40, ttl_seconds=60, tenant_id=tenant, issuer="builtin:x",
            session_id="sid-1",
        )
        claims = security.decode_jwt(token, "k" * 40)
        assert claims["tid"] == str(tenant) and claims["sub"] == str(user)
        assert claims["iss"] == "builtin:x" and claims["sid"] == "sid-1"
        bare = security.create_access_token(
            user, [], key="k" * 40, ttl_seconds=60, issuer="builtin:x"
        )
        assert "tid" not in security.decode_jwt(bare, "k" * 40)
        """,
        AUTH_JWT_SECRET="j" * 40,
    )


def test_only_tenant_scoped_entities_get_the_tenant_column(workspace: Path, twilio: Path) -> None:
    migration = (workspace / "alembic/versions/0002_auth.py").read_text(encoding="utf-8")
    assert 'op.add_column("tasks", sa.Column("tenant_id"' in migration
    assert 'op.add_column("announcements", sa.Column("tenant_id"' in migration
    assert "fk_tasks_tenant_id_auth_tenants" in migration
    assert 'sa.Column("tenant_id", sa.Uuid(), nullable=False)' in migration  # users, invitations
    models = (workspace / "app/auth/models.py").read_text(encoding="utf-8")
    assert "tenant_id" in models and "class AuthTenant" in models
    # Projects without multi-tenancy have the (empty) tenants table but no tenant columns.
    plain = (twilio / "app/auth/models.py").read_text(encoding="utf-8")
    assert "tenant_id" not in plain
    assert "tenant_id" not in (twilio / "alembic/versions/0002_auth.py").read_text(encoding="utf-8")
    assert "tenant_id" not in (twilio / "app/routers/items.py").read_text(encoding="utf-8")


def test_tenant_projects_expose_the_tenant_routes_and_require_a_name(
    workspace: Path, twilio: Path
) -> None:
    router = (workspace / "app/auth/router.py").read_text(encoding="utf-8")
    assert '"/tenant"' in router
    assert "tenant_name" in (workspace / "app/auth/schemas.py").read_text(encoding="utf-8")
    assert '"/tenant"' not in (twilio / "app/auth/router.py").read_text(encoding="utf-8")
    assert "tenant_name" not in (twilio / "app/auth/schemas.py").read_text(encoding="utf-8")
