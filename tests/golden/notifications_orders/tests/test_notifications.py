"""Notification checks (generated): templates escape, hostile input is inert, opt-outs are honoured, the
delivery log keeps no body or secret, retries back off, tenants are separate. Nothing is really sent: the
provider emulator is the only adapter."""

import datetime as dt
import importlib
import json
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from structlog.testing import capture_logs

from app.auth.models import AuthUser
from app.db import session_factory
from app.events import bus
from app.notifications import definitions, dispatcher, render, service
from app.notifications.models import NotificationDelivery
from app.providers import breaker
from tests._auth_support import outbox, sign_in, sign_in_plain  # noqa: F401
from tests._providers_support import emulator, vault_env  # noqa: F401

ADMIN = 'admin'
TENANT = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-4222-8222-222222222222")
CANARY = "CANARY-5d2e8a41c7b3-must-not-be-stored"
OPT = json.loads('["order_shipped", "email", ["order", "tracking"]]')  # (type, channel, variables) of an optional type, or None
TRANS = json.loads('["security_alert", "email", ["detail"]]')  # (type, channel, variables) of a transactional type, or None
EVENT = json.loads('["welcome", "customer.created"]')  # (type, event name) of a type with on_event, or None
ADDRESS = {"email": "ann@example.com", "sms": "+15550100", "push": "device-token-1"}


needs_opt = pytest.mark.skipif(OPT is None, reason="the spec has no optional type with variables")
needs_trans = pytest.mark.skipif(TRANS is None, reason="the spec has no transactional type")


def _recipient(key: str, channel: str) -> service.Recipient:
    return service.Recipient(
        key=key, email=ADDRESS["email"], phone=ADDRESS["sms"], device=ADDRESS["push"]
    )


def _values(variables: list[str], value: str = "v") -> dict[str, str]:
    return {name: value for name in variables}


async def _rows(**where: object) -> list[NotificationDelivery]:
    async with session_factory() as session:
        stmt = sa.select(NotificationDelivery).order_by(NotificationDelivery.created_at, NotificationDelivery.id)
        for column, value in where.items():
            stmt = stmt.where(getattr(NotificationDelivery, column) == value)
        return list((await session.execute(stmt)).scalars())


async def _send(type_name: str, channel: str, key: str, values: dict[str, str], **kw: object) -> list[uuid.UUID]:
    async with session_factory() as session:
        ids = await service.notify(
            session, type_name, _recipient(key, channel), values, tenant_id=TENANT, channels=(channel,), **kw  # type: ignore[arg-type]
        )
        await session.commit()
    return ids


async def _dispatch(now: dt.datetime | None = None) -> list[str]:
    outcomes: list[str] = []
    while (job := await dispatcher.claim(session_factory, now=now)) is not None:
        outcomes.append(await dispatcher.process(session_factory, job))
    return outcomes


# --- rendering: escaping and hostile input -----------------------------------------------------------


