"""Webhook checks (generated): the SSRF guard, signatures, the admin API, delivery with retries, rotation without
downtime, auto-disable, and incoming verification. No network: names resolve through a table and connections go
to in-memory servers (tests/_webhooks_support.py)."""

import datetime as dt
import json
import time
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from structlog.testing import capture_logs

import app.hooks.jobs  # noqa: F401  (registers the project's job handlers, including webhook_delivery)
from app.db import session_factory
from app.events.bus import Event
from app.jobs import definitions as job_defs
from app.jobs import worker
from app.webhooks import definitions, delivery, egress, fanout, handlers, signing, ssrf
from app.webhooks.models import Attempt, Delivery, Endpoint, InboundSeen, Subscription
from tests._auth_support import outbox, sign_in, sign_in_plain  # noqa: F401
from tests._webhooks_support import FakeNet, net  # noqa: F401

ADMIN = 'admin'
EVENT = 'order.created'
INBOUND = 'payments'
QUEUE = job_defs.JOBS[definitions.JOB]["queue"]
HOST = "hooks.example.com"
PUBLIC = "93.184.216.34"
URL = f"https://{HOST}/in"
POLICY = ssrf.Policy(allow_http=False, allowed_ports=())


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _web(net: FakeNet, status: int = 200) -> None:  # noqa: F811
    net.resolve[HOST] = [PUBLIC]
    net.serve(PUBLIC, status)


async def _create(client: AsyncClient, headers: dict[str, str], url: str = URL, events: list[str] | None = None) -> dict:
    response = await client.post("/webhooks/subscriptions", json={"url": url, "event_types": events or [EVENT]}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _sub(sub_id: str) -> Subscription:
    async with session_factory() as session:
        return (await session.execute(sa.select(Subscription).where(Subscription.id == uuid.UUID(sub_id)))).scalar_one()


async def _deliveries() -> list[Delivery]:
    async with session_factory() as session:
        return list((await session.execute(sa.select(Delivery).order_by(Delivery.created_at))).scalars())


async def _attempts() -> list[Attempt]:
    async with session_factory() as session:
        return list((await session.execute(sa.select(Attempt).order_by(Attempt.created_at))).scalars())


async def _sql(statement: str) -> None:
    async with session_factory() as session:
        await session.execute(sa.text(statement))
        await session.commit()


async def _due() -> None:
    """Make every waiting retry due now (no sleeping in tests)."""
    await _sql("UPDATE jb_jobs SET run_at = now() - interval '1 second' WHERE status = 'pending'")


async def _drain() -> int:
    return await worker.drain(session_factory, [QUEUE], "test-worker")


def _event(sub: Subscription, event_type: str = EVENT) -> Event:
    return Event(
        id=uuid.uuid4(), type=event_type, aggregate_type="Order", aggregate_id=uuid.uuid4(), seq=1,
        tenant_id=sub.tenant_id, occurred_at=_now(), payload={"data": {"reference": "A-1"}},
    )


async def _announce(sub_id: str, event_type: str = EVENT) -> Event:
    event = _event(await _sub(sub_id), event_type)
    await fanout.fan_out(event)
    return event


def _verifies(request, secret: str) -> bool:  # noqa: ANN001
    return signing.verify(
        request.header("webhook-signature"), request.header("webhook-id"), request.header("webhook-timestamp"),
        request.body, [secret], tolerance_seconds=300,
    )


# --- the SSRF guard -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://10.0.0.1/", "https://172.16.0.9/", "https://192.168.1.1/", "https://127.0.0.1/", "https://0.0.0.0/",
        "https://169.254.169.254/latest/meta-data/", "https://100.64.0.1/", "https://100.100.100.200/",
        "https://198.18.0.1/", "https://224.0.0.1/", "https://255.255.255.255/", "https://[::1]/", "https://[::]/",
        "https://[fe80::1]/", "https://[fd00:ec2::254]/", "https://[fc00::1]/", "https://[::ffff:127.0.0.1]/",
        "https://[::ffff:7f00:1]/", "https://[::ffff:10.0.0.1]/", "https://[::ffff:169.254.169.254]/",
        "https://[64:ff9b::7f00:1]/", "https://[2002:7f00:1::]/", "https://[2002:a9fe:a9fe::]/", "https://[2001::1]/", "https://[::ffff:0:7f00:1]/", "https://[::ffff:0:a00:1]/", "https://[5f00::1]/", "https://[::7f00:1]/",
        "https://2130706433/", "https://0x7f000001/", "https://0x7f.1/", "https://0177.0.0.1/", "https://127.1/",
        "https://017700000001/", "https://localhost/", "https://LOCALHOST./", "https://foo.localhost/",
        "https://metadata.google.internal/", "https://db.internal/", "https://printer.local/",
    ],
)
def test_private_loopback_link_local_and_ambiguous_addresses_are_refused(url: str) -> None:
    with pytest.raises(ssrf.Blocked):
        ssrf.parse_target(url, POLICY)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com@127.0.0.1/", "https://user:pass@hooks.example.com/", "https://hooks.example.com@evil.example.org/",
        "https://127.0.0.1#@hooks.example.com/", "https://hooks.example.com\\@127.0.0.1/", "https://hooks.example.com:443@127.0.0.1/",
        "https://@hooks.example.com/", "https://hooks.example.com/%0d%0aX: y", "https://hooks.example.com/a b",
        "https://hooks.example.com/\r\nHost: evil", "https://hooks.example.com/#frag", "https://hooks.exämple.com/",
        "https://hooks.example.com:99999/", "https://hooks.example.com:abc/", "https://:443/", "https:///path",
    ],
)
def test_user_info_and_parser_confusion_tricks_are_refused(url: str) -> None:
    try:
        target = ssrf.parse_target(url, POLICY)
    except ssrf.Blocked:
        return
    # the one allowed shape: a percent-encoded CRLF stays encoded in the path and can split nothing
    assert "\r" not in target.request_target and "\n" not in target.request_target and url.startswith("https://hooks.example.com/%0d")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://hooks.example.com/", "gopher://hooks.example.com/", "javascript:alert(1)", "http://hooks.example.com/", "//hooks.example.com/", "hooks.example.com"])
