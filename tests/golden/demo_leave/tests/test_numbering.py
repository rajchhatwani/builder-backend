"""Numbered fields (generated): the platform draws each number from its sequence; callers cannot set it."""

import asyncio
import re

from httpx import AsyncClient

from tests import _factories


def _count(value: object) -> int:
    match = re.search(r"(\d+)$", str(value))
    assert match is not None, value
    return int(match.group(1))


async def test_leave_requests_numbers_come_from_the_sequence(authed_client: AsyncClient) -> None:
    client = authed_client
    made = await asyncio.gather(*(_factories.make_leave_requests(client) for _ in range(6)))
    last: dict[str, int] = {}
    # 6 parallel creates: 6 distinct numbers, one after another (gapless)
    numbers = sorted(_count(row['request_no']) for row in made)
    assert numbers == list(range(numbers[0], numbers[0] + 6)), numbers
    last['request_no'] = numbers[-1]
    # a number chosen by the caller is ignored
    forged = await _factories.make_leave_requests(
        client,
        **{
            'request_no': 'FORGED-1',
        },
    )
    for name, number in last.items():
        assert str(forged[name]) not in ("FORGED-1", "999999")
        assert _count(forged[name]) == number + 1
    # and it cannot be changed afterwards
    before = (await client.get(f"/leave_requests/{forged['id']}")).json()
    await client.patch(
        f"/leave_requests/{forged['id']}",
        json={
            'request_no': 'HACKED-1',
        },
    )
    after = (await client.get(f"/leave_requests/{forged['id']}")).json()
    for name in last:
        assert after[name] == before[name]
