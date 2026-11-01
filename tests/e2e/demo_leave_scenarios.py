"""Owner demo, HR leave request (generated project `demo_leave`). Copied into the project's tests/ folder by
tests/e2e/test_cycle1_demo.py and run against a real Postgres. Every `say()` line goes to the transcript.

What the story shows: an employee asks for leave; the rules route it to the manager (up to 5 days) or to HR
(more), or decline it at once when the balance is too small; only the matching reviewer decides; the
`check_request` hook asks for a reason on long leave; dates and days keep a change history; request numbers come from
a gapless sequence that restarts every year; settings and the leave-type list are HR-editable.
"""

import asyncio
import datetime as dt
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.db import session_factory
from app.main import app
from app.runtime_config import sequences

TRANSCRIPT = Path(__file__).resolve().parent.parent / "demo_transcript.log"


def say(line: str) -> None:
    with TRANSCRIPT.open("a", encoding="utf-8") as out:
        out.write(line + "\n")


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "employee": await sign_in(http, "emp@example.com", roles=["employee"], n=0),
        "manager": await sign_in(http, "mgr@example.com", roles=["manager"], n=1),
        "hr": await sign_in(http, "hr@example.com", roles=["hr"], n=2),
    }


async def next_number() -> str:
    async with session_factory() as session:
        number = await sequences.next_number(session, "request_no")
        await session.commit()
        return number