@pytest.mark.parametrize("payload", ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", '"><svg/onload=x>'])
def test_html_email_escapes_every_value(payload: str) -> None:
    _, body = render.render("email", "S", "<p>{{ v }}</p>", True, {"v": payload})
    assert payload not in body and "<script" not in body and "<img" not in body and "<svg" not in body
    assert body.startswith("<p>") and body.endswith("</p>")


@pytest.mark.parametrize("payload", ["{{ 7*7 }}", "{{ v }}", "{% if 1 %}x{% endif %}", "{{ ''.__class__ }}", "${7*7}", "#{7*7}"])
def test_a_value_is_never_evaluated_or_expanded_again(payload: str) -> None:
    subject, body = render.render("email", "S {{ v }}", "B {{ v }} / {{ w }}", False, {"v": payload, "w": "ok"})
    assert subject == f"S {payload}" and body == f"B {payload} / ok"
    assert "49" not in body


@pytest.mark.parametrize(
    "template",
    ["{{ 7*7 }}", "{{ a.b }}", "{{ a|upper }}", "{% for x in y %}", "{{ a }", "}} {{ a", "{# c #}", "{{ __class__ }}", "{{ x }}"],
)
def test_a_template_may_only_use_declared_placeholders(template: str) -> None:
    with pytest.raises(render.RenderError) as raised:
        render.check_template(template, {"a"})
    assert "49" not in str(raised.value)


@pytest.mark.parametrize(
    "subject",
    ["Hi\r\nBcc: evil@example.com", "Hi\nSubject: other", "Hi\rX", "Hi\x00there", "Hi there", "a‮b"],
)
def test_a_subject_is_one_line_whatever_the_value(subject: str) -> None:
    out, _ = render.render("email", "Order {{ v }}", "body", False, {"v": subject})
    assert not any(ch in out for ch in "\r\n\x00 ‮") and out.startswith("Order ")
    title, _ = render.render("push", "{{ v }}", "body", False, {"v": subject})
    assert "\n" not in title and "\r" not in title


@pytest.mark.parametrize(
    "value",
    ["javascript:alert(1)", "JaVaScRiPt:alert(1)", " java\tscript:alert(1)", "java\nscript:alert(1)", "data:text/html,<b>x</b>", "vbscript:msgbox(1)", "\x01javascript:x"],
)
@pytest.mark.parametrize("template", ['<a href="{{ v }}">x</a>', "<a href='{{ v }}'>x</a>", "<a href={{ v }}>x</a>", '<img src="{{ v }}">', '<a class="c" HREF = "{{ v }}">x</a>'])
def test_a_dangerous_url_scheme_is_neutralised_in_an_html_attribute(template: str, value: str) -> None:
    _, body = render.render("email", "S", template, True, {"v": value})
    assert "javascript" not in body.lower().replace("\t", "").replace("\n", "") and "vbscript" not in body.lower() and "data:" not in body.lower()
    assert "#" in body


@pytest.mark.parametrize("value", ["https://example.com/a?b=1&c=2", "http://example.com", "mailto:a@example.com", "tel:+15550100", "/relative/path", "#top", "example.com/x"])
def test_ordinary_links_are_kept_and_escaped(value: str) -> None:
    _, body = render.render("email", "S", '<a href="{{ v }}">x</a>', True, {"v": value})
    assert body == '<a href="' + value.replace("&", "&amp;") + '">x</a>'


def test_text_in_a_body_is_not_treated_as_a_url() -> None:
    _, body = render.render("email", "S", "<p>{{ v }}</p>", True, {"v": "javascript: is a language"})
    assert body == "<p>javascript: is a language</p>"


def test_a_nul_character_is_refused_everywhere() -> None:
    with pytest.raises(render.RenderError):
        render.clean_values({"v": "a\x00b"}, {"v"})
    for channel in ("email", "sms", "push"):
        with pytest.raises(render.RenderError):
            service.validate_template(*_any_type(channel), "S" if channel != "sms" else "", "body \x00 here", False)


def _any_type(channel: str) -> tuple[str, str]:
    for name, spec in definitions.TYPES.items():
        if channel in spec["channels"]:
            return name, channel
    pytest.skip("no type uses this channel")


def test_text_channels_drop_control_characters() -> None:
    _, body = render.render("sms", "", "x {{ v }}", False, {"v": "a\x00b\x1bc\x7fd\ne"})
    assert body == "x abcd\ne"


@pytest.mark.parametrize(
    ("channel", "address", "good"),
    [
        ("email", "ann@example.com", True), ("email", "a.b+c@sub.example.org", True),
        ("email", "ann@example.com\r\nBcc: x@y.com", False), ("email", "ann@example.com,bob@example.com", False),
        ("email", "ann@example.com;bob@example.com", False), ("email", "Ann <ann@example.com>", False),
        ("email", "ann@example.com ", False), ("email", "ann@localhost", False), ("email", "", False),
        ("email", "a" * 70 + "@example.com", False),
        ("sms", "+15550100", True), ("sms", "15550100", False), ("sms", "+1555;rm -rf", False), ("sms", "+1\n555", False),
        ("push", "device-token-1", True), ("push", "dev", False), ("push", "tok en-12345", False), ("push", "tok\nen-12345", False),
        ("fax", "x", False),
    ],
)
def test_recipient_addresses_are_checked_strictly(channel: str, address: str, good: bool) -> None:
    assert render.valid_address(channel, address) is good
    assert (render.mask(channel, address) != "") is good
    if good:
        assert address not in render.mask(channel, address)


def test_values_must_be_plain_and_small() -> None:
    names = {"v"}
    with pytest.raises(render.RenderError):
        render.clean_values({"v": {"a": 1}}, names)
    with pytest.raises(render.RenderError):
        render.clean_values({"v": "x" * (render.MAX_VALUE + 1)}, names)
    with pytest.raises(render.RenderError):
        render.clean_values({"other": "x"}, names)
    assert render.clean_values({"v": None}, names) == {"v": ""}


# --- sending, the log, preferences ---------------------------------------------------------------------


@needs_opt
async def test_a_message_is_sent_through_the_emulator_and_logged_without_its_content(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    ids = await _send(type_name, channel, "user-1", _values(variables, CANARY))
    assert len(ids) == 1 and (await _rows())[0].status == "queued"
    assert (await _rows())[0].address == ADDRESS[channel] and CANARY in json.dumps((await _rows())[0].variables)
    with capture_logs() as logs:
        assert await _dispatch() == ["sent"]
    assert CANARY not in json.dumps(logs, default=str)
    sent = emulator.sent[channel]
    assert len(sent) == 1 and sent[0].message_id.startswith("emu-")
    row = (await _rows())[0]
    assert row.status == "sent" and row.attempts == 1 and row.provider == "emulator"
    assert row.provider_message_id == sent[0].message_id and row.error_code is None
    assert row.address is None and row.variables is None  # erased once sent
    assert row.recipient_hint and ADDRESS[channel] not in row.recipient_hint
    text = json.dumps({c.name: getattr(row, c.name) for c in NotificationDelivery.__table__.columns}, default=str)
    assert CANARY not in text and sent[0].request.get("body", "") not in text


@needs_opt
async def test_an_opt_out_is_honoured_and_logged(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    async with session_factory() as session:
        await service.set_preference(session, TENANT, "user-2", type_name, channel, False)
        await session.commit()
    await _send(type_name, channel, "user-2", _values(variables))
    row = (await _rows())[0]
    assert row.status == "suppressed" and row.reason == "opt_out" and row.address is None and row.variables is None
    assert await _dispatch() == [] and not emulator.sent[channel]
    await _send(type_name, channel, "user-3", _values(variables))  # somebody else is not affected
    assert await _dispatch() == ["sent"] and len(emulator.sent[channel]) == 1


@needs_opt
async def test_an_opt_out_made_after_queueing_stops_the_send(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    await _send(type_name, channel, "user-4", _values(variables))
    async with session_factory() as session:
        await service.set_preference(session, TENANT, "user-4", type_name, channel, False)
        await session.commit()
    assert await _dispatch() == ["suppressed"] and not emulator.sent[channel]
    row = (await _rows())[0]
    assert row.status == "suppressed" and row.reason == "opt_out" and row.address is None


@needs_opt
async def test_opting_back_in_and_one_channel_only(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    async with session_factory() as session:
        await service.set_preference(session, TENANT, "user-5", type_name, channel, False)
        await service.set_preference(session, TENANT, "user-5", type_name, channel, True)
        assert await service.preference(session, TENANT, "user-5", type_name, channel)
        await session.commit()
    await _send(type_name, channel, "user-5", _values(variables))
    assert await _dispatch() == ["sent"]


@needs_trans
async def test_a_transactional_message_cannot_be_switched_off(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = TRANS
    async with session_factory() as session:
        with pytest.raises(service.UnknownNotification):
            await service.set_preference(session, TENANT, "user-6", type_name, channel, False)
        await session.rollback()
    await _send(type_name, channel, "user-6", _values(variables))
    assert await _dispatch() == ["sent"] and len(emulator.sent[channel]) == 1


@needs_opt
async def test_a_bad_address_is_logged_and_never_sent(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    bad = {"email": "ann@example.com\r\nBcc: evil@example.com", "sms": "+1555;drop", "push": "x y"}[channel]
    recipient = service.Recipient(key="user-7", email=bad, phone=bad, device=bad)
    async with session_factory() as session:
        await service.notify(session, type_name, recipient, _values(variables), tenant_id=TENANT, channels=(channel,))
        await session.commit()
    row = (await _rows())[0]
    assert row.status == "suppressed" and row.reason == "invalid_address" and row.address is None
    assert row.recipient_hint == "" and await _dispatch() == [] and not emulator.sent[channel]


@needs_opt
async def test_unknown_types_channels_and_variables_are_refused(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    async with session_factory() as session:
        with pytest.raises(service.UnknownNotification):
            await service.notify(session, "nope", _recipient("u", channel), {}, tenant_id=TENANT)
        with pytest.raises(service.UnknownNotification):
            await service.notify(session, type_name, _recipient("u", channel), {}, tenant_id=TENANT, channels=("fax",))
        with pytest.raises(render.RenderError):
            await service.notify(session, type_name, _recipient("u", channel), {"nope": "x"}, tenant_id=TENANT)
        await session.rollback()
    assert await _rows() == []


@needs_opt
async def test_a_dedupe_key_queues_a_message_once(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    first = await _send(type_name, channel, "user-8", _values(variables), dedupe_key="order-1")
    again = await _send(type_name, channel, "user-8", _values(variables), dedupe_key="order-1")
    assert len(first) == 1 and again == [] and len(await _rows()) == 1


# --- retries ---------------------------------------------------------------------------------------------


@needs_opt
async def test_a_temporary_failure_is_retried_with_backoff_then_succeeds(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    await _send(type_name, channel, "user-9", _values(variables))
    emulator.inject(channel, "retryable", times=50)
    assert await _dispatch() == ["retry"]
    row = (await _rows())[0]
    assert row.status == "queued" and row.attempts == 1 and row.error_code in ("retryable", "circuit_open")
    assert row.address is not None  # still needed
    assert row.next_attempt_at > dt.datetime.now(dt.UTC)
    assert await _dispatch() == []  # not due yet
    emulator.failures[channel].clear()
    breaker.reset_all()
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=definitions.BACKOFF_SECONDS * 4 + 5)
    assert await _dispatch(later) == ["sent"]
    row = (await _rows())[0]
    assert row.status == "sent" and row.attempts == 2 and row.address is None


@needs_opt
async def test_a_permanent_failure_fails_at_once_and_keeps_only_the_code(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    await _send(type_name, channel, "user-10", _values(variables, CANARY))
    emulator.inject(channel, "permanent")
    assert await _dispatch() == ["failed"]
    row = (await _rows())[0]
    assert row.status == "failed" and row.error_code == "permanent" and row.attempts == 1
    assert row.address is None and row.variables is None and CANARY not in json.dumps(row.error_code)


@needs_opt
async def test_retries_stop_at_the_cap(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    await _send(type_name, channel, "user-11", _values(variables))
    far = dt.datetime.now(dt.UTC)
    outcomes: list[str] = []
    for _ in range(definitions.MAX_ATTEMPTS + 2):
        emulator.inject(channel, "retryable", times=50)
        breaker.reset_all()
        far += dt.timedelta(hours=2)
        outcomes += await _dispatch(far)
    assert outcomes == ["retry"] * (definitions.MAX_ATTEMPTS - 1) + ["failed"]
    row = (await _rows())[0]
    assert row.status == "failed" and row.attempts == definitions.MAX_ATTEMPTS and row.error_code in ("retryable", "circuit_open")


@needs_opt
async def test_a_lost_lease_is_taken_over_once(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    await _send(type_name, channel, "user-12", _values(variables))
    first = await dispatcher.claim(session_factory)
    assert first is not None and await dispatcher.claim(session_factory) is None  # leased: nobody else gets it
    later = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    second = await dispatcher.claim(session_factory, now=later)
    assert second is not None and second.id == first.id and second.attempt == 2
    assert await dispatcher.process(session_factory, first) == "lost"  # the old holder cannot overwrite
    assert await dispatcher.process(session_factory, second) == "sent"
    assert len(emulator.sent[channel]) <= 2 and (await _rows())[0].status == "sent"


@needs_opt
async def test_a_send_that_keeps_crashing_is_abandoned_at_the_cap(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    await _send(type_name, channel, "user-14", _values(variables, CANARY))
    later = dt.datetime.now(dt.UTC)
    for _ in range(definitions.MAX_ATTEMPTS):  # a worker that dies mid-send: claimed, never finished
        later += dt.timedelta(hours=1)
        assert await dispatcher.claim(session_factory, now=later) is not None
    later += dt.timedelta(hours=1)
    assert await dispatcher.claim(session_factory, now=later) is None  # no further send is made
    row = (await _rows())[0]
    assert row.status == "failed" and row.error_code == "abandoned" and row.attempts == definitions.MAX_ATTEMPTS
    assert row.address is None and row.variables is None and not emulator.sent[channel]


@needs_opt
async def test_a_nul_in_a_recipient_key_or_dedupe_key_is_refused(emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    async with session_factory() as session:
        with pytest.raises(ValueError):
            await service.notify(session, type_name, _recipient("a\x00b", channel), _values(variables), tenant_id=TENANT)
        with pytest.raises(ValueError):
            await service.notify(session, type_name, _recipient("ok", channel), _values(variables), tenant_id=TENANT, dedupe_key="a\x00b")
        await session.rollback()


# --- hostile templates and values end to end ---------------------------------------------------------


@needs_opt
@pytest.mark.parametrize("payload", ["<script>alert(1)</script>", "{{ 7*7 }}", "x\r\nBcc: evil@example.com"])
async def test_a_hostile_value_goes_out_inert(emulator, payload: str) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    first = variables[0]
    html = channel == "email"
    async with session_factory() as session:
        await service.save_template(
            session, TENANT, type_name, channel, "" if channel == "sms" else "S {{ " + first + " }}",
            "B {{ " + first + " }}", html, None,
        )
        await session.commit()
    await _send(type_name, channel, "user-13", {first: payload})
    assert await _dispatch() == ["sent"]
    request = emulator.sent[channel][0].request
    body = request["body"]
    assert "49" not in body
    if html:
        assert "<script" not in body and "\r" not in request["subject"] and "\n" not in request["subject"]
        if "<" in payload:
            assert "&lt;script&gt;" in body
    elif channel == "push":
        assert "\n" not in request["title"] and "\r" not in request["title"]


# --- event triggers ------------------------------------------------------------------------------------------


@pytest.mark.skipif(EVENT is None, reason="no notification type is triggered by an event")
async def test_an_event_queues_the_notification_once(emulator) -> None:  # noqa: ANN001, F811
    type_name, event_name = EVENT
    spec = definitions.TYPES[type_name]
    importlib.import_module("app.notifications.triggers")
    data: dict[str, object] = {name: "v" for name in spec["variables"]}
    data[spec["recipient_key_field"]] = "event-user-1"
    for channel, field in spec["address_fields"].items():
        data[field] = ADDRESS[channel]
    event = bus.Event(
        id=uuid.uuid4(), type=event_name, aggregate_type="Thing", aggregate_id=uuid.uuid4(), seq=1,
        tenant_id=TENANT, occurred_at=dt.datetime.now(dt.UTC), payload={"data": data},
    )
    handlers = [h for _, h in bus.subscribers_for(event_name) if h.__module__.endswith("triggers")]
    assert handlers, "the trigger is registered for the event"
    for _ in range(2):  # delivered twice (at least once): one set of rows
        for handler in handlers:
            await handler(event)
    rows = await _rows(type=type_name)
    assert sorted(r.channel for r in rows) == sorted(spec["channels"])
    assert all(r.source_event_id == event.id and r.recipient_key == "event-user-1" for r in rows)
    await _dispatch()
    assert all(r.status == "sent" for r in await _rows(type=type_name))


# --- the API -------------------------------------------------------------------------------------------------


@needs_opt
async def test_templates_can_be_listed_previewed_edited_and_reset(client: AsyncClient, outbox, emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    admin = await sign_in(client, "tpl-admin@example.com", roles=[ADMIN])
    listing = await client.get("/notifications/templates", headers=admin)
    assert listing.status_code == 200, listing.text
    mine = [t for t in listing.json() if t["type"] == type_name and t["channel"] == channel][0]
    assert mine["source"] == "default" and sorted(mine["variables"]) == sorted(variables)
    url = f"/notifications/templates/{type_name}/{channel}"
    first = variables[0]
    subject = "" if channel == "sms" else "Hi {{ " + first + " }}"
    draft = {"subject": subject, "body": "Dear {{ " + first + " }}", "html": channel == "email"}
    preview = await client.post(url + "/preview", json={**draft, "variables": {first: "<b>Ann</b>"}}, headers=admin)
    assert preview.status_code == 200, preview.text
    if channel == "email":
        assert "&lt;b&gt;Ann&lt;/b&gt;" in preview.json()["body"] and "<b>" not in preview.json()["body"]
    sample = await client.post(url + "/preview", json=draft, headers=admin)
    assert f"[{first}]" in sample.json()["body"]
    assert (await client.get("/notifications/deliveries", headers=admin)).json() == []  # a preview sends nothing
    assert not emulator.sent[channel]
    for bad in ("{{ 7*7 }}", "{{ nope }}", "{% if 1 %}", "{{ " + first + ".x }}"):
        r = await client.put(url, json={**draft, "body": bad}, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == "invalid_template", r.text
        assert "49" not in r.text
        assert (await client.post(url + "/preview", json={**draft, "body": bad}, headers=admin)).status_code == 422
    saved = await client.put(url, json=draft, headers=admin)
    assert saved.status_code == 200 and saved.json()["source"] == "custom"
    after = [t for t in (await client.get("/notifications/templates", headers=admin)).json() if t["type"] == type_name and t["channel"] == channel][0]
    assert after["body"] == draft["body"] and after["source"] == "custom"
    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.delete(url, headers=admin)).status_code == 404
    assert (await client.put("/notifications/templates/nope/email", json=draft, headers=admin)).status_code == 404
    assert (await client.put(url.replace(channel, "fax"), json=draft, headers=admin)).status_code == 422


async def test_templates_and_the_log_need_the_admin_role(client: AsyncClient, outbox) -> None:  # noqa: ANN001, F811
    plain = await sign_in_plain(client, "tpl-plain@example.com")
    calls = [
        ("GET", "/notifications/templates"), ("GET", "/notifications/deliveries"),
        ("PUT", "/notifications/templates/x/email"), ("DELETE", "/notifications/templates/x/email"),
        ("POST", "/notifications/templates/x/email/preview"),
    ]
    for method, path in calls:
        body = {"body": "x"} if method in ("PUT", "POST") else None
        assert (await client.request(method, path, json=body, headers=plain)).status_code == 403, path
        assert (await client.request(method, path, json=body)).status_code in (401, 403), path
    assert (await client.get("/notifications/types", headers=plain)).status_code == 200
    assert (await client.get("/notifications/types")).status_code in (401, 403)


@needs_opt
async def test_a_user_manages_only_their_own_preferences(client: AsyncClient, outbox, emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    ann = await sign_in_plain(client, "pref-ann@example.com")
    bob = await sign_in_plain(client, "pref-bob@example.com")
    listing = await client.get("/notifications/preferences", headers=ann)
    assert listing.status_code == 200, listing.text
    row = [p for p in listing.json() if p["type"] == type_name and p["channel"] == channel][0]
    assert row["editable"] is True and row["category"] == "optional"
    off = await client.put(f"/notifications/preferences/{type_name}/{channel}", json={"enabled": False}, headers=ann)
    assert off.status_code == 200 and off.json()["enabled"] is False
    mine = [p for p in (await client.get("/notifications/preferences", headers=ann)).json() if p["type"] == type_name and p["channel"] == channel][0]
    his = [p for p in (await client.get("/notifications/preferences", headers=bob)).json() if p["type"] == type_name and p["channel"] == channel][0]
    assert mine["enabled"] is False and his["enabled"] is row["enabled"]
    async with session_factory() as session:
        ann_row = (await session.execute(sa.select(AuthUser).where(AuthUser.email == "pref-ann@example.com"))).scalar_one()
        bob_row = (await session.execute(sa.select(AuthUser).where(AuthUser.email == "pref-bob@example.com"))).scalar_one()
        await service.notify(session, type_name, _recipient(str(ann_row.id), channel), _values(variables), tenant_id=ann_row.tenant_id, channels=(channel,))
        await service.notify(session, type_name, _recipient(str(bob_row.id), channel), _values(variables), tenant_id=bob_row.tenant_id, channels=(channel,))
        await session.commit()
    by_user = {r.recipient_key: r for r in await _rows()}
    assert by_user[str(ann_row.id)].status == "suppressed" and by_user[str(ann_row.id)].reason == "opt_out"
    assert by_user[str(bob_row.id)].status == ("queued" if row["enabled"] else "suppressed")
    bad = await client.put("/notifications/preferences/nope/email", json={"enabled": False}, headers=ann)
    assert bad.status_code == 404
    assert (await client.put(f"/notifications/preferences/{type_name}/{channel}", json={"enabled": "maybe"}, headers=ann)).status_code == 422


@needs_trans
async def test_the_api_refuses_to_switch_off_a_transactional_type(client: AsyncClient, outbox) -> None:  # noqa: ANN001, F811
    type_name, channel, _ = TRANS
    ann = await sign_in_plain(client, "pref-trans@example.com")
    r = await client.put(f"/notifications/preferences/{type_name}/{channel}", json={"enabled": False}, headers=ann)
    assert r.status_code == 409 and r.json()["code"] == "not_optional"
    entry = [p for p in (await client.get("/notifications/preferences", headers=ann)).json() if p["type"] == type_name][0]
    assert entry["editable"] is False and entry["enabled"] is True


@needs_opt
async def test_the_delivery_log_is_listed_filtered_and_has_no_secrets(client: AsyncClient, outbox, emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    admin = await sign_in(client, "log-admin@example.com", roles=[ADMIN])
    async with session_factory() as session:
        me = (await session.execute(sa.select(AuthUser).where(AuthUser.email == "log-admin@example.com"))).scalar_one()
        await service.notify(session, type_name, _recipient("log-1", channel), _values(variables, CANARY), tenant_id=me.tenant_id, channels=(channel,))
        await service.notify(session, type_name, service.Recipient(key="log-2"), _values(variables), tenant_id=me.tenant_id, channels=(channel,))
        await session.commit()
    await _dispatch()
    everything = await client.get("/notifications/deliveries", headers=admin)
    assert everything.status_code == 200, everything.text
    assert CANARY not in everything.text and ADDRESS[channel] not in everything.text
    items = everything.json()
    assert len(items) == 2
    assert set(items[0]) == {
        "id", "type", "channel", "recipient_key", "recipient_hint", "status", "reason", "attempts", "provider",
        "provider_message_id", "error_code", "source_event_id", "created_at", "finished_at",
    }
    assert {i["status"] for i in items} == {"sent", "suppressed"}
    sent = (await client.get("/notifications/deliveries", params={"status": "sent"}, headers=admin)).json()
    assert [i["recipient_key"] for i in sent] == ["log-1"] and sent[0]["provider_message_id"].startswith("emu-")
    assert (await client.get("/notifications/deliveries", params={"status": "bogus"}, headers=admin)).status_code == 422
    assert (await client.get("/notifications/deliveries", params={"limit": 0}, headers=admin)).status_code == 422
    assert len((await client.get("/notifications/deliveries", params={"limit": 1}, headers=admin)).json()) == 1


@needs_opt
async def test_tenants_do_not_see_each_others_templates_preferences_or_log(client: AsyncClient, outbox, emulator) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    a = await sign_in(client, "iso-a@example.com", roles=[ADMIN])
    b = await sign_in(client, "iso-b@example.com", roles=[ADMIN])
    async with session_factory() as session:
        ua = (await session.execute(sa.select(AuthUser).where(AuthUser.email == "iso-a@example.com"))).scalar_one()
        ub = (await session.execute(sa.select(AuthUser).where(AuthUser.email == "iso-b@example.com"))).scalar_one()
        await service.notify(session, type_name, _recipient("iso-1", channel), _values(variables), tenant_id=ua.tenant_id, channels=(channel,))
        await session.commit()
    if ua.tenant_id == ub.tenant_id:
        pytest.skip("this project is not multi-tenant")
    first = variables[0]
    url = f"/notifications/templates/{type_name}/{channel}"
    draft = {"subject": "" if channel == "sms" else "A {{ " + first + " }}", "body": "A-only {{ " + first + " }}", "html": False}
    assert (await client.put(url, json=draft, headers=a)).status_code == 200
    seen_by_b = [t for t in (await client.get("/notifications/templates", headers=b)).json() if t["type"] == type_name and t["channel"] == channel][0]
    assert seen_by_b["source"] == "default" and "A-only" not in seen_by_b["body"]
    assert len((await client.get("/notifications/deliveries", headers=a)).json()) == 1
    assert (await client.get("/notifications/deliveries", headers=b)).json() == []
    assert (await client.delete(url, headers=b)).status_code == 404
    await client.put(f"/notifications/preferences/{type_name}/{channel}", json={"enabled": False}, headers=a)
    async with session_factory() as session:
        assert await service.preference(session, ua.tenant_id, str(ua.id), type_name, channel) is False
        # the same person key in the other tenant is a different person: the default applies
        default = bool(definitions.TYPES[type_name]["default_enabled"])
        assert await service.preference(session, ub.tenant_id, str(ua.id), type_name, channel) is default


@needs_opt
async def test_a_nul_in_a_template_or_filter_is_a_422_not_a_500(client: AsyncClient, outbox) -> None:  # noqa: ANN001, F811
    type_name, channel, variables = OPT
    admin = await sign_in(client, "nul-admin@example.com", roles=[ADMIN])
    url = f"/notifications/templates/{type_name}/{channel}"
    draft = {"subject": "" if channel == "sms" else "Hi", "body": "Dear \u0000 {{ " + variables[0] + " }}", "html": False}
    for call in (client.put(url, json=draft, headers=admin), client.post(url + "/preview", json=draft, headers=admin)):
        r = await call
        assert r.status_code == 422 and r.json()["code"] == "invalid_template", r.text
    r = await client.put(url, json={**draft, "body": "ok", "subject": "a\u0000b" if channel != "sms" else ""}, headers=admin)
    assert r.status_code == 422 if channel != "sms" else r.status_code == 200
    r = await client.get("/notifications/deliveries", params={"type": "a\u0000b"}, headers=admin)
    assert r.status_code == 422