def test_only_https_is_allowed_by_default(url: str) -> None:
    with pytest.raises(ssrf.Blocked):
        ssrf.parse_target(url, POLICY)


@pytest.mark.parametrize("port", [22, 25, 3306, 5432, 6379, 8080, 9200, 11211, 2375, 80])
def test_only_allow_listed_ports_are_used(port: int) -> None:
    with pytest.raises(ssrf.Blocked):
        ssrf.parse_target(f"https://hooks.example.com:{port}/", POLICY)
    assert ssrf.parse_target(f"https://hooks.example.com:{port}/", ssrf.Policy(False, (port,))).port == port
    assert ssrf.parse_target("https://hooks.example.com/x?a=1", POLICY).port == 443


def test_http_needs_the_spec_flag_and_a_listed_port() -> None:
    allowed = ssrf.Policy(allow_http=True, allowed_ports=())
    assert ssrf.parse_target("http://hooks.example.com/", allowed).port == 80
    with pytest.raises(ssrf.Blocked):
        ssrf.parse_target("http://hooks.example.com:8080/", allowed)
    with pytest.raises(ssrf.Blocked):
        ssrf.parse_target("http://127.0.0.1/", allowed)


def test_public_addresses_and_names_pass() -> None:
    assert ssrf.parse_target(f"https://{PUBLIC}/hook?x=1", POLICY).is_ip
    target = ssrf.parse_target("https://Hooks.Example.com./a/b?c=d", POLICY)
    assert (target.host, target.request_target, target.is_ip) == ("hooks.example.com", "/a/b?c=d", False)
    assert ssrf.parse_target("https://[2606:4700:4700::1111]/", POLICY).is_ip


async def test_a_name_with_any_private_answer_is_refused(net: FakeNet) -> None:  # noqa: F811
    target = ssrf.parse_target(URL, POLICY)
    for answers in (["10.0.0.5"], ["127.0.0.1"], [PUBLIC, "169.254.169.254"], ["::1"], ["::ffff:10.0.0.1"], ["fe80::1%eth0"], ["not-an-ip"]):
        net.resolve[HOST] = answers
        with pytest.raises(ssrf.Blocked):
            await ssrf.pin(target)
    net.resolve[HOST] = [PUBLIC, "93.184.216.35"]
    assert await ssrf.pin(target) == PUBLIC
    net.resolve.pop(HOST)
    with pytest.raises(ssrf.ResolveFailed):
        await ssrf.pin(target)


async def test_dns_rebinding_cannot_swap_the_address_between_check_and_connect(net: FakeNet) -> None:  # noqa: F811
    net.resolve[HOST] = [[PUBLIC], ["127.0.0.1"]]  # first lookup public, every later lookup loopback
    net.serve(PUBLIC)
    net.serve("127.0.0.1")
    response = await egress.post(URL, b"{}", {}, policy=POLICY, timeout=5)
    assert response.status == 200
    assert net.lookups == [HOST]  # the name is resolved exactly once
    assert net.connects == [(PUBLIC, 443, HOST)]  # and the connection goes to that IP, TLS checked against the name
    with pytest.raises(ssrf.Blocked):  # the next delivery sees the rebinding answer and is refused
        await egress.post(URL, b"{}", {}, policy=POLICY, timeout=5)
    assert net.connects == [(PUBLIC, 443, HOST)]