async def employee(http: AsyncClient, who: dict[str, str], balance: int = 10) -> str:
    response = await http.post(
        "/employees",
        json={"name": "Sam Rivera", "email": "sam@example.com", "department": "Finance", "leave_balance": balance},
        headers=who,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def span(days: int) -> dict[str, str]:
    return {"start_date": "2026-03-02", "end_date": (dt.date(2026, 3, 2) + dt.timedelta(days=days - 1)).isoformat()}


async def request(http, who, emp, days, balance, **extra):  # noqa: ANN001, ANN201
    body = {
        "request_no": await next_number(), "employee_id": emp, "days": days, "balance": balance,
        "reason": "Holiday", **span(days), **extra,
    }
    return await http.post("/leave_requests", json=body, headers=who)


async def filed(http, who, emp, days, balance) -> dict:  # noqa: ANN001
    response = await request(http, who, emp, days, balance)
    assert response.status_code == 201, response.text
    body = response.json()
    say(f"  employee asks for {days} day(s), balance {balance}: {body['request_no']} -> {body['state']}")
    return body


async def move(http, who, item, name):  # noqa: ANN001, ANN201
    return await http.post(f"/leave_requests/{item}/transitions/{name}", headers=who)


async def test_requests_are_routed_by_the_rules(http, people) -> None:  # noqa: ANN001
    say("Scenario 1: routing by days and balance")
    emp = await employee(http, people["hr"])
    short = await filed(http, people["employee"], emp, 3, 10)
    long_ = await filed(http, people["employee"], emp, 8, 10)
    over = await filed(http, people["employee"], emp, 12, 10)
    assert (short["state"], long_["state"], over["state"]) == ("manager_review", "hr_review", "declined")
    log = (await http.get(f"/leave_requests/{over['id']}/state-history", headers=people["hr"])).json()
    assert [h["to_state"] for h in log] == ["requested", "declined"] and log[1]["automatic"] is True
    say("  the 12-day request was declined automatically (balance rule); state log: "
        + str([(h["to_state"], "automatic" if h["automatic"] else "by a person") for h in log]))


async def test_only_the_matching_reviewer_decides(http, people) -> None:  # noqa: ANN001
    say("Scenario 2: manager or HR decides, never both")
    emp = await employee(http, people["hr"])
    short = await filed(http, people["employee"], emp, 3, 10)
    long_ = await filed(http, people["employee"], emp, 8, 10)
    assert (await move(http, people["hr"], short["id"], "manager_approve")).status_code == 403
    say("  HR tries the manager's transition on the 3-day request -> 403")
    assert (await move(http, people["manager"], long_["id"], "manager_approve")).status_code == 409
    assert (await move(http, people["manager"], long_["id"], "hr_approve")).status_code == 403
    say("  manager tries the 8-day request -> 409 (wrong state) / 403 (HR transition)")
    approved = await move(http, people["manager"], short["id"], "manager_approve")
    assert approved.json()["state"] == "approved"
    say("  manager approves the 3-day request -> approved")
    declined = await move(http, people["hr"], long_["id"], "hr_decline")
    assert declined.json()["state"] == "declined"
    say("  HR declines the 8-day request -> declined")
    assert (await move(http, people["hr"], short["id"], "hr_decline")).status_code == 409
    assert (await move(http, people["employee"], short["id"], "cancel")).status_code == 409
    say("  a decided request is final: further moves -> 409")


async def test_the_request_hook_asks_for_a_reason_on_long_leave(http, people) -> None:  # noqa: ANN001
    say("Scenario 3: the check_request hook (validate, fail closed)")
    emp = await employee(http, people["hr"])
    long_no_reason = await request(http, people["employee"], emp, 8, 20, reason=None)
    assert long_no_reason.status_code == 422, long_no_reason.text
    say(f"  8 days without a reason -> {long_no_reason.status_code} {long_no_reason.json().get('code')}: "
        f"{long_no_reason.json().get('message')}")
    blank = await request(http, people["employee"], emp, 8, 20, reason="   ")
    assert blank.status_code == 422
    say("  8 days with a blank reason -> 422 as well")
    short = await request(http, people["employee"], emp, 2, 20, reason=None)
    assert short.status_code == 201, short.text
    say("  2 days without a reason -> 201 (the hook only asks for long leave)")
    too_long = await request(http, people["employee"], emp, 90, 100)
    assert too_long.status_code == 422
    say("  90 days -> 422 (field limit of 60 days, checked before the hook)")


async def test_dates_and_days_keep_a_history(http, people) -> None:  # noqa: ANN001
    say("Scenario 4: change history")
    emp = await employee(http, people["hr"])
    item = await filed(http, people["employee"], emp, 2, 10)
    patched = await http.patch(f"/leave_requests/{item['id']}", json={"end_date": "2026-03-04", "days": 3},
                               headers=people["hr"])
    assert patched.status_code == 200, patched.text
    assert (await http.get(f"/leave_requests/{item['id']}/history", headers=people["employee"])).status_code == 403
    rows = (await http.get(f"/leave_requests/{item['id']}/history", headers=people["manager"])).json()
    updates = sorted((r["field"], r["old_value"], r["new_value"]) for r in rows if r["op"] == "update")
    say(f"  HR extends the leave; manager reads the history: {updates}")
    assert [u[0] for u in updates] == ["days", "end_date"]
    say("  employee cannot read the history (403)")


async def test_request_numbers_are_gapless_and_yearly(http, people) -> None:  # noqa: ANN001
    say("Scenario 5: gapless request numbers")
    numbers = await asyncio.gather(*(next_number() for _ in range(10)))
    year = dt.datetime.now(dt.UTC).year
    assert sorted(numbers) == [f"LR-{year}-{n:04d}" for n in range(1, 11)]
    say(f"  10 parallel draws -> {min(numbers)} .. {max(numbers)}, no gap, no duplicate")


async def test_settings_and_the_leave_type_list(http, people) -> None:  # noqa: ANN001
    say("Scenario 6: HR-editable settings and list")
    put = lambda key, value, who: http.put(f"/config/settings/{key}", json={"value": value}, headers=who)  # noqa: E731
    assert (await put("max_days_without_hr", 7, people["manager"])).status_code == 403
    assert (await put("max_days_without_hr", 7, people["hr"])).status_code == 200
    assert (await put("max_days_without_hr", 0, people["hr"])).status_code == 422
    shown = {s["key"]: s["value"] for s in (await http.get("/config/settings", headers=people["hr"])).json()}
    say(f"  max_days_without_hr: manager 403, HR 200, 0 -> 422; HR now sees {shown}")
    assert shown["max_days_without_hr"] == 7
    items = (await http.get("/config/lists/leave_type", headers=people["employee"])).json()["items"]
    say(f"  leave types for an employee: {[i['value'] for i in items]}")