async def test_a_peer_that_is_not_public_is_refused_after_connecting(net: FakeNet) -> None:  # noqa: F811
    _web(net)
    net.peer_override[PUBLIC] = "10.0.0.5"
    with pytest.raises(ssrf.Blocked):
        await egress.post(URL, b"{}", {}, policy=POLICY, timeout=5)
    assert net.requests == []  # nothing was sent


async def test_a_redirect_to_an_internal_address_is_not_followed(net: FakeNet) -> None:  # noqa: F811
    net.resolve[HOST] = [PUBLIC]
    net.serve(PUBLIC, 302, headers="Location: http://169.254.169.254/latest/meta-data/\r\n")
    net.serve("169.254.169.254")
    response = await egress.post(URL, b"{}", {}, policy=POLICY, timeout=5)
    assert response.status == 302
    assert net.connects == [(PUBLIC, 443, HOST)] and len(net.requests) == 1  # one hop, never the Location
    assert delivery.classify(302) == (False, "redirect_not_followed")


@pytest.mark.parametrize("name,value", [("X-A", "ok\r\nX-Injected: 1"), ("X-A\r\nX-B", "ok"), ("X A", "ok"), ("X-A", "\x00")])
async def test_header_injection_is_refused(net: FakeNet, name: str, value: str) -> None:  # noqa: F811
    _web(net)
    with pytest.raises(ssrf.Blocked):
        await egress.post(URL, b"{}", {name: value}, policy=POLICY, timeout=5)
    assert net.connects == []


async def test_a_server_that_hangs_or_answers_garbage_is_a_retryable_failure(net: FakeNet) -> None:  # noqa: F811
    net.resolve[HOST] = [PUBLIC]
    net.answers[PUBLIC] = lambda _r: b"not http at all\r\n\r\n"
    with pytest.raises(egress.EgressError) as bad:
        await egress.post(URL, b"{}", {}, policy=POLICY, timeout=5)
    assert (bad.value.code, bad.value.retryable) == ("bad_response", True)
    net.unreachable.add(PUBLIC)
    with pytest.raises(egress.EgressError) as down:
        await egress.post(URL, b"{}", {}, policy=POLICY, timeout=5)
    assert (down.value.code, down.value.retryable) == ("connect_failed", True)


def test_the_request_names_the_original_host_and_carries_the_body() -> None:
    target = ssrf.parse_target("https://hooks.example.com:8443/x", ssrf.Policy(False, (8443,)))
    raw = egress._request_bytes(target, b'{"a":1}', {"webhook-id": "abc"})
    assert raw.startswith(b"POST /x HTTP/1.1\r\nHost: hooks.example.com:8443\r\n") and raw.endswith(b'\r\n\r\n{"a":1}')


# --- signatures -----------------------------------------------------------------------------------------


def test_a_signature_verifies_only_for_the_same_id_time_body_and_secret() -> None:
    secret = signing.new_secret()
    body = b'{"x":1}'
    now = int(time.time())
    header = signing.sign(secret, "msg_1", now, body)
    assert header.startswith("v1,")
    assert signing.verify(header, "msg_1", str(now), body, [secret], tolerance_seconds=300)
    for args in (
        (header, "msg_2", str(now), body, [secret]),
        (header, "msg_1", str(now + 1), body, [secret]),
        (header, "msg_1", str(now), body + b" ", [secret]),
        (header, "msg_1", str(now), body, [signing.new_secret()]),
        (None, "msg_1", str(now), body, [secret]),
        ("", "msg_1", str(now), body, [secret]),
        ("v2,abc", "msg_1", str(now), body, [secret]),
        ("v1,%%%", "msg_1", str(now), body, [secret]),
        (header, None, str(now), body, [secret]),
        (header, "msg_1", None, body, [secret]),
        (header, "msg_1", "12ab", body, [secret]),
        (header, "msg_1", str(now), body, []),
    ):
        assert not signing.verify(*args, tolerance_seconds=300)  # type: ignore[arg-type]


def test_delivery_ids_cannot_contain_a_dot_so_the_signed_text_is_unambiguous() -> None:
    secret = signing.new_secret()
    header = signing.sign(secret, "a.5", 6, b"x")
    assert signing.verify(header, "a", "5", b"6.x", [secret], tolerance_seconds=10**9, now=5)  # the ambiguity itself
    assert not signing.verify(header, "a.5", "6", b"x", [secret], tolerance_seconds=10**9, now=6)  # ids with a dot are refused
    for bad in ("a.b", "a b", "a/b", "", "x" * 129, "a\u00b2", "a\n"):
        assert not signing.valid_id(bad)
    assert signing.valid_id(str(uuid.uuid4())) and signing.valid_id("msg_2Lq-9:x")


def test_the_signature_is_the_documented_hmac_over_the_raw_body() -> None:
    import base64
    import hashlib
    import hmac

    secret = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
    expected = base64.b64encode(hmac.new(b"0123456789abcdef0123456789abcdef", b"id1.1700000000.{}", hashlib.sha256).digest()).decode()
    assert signing.sign(secret, "id1", 1700000000, b"{}") == "v1," + expected


def test_old_and_far_future_timestamps_are_refused() -> None:
    secret = signing.new_secret()
    now = 1_800_000_000
    for stamp, ok in ((now, True), (now - 299, True), (now - 301, False), (now + 299, True), (now + 301, False), (now - 86400, False)):
        header = signing.sign(secret, "m", stamp, b"{}")
        assert signing.verify(header, "m", str(stamp), b"{}", [secret], tolerance_seconds=300, now=now) is ok


def test_two_secrets_are_accepted_during_a_rotation_and_comparison_is_constant_time() -> None:
    import inspect

    old, new = signing.new_secret(), signing.new_secret()
    header = signing.signature_header([new, old], "m", 1_800_000_000, b"{}")
    assert len(header.split()) == 2
    for secret in (old, new):
        assert signing.verify(header, "m", "1800000000", b"{}", [secret], tolerance_seconds=300, now=1_800_000_000)
    assert "compare_digest" in inspect.getsource(signing.verify) and "==" not in inspect.getsource(signing.verify).split("compare_digest")[0].split("expected")[-1]


# --- the admin API --------------------------------------------------------------------------------------


async def test_only_the_admin_role_may_use_the_webhook_api(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    plain = await sign_in_plain(client, "plain@example.com")
    for headers, status in ((plain, 403), ({}, 401)):
        assert (await client.get("/webhooks/subscriptions", headers=headers)).status_code == status
        assert (await client.post("/webhooks/subscriptions", json={"url": URL, "event_types": [EVENT]}, headers=headers)).status_code == status
        assert (await client.get("/webhooks/events", headers=headers)).status_code == status
        assert (await client.put(f"/webhooks/inbound/{INBOUND or 'x'}/secret", json={"value": "x" * 20}, headers=headers)).status_code == status


async def test_unsafe_urls_and_unlisted_events_are_refused_when_subscribing(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    for url in ("https://127.0.0.1/", "https://169.254.169.254/", "http://hooks.example.com/", "https://u:p@hooks.example.com/", "https://2130706433/", "file:///etc/passwd"):
        response = await client.post("/webhooks/subscriptions", json={"url": url, "event_types": [EVENT]}, headers=admin)
        assert response.status_code == 422 and response.json()["code"] == "url_not_allowed", url
    for events in (["order.nonsense"], [EVENT, "customer.deleted_everything"]):
        response = await client.post("/webhooks/subscriptions", json={"url": URL, "event_types": events}, headers=admin)
        assert response.status_code == 422, events
    assert (await client.post("/webhooks/subscriptions", json={"url": URL, "event_types": []}, headers=admin)).status_code == 422
    assert (await client.post("/webhooks/subscriptions", json={"url": URL, "event_types": [EVENT], "secret": "mine"}, headers=admin)).status_code == 422
    assert (await client.get("/webhooks/subscriptions", headers=admin)).json() == []
    assert (await client.get("/webhooks/events", headers=admin)).json() == list(definitions.EVENTS)


async def test_the_secret_is_shown_once_and_never_stored_in_clear(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    _web(net)
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    created = await _create(client, admin)
    secret = created["secret"]
    assert secret.startswith("whsec_")
    rotated = (await client.post(f"/webhooks/subscriptions/{created['id']}/rotate", headers=admin)).json()
    newest = rotated["secret"]
    await _announce(created["id"])
    with capture_logs() as logs:
        await _drain()
    texts = [
        (await client.get("/webhooks/subscriptions", headers=admin)).text,
        (await client.get(f"/webhooks/subscriptions/{created['id']}", headers=admin)).text,
        (await client.get(f"/webhooks/subscriptions/{created['id']}/deliveries", headers=admin)).text,
        json.dumps(logs, default=str),
    ]
    async with session_factory() as session:
        for table in ("wh_subscriptions", "wh_deliveries", "wh_attempts", "wh_endpoints", "wh_inbound", "provider_credentials"):
            rows = (await session.execute(sa.text(f"SELECT * FROM {table}"))).fetchall()
            texts.append(json.dumps([list(map(str, row)) for row in rows]))
    for text in texts:
        assert secret not in text and newest not in text and secret[6:] not in text and newest[6:] not in text
    assert "ciphertext" not in texts[0]


async def test_a_tenant_never_sees_or_changes_another_tenants_subscriptions(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    first = await sign_in(client, "first@example.com", roles=[ADMIN])
    second = await sign_in(client, "second@example.com", roles=[ADMIN])
    mine = await _create(client, first)
    assert [s["id"] for s in (await client.get("/webhooks/subscriptions", headers=first)).json()] == [mine["id"]]
    assert (await client.get("/webhooks/subscriptions", headers=second)).json() == []
    path = f"/webhooks/subscriptions/{mine['id']}"
    assert (await client.get(path, headers=second)).status_code == 404
    assert (await client.patch(path, json={"description": "x"}, headers=second)).status_code == 404
    assert (await client.post(path + "/rotate", headers=second)).status_code == 404
    assert (await client.delete(path, headers=second)).status_code == 404
    assert (await client.get(path + "/deliveries", headers=second)).status_code == 404
    event = _event(await _sub(mine["id"]))
    other = _event(await _sub(mine["id"]))
    other_tenant = uuid.uuid4()
    await fanout.fan_out(Event(**{**other.model_dump(), "tenant_id": other_tenant}))
    await fanout.fan_out(event)
    assert len(await _deliveries()) == 1  # the other tenant's event did not reach this tenant's subscription
    assert (await client.delete(f"/webhooks/subscriptions/{mine['id']}", headers=first)).status_code == 204
    async with session_factory() as session:
        assert (await session.execute(sa.text("SELECT count(*) FROM provider_credentials WHERE provider = 'webhooks'"))).scalar_one() == 0


# --- delivery -------------------------------------------------------------------------------------------


async def test_an_event_becomes_one_signed_delivery_with_a_stable_id(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    _web(net)
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)
    event = await _announce(sub["id"])
    await fanout.fan_out(event)  # the bus delivers at least once: a repeat changes nothing
    rows = await _deliveries()
    assert len(rows) == 1 and rows[0].event_id == event.id and rows[0].status == "pending"
    async with session_factory() as session:
        assert (await session.execute(sa.text("SELECT count(*) FROM jb_jobs WHERE name = 'webhook_delivery'"))).scalar_one() == 1
    assert await _drain() == 1
    (request,) = net.requests
    assert request.ip == PUBLIC and request.hostname == HOST and request.tls
    assert request.header("webhook-id") == str(rows[0].id) and request.header("content-type") == "application/json"
    assert _verifies(request, sub["secret"])
    assert not signing.verify(request.header("webhook-signature"), request.header("webhook-id"), request.header("webhook-timestamp"), request.body + b" ", [sub["secret"]], tolerance_seconds=300)
    envelope = json.loads(request.body)
    assert envelope["id"] == str(event.id) and envelope["type"] == EVENT and envelope["data"] == event.payload
    done = (await _deliveries())[0]
    assert (done.status, done.attempts, done.last_status_code) == ("delivered", 1, 200)
    assert [(a.attempt, a.outcome, a.status_code) for a in await _attempts()] == [(1, "delivered", 200)]
    log = (await client.get(f"/webhooks/subscriptions/{sub['id']}/deliveries", headers=admin)).json()
    assert [(d["status"], d["attempts"]) for d in log] == [("delivered", 1)]
    attempts = (await client.get(f"/webhooks/deliveries/{rows[0].id}/attempts", headers=admin)).json()
    assert [a["outcome"] for a in attempts] == ["delivered"]


async def test_only_subscribed_and_listed_events_are_delivered(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    _web(net)
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)
    await _announce(sub["id"], "unlisted.event")  # not in the spec: never announced
    for other in definitions.EVENTS:
        if other != EVENT:
            await _announce(sub["id"], other)  # listed, but this subscription did not ask for it
    assert await _deliveries() == []
    disabled = await _create(client, admin)
    await client.post(f"/webhooks/subscriptions/{disabled['id']}/disable", headers=admin)
    await _announce(sub["id"])
    assert len(await _deliveries()) == 1  # the disabled subscription got nothing


async def test_failures_are_retried_with_backoff_and_every_try_has_the_same_id_and_body(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    net.resolve[HOST] = [PUBLIC]
    net.serve_sequence(PUBLIC, [503, 429, 200])
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)
    await _announce(sub["id"])
    assert await _drain() == 1
    assert (await _deliveries())[0].status == "pending" and (await _deliveries())[0].last_error == "http_503"
    assert await _drain() == 0  # the retry waits for its backoff
    await _due()
    await _drain()
    assert (await _deliveries())[0].last_error == "http_429"
    await _due()
    await _drain()
    done = (await _deliveries())[0]
    assert (done.status, done.attempts, done.last_error) == ("delivered", 3, None)
    assert len(net.requests) == 3
    assert len({r.header("webhook-id") for r in net.requests}) == 1 and len({r.body for r in net.requests}) == 1
    assert [a.outcome for a in await _attempts()] == ["http_503", "http_429", "delivered"]
    assert (await _sub(sub["id"])).consecutive_failures == 0  # a success resets the count


async def test_permanent_refusals_are_not_retried_and_the_last_retry_ends_the_delivery(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    net.resolve[HOST] = [PUBLIC]
    net.serve(PUBLIC, 410)
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)
    await _announce(sub["id"])
    await _drain()
    gone = (await _deliveries())[0]
    assert (gone.status, gone.attempts, gone.last_error) == ("failed", 1, "http_410") and len(net.requests) == 1
    await _drain()
    assert len(net.requests) == 1
    net.serve(PUBLIC, 500)
    await client.post(f"/webhooks/subscriptions/{sub['id']}/enable", headers=admin)
    await _announce(sub["id"])
    second = [d for d in await _deliveries() if d.status == "pending"][0]
    outcome = await delivery.deliver(second.id, attempt=4, last_attempt=True)
    assert (outcome.state, outcome.code) == ("failed", "http_500")


async def test_a_redirect_answer_is_a_failure_and_the_location_is_never_requested(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    net.resolve[HOST] = [PUBLIC]
    net.serve(PUBLIC, 301, headers="Location: https://169.254.169.254/\r\n")
    net.serve("169.254.169.254")
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)
    await _announce(sub["id"])
    await _drain()
    row = (await _deliveries())[0]
    assert (row.status, row.last_error, row.attempts) == ("failed", "redirect_not_followed", 1)
    assert [c[0] for c in net.connects] == [PUBLIC]


async def test_a_name_that_now_resolves_to_an_internal_address_is_refused_at_delivery(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    net.resolve[HOST] = [PUBLIC]
    net.serve(PUBLIC)
    net.serve("10.0.0.5")
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)  # the name resolved to a public address when it was subscribed
    net.resolve[HOST] = ["10.0.0.5"]  # ... and was re-pointed afterwards
    await _announce(sub["id"])
    await _drain()
    row = (await _deliveries())[0]
    assert (row.status, row.last_error) == ("failed", "blocked_address_not_public")
    assert net.connects == [] and net.requests == []  # not one byte left the process


async def test_consecutive_failures_disable_the_subscription_and_a_success_resets_the_count(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    net.resolve[HOST] = [PUBLIC]
    net.serve(PUBLIC, 500)
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)
    limit = definitions.MAX_CONSECUTIVE_FAILURES
    await _announce(sub["id"])
    did = (await _deliveries())[0].id
    for n in range(1, limit):
        await delivery.deliver(did, attempt=n, last_attempt=False)
    assert (await _sub(sub["id"])).status == "active" and (await _sub(sub["id"])).consecutive_failures == limit - 1
    net.serve(PUBLIC, 200)
    await delivery.deliver(did, attempt=limit, last_attempt=False)
    assert (await _sub(sub["id"])).consecutive_failures == 0
    net.serve(PUBLIC, 500)
    await _announce(sub["id"])
    second = [d for d in await _deliveries() if d.status == "pending"][0].id
    for n in range(1, limit + 1):
        await delivery.deliver(second, attempt=n, last_attempt=False)
    row = await _sub(sub["id"])
    assert (row.status, row.disabled_reason, row.consecutive_failures) == ("disabled", "consecutive_failures", limit)
    shown = (await client.get(f"/webhooks/subscriptions/{sub['id']}", headers=admin)).json()
    assert shown["status"] == "disabled" and shown["disabled_reason"] == "consecutive_failures"
    after = await delivery.deliver(second, attempt=limit + 1, last_attempt=False)
    assert (after.state, after.code) == ("skipped", "subscription_inactive")
    before = len(await _deliveries())
    await _announce(sub["id"])
    assert len(await _deliveries()) == before  # nothing new is created for a disabled subscription
    assert (await client.post(f"/webhooks/subscriptions/{sub['id']}/enable", headers=admin)).json()["status"] == "active"
    await _announce(sub["id"])
    assert len(await _deliveries()) == before + 1


async def test_rotation_signs_with_both_secrets_during_the_overlap_and_only_the_new_one_after(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    _web(net)
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)
    old = sub["secret"]
    rotated = (await client.post(f"/webhooks/subscriptions/{sub['id']}/rotate", json={"overlap_hours": 2}, headers=admin)).json()
    new = rotated["secret"]
    assert new != old and rotated["rotating"] is True and rotated["secret_version"] == 2
    await _announce(sub["id"])
    await _drain()
    during = net.requests[-1]
    assert len(during.header("webhook-signature").split()) == 2
    assert _verifies(during, old) and _verifies(during, new)  # a receiver on either secret keeps working
    await _sql("UPDATE wh_subscriptions SET previous_expires_at = now() - interval '1 minute'")
    await _announce(sub["id"])
    await _drain()
    after = net.requests[-1]
    assert len(after.header("webhook-signature").split()) == 1
    assert _verifies(after, new) and not _verifies(after, old)
    assert (await client.get(f"/webhooks/subscriptions/{sub['id']}", headers=admin)).json()["rotating"] is False
    again = (await client.post(f"/webhooks/subscriptions/{sub['id']}/rotate", headers=admin)).json()
    assert again["secret_version"] == 3
    async with session_factory() as session:
        names = (await session.execute(sa.text("SELECT key_name FROM provider_credentials WHERE provider = 'webhooks' ORDER BY key_name"))).scalars().all()
    assert len(names) == 2 and all(n.startswith("out_") for n in names)  # v1 was dropped; v2 and v3 remain


async def test_a_subscription_without_its_secret_fails_closed(client: AsyncClient, outbox, net: FakeNet) -> None:  # noqa: ANN001, F811
    _web(net)
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    sub = await _create(client, admin)
    await _sql("DELETE FROM provider_credentials WHERE provider = 'webhooks'")
    await _announce(sub["id"])
    await _drain()
    assert (await _deliveries())[0].last_error == "no_secret" and net.requests == []


# --- incoming -------------------------------------------------------------------------------------------


@pytest.fixture
def seen():  # noqa: ANN201
    saved = dict(handlers._HANDLERS)
    handlers.clear_handlers()
    calls: list[tuple[str, object]] = []

    @handlers.inbound(INBOUND)
    async def record(ctx: handlers.InboundContext) -> None:
        calls.append((ctx.delivery_id, ctx.json()))

    yield calls
    handlers._HANDLERS.clear()
    handlers._HANDLERS.update(saved)


def _signed(body: bytes, secret: str, msg_id: str = "msg_1", stamp: int | None = None) -> dict[str, str]:
    stamp = int(time.time()) if stamp is None else stamp
    return {
        "content-type": "application/json", "webhook-id": msg_id, "webhook-timestamp": str(stamp),
        "webhook-signature": signing.sign(secret, msg_id, stamp, body),
    }


async def _in_url(client: AsyncClient, admin: dict[str, str]) -> str:
    secret_set = await client.put(f"/webhooks/inbound/{INBOUND}/secret", json={"value": SECRET}, headers=admin)
    assert secret_set.status_code == 200 and SECRET not in secret_set.text
    async with session_factory() as session:
        row = (await session.execute(sa.select(Endpoint))).scalar_one()
    return f"/webhooks/in/{INBOUND}/{row.tenant_id}"


SECRET = "whsec_" + "dGVzdC1pbmNvbWluZy1zZWNyZXQtMDEyMzQ1Njc4OWFiY2RlZg=="
BODY = b'{"type":"paid","amount":5}'


async def test_an_unsigned_or_badly_signed_request_is_rejected_and_the_handler_never_runs(client: AsyncClient, outbox, net: FakeNet, seen) -> None:  # noqa: ANN001, F811
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    url = await _in_url(client, admin)
    good = _signed(BODY, SECRET)
    stale = _signed(BODY, SECRET, stamp=int(time.time()) - 3600)
    future = _signed(BODY, SECRET, stamp=int(time.time()) + 3600)
    cases = [
        {"content-type": "application/json"},  # unsigned
        {**good, "webhook-signature": ""},
        {**good, "webhook-signature": "v1,AAAA"},
        {**good, "webhook-signature": "garbage"},
        {k: v for k, v in good.items() if k != "webhook-id"},
        {k: v for k, v in good.items() if k != "webhook-timestamp"},
        {**good, "webhook-id": "msg_other"},  # the id is part of what is signed
        stale,
        future,
        _signed(BODY, "whsec_" + "b3RoZXItc2VjcmV0LW90aGVyLXNlY3JldC0wMDAwMDAwMA=="),
    ]
    for headers in cases:
        response = await client.post(url, content=BODY, headers=headers)
        assert response.status_code == 401 and response.json()["code"] == "invalid_signature", headers
    assert (await client.post(url, content=BODY + b" ", headers=good)).status_code == 401  # tampered body
    assert seen == []
    async with session_factory() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(InboundSeen))).scalar_one() == 0
    assert (await client.post(url, content=BODY, headers=good)).status_code == 200


async def test_an_endpoint_without_a_stored_secret_rejects_everything(client: AsyncClient, outbox, net: FakeNet, seen) -> None:  # noqa: ANN001, F811
    path = f"/webhooks/in/{INBOUND}" + ("/" + str(uuid.uuid4()) if True else "")
    assert (await client.post(path, content=BODY, headers=_signed(BODY, SECRET))).status_code == 401
    assert (await client.post("/webhooks/in/unknown_endpoint" + ("/" + str(uuid.uuid4()) if True else ""), content=BODY, headers=_signed(BODY, SECRET))).status_code == 404
    assert seen == []


async def test_a_delivery_id_is_handled_once_and_a_replay_is_acknowledged_without_running_again(client: AsyncClient, outbox, net: FakeNet, seen) -> None:  # noqa: ANN001, F811
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    url = await _in_url(client, admin)
    first = await client.post(url, content=BODY, headers=_signed(BODY, SECRET, "msg_a"))
    assert (first.status_code, first.json()) == (200, {"status": "accepted"})
    replay = await client.post(url, content=BODY, headers=_signed(BODY, SECRET, "msg_a"))
    assert (replay.status_code, replay.json()) == (200, {"status": "duplicate"})
    other = await client.post(url, content=BODY, headers=_signed(BODY, SECRET, "msg_b"))
    assert other.json() == {"status": "accepted"}
    assert [c[0] for c in seen] == ["msg_a", "msg_b"] and seen[0][1] == {"type": "paid", "amount": 5}


async def test_a_failing_handler_records_nothing_so_the_senders_retry_runs_it_again(client: AsyncClient, outbox, net: FakeNet, seen) -> None:  # noqa: ANN001, F811
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    url = await _in_url(client, admin)
    handlers.clear_handlers()
    attempts: list[int] = []

    @handlers.inbound(INBOUND)
    async def flaky(ctx: handlers.InboundContext) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("boom whsec_leak")

    headers = _signed(BODY, SECRET, "msg_f")
    failed = await client.post(url, content=BODY, headers=headers)
    assert failed.status_code == 500 and "boom" not in failed.text and "whsec_leak" not in failed.text
    assert (await client.post(url, content=BODY, headers=headers)).json() == {"status": "accepted"}
    assert len(attempts) == 2


async def test_a_non_ascii_content_length_is_a_client_error_not_a_crash(client: AsyncClient, outbox, net: FakeNet, seen) -> None:  # noqa: ANN001, F811
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    url = await _in_url(client, admin)
    for value in ("\u00b2", "\u00b9", "-1", "1e3", " "):
        raw = [(k.encode(), v.encode("latin-1")) for k, v in {**_signed(BODY, SECRET), "content-length": value}.items()]
        response = await client.post(url, content=BODY, headers=raw)
        assert response.status_code in (400, 401), value
    assert seen == []


async def test_incoming_bodies_over_the_limit_are_refused(client: AsyncClient, outbox, net: FakeNet, seen) -> None:  # noqa: ANN001, F811
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    url = await _in_url(client, admin)
    big = b"x" * (definitions.INBOUND[INBOUND]["max_body_bytes"] + 1)
    assert (await client.post(url, content=big, headers=_signed(big, SECRET))).status_code == 413
    assert seen == []


async def test_incoming_secret_rotation_accepts_both_during_the_overlap(client: AsyncClient, outbox, net: FakeNet, seen) -> None:  # noqa: ANN001, F811
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    url = await _in_url(client, admin)
    newer = "whsec_" + "bmV3ZXItc2VjcmV0LW5ld2VyLXNlY3JldC0xMTExMTExMQ=="
    rotated = await client.put(f"/webhooks/inbound/{INBOUND}/secret", json={"value": newer}, headers=admin)
    assert rotated.json()["rotating"] is True and rotated.json()["secret_version"] == 2 and newer not in rotated.text
    assert (await client.post(url, content=BODY, headers=_signed(BODY, SECRET, "r1"))).status_code == 200
    assert (await client.post(url, content=BODY, headers=_signed(BODY, newer, "r2"))).status_code == 200
    await _sql("UPDATE wh_endpoints SET previous_expires_at = now() - interval '1 minute'")
    assert (await client.post(url, content=BODY, headers=_signed(BODY, SECRET, "r3"))).status_code == 401
    assert (await client.post(url, content=BODY, headers=_signed(BODY, newer, "r4"))).status_code == 200
    listed = (await client.get("/webhooks/inbound", headers=admin)).json()
    assert listed == [{"name": INBOUND, "has_secret": True, "secret_version": 2, "rotating": False, "updated_at": listed[0]["updated_at"]}]
