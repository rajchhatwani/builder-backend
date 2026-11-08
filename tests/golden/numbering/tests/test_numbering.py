"""Numbered fields (generated): the platform draws each number from its sequence; callers cannot set it."""

import asyncio
import re

from httpx import AsyncClient

from tests import _factories


def _count(value: object) -> int:
    match = re.search(r"(\d+)$", str(value))
    assert match is not None, value
    return int(match.group(1))


async def test_orders_numbers_come_from_the_sequence(authed_client: AsyncClient) -> None:
    client = authed_client
    made = await asyncio.gather(*(_factories.make_orders(client) for _ in range(6)))
    last: dict[str, int] = {}
    # 6 parallel creates: 6 distinct numbers, one after another (gapless)
    numbers = sorted(_count(row['invoice_no']) for row in made)
    assert numbers == list(range(numbers[0], numbers[0] + 6)), numbers
    last['invoice_no'] = numbers[-1]
    # 6 parallel creates: 6 distinct numbers, one after another (gapless)
    numbers = sorted(_count(row['order_no']) for row in made)
    assert numbers == list(range(numbers[0], numbers[0] + 6)), numbers
    last['order_no'] = numbers[-1]
    # 6 parallel creates: 6 distinct numbers, one after another (gapless)
    numbers = sorted(_count(row['ticket_no']) for row in made)
    assert numbers == list(range(numbers[0], numbers[0] + 6)), numbers
    last['ticket_no'] = numbers[-1]
    # a number chosen by the caller is ignored
    forged = await _factories.make_orders(
        client,
        **{
            'invoice_no': 'FORGED-1',
            'order_no': 'FORGED-1',
            'ticket_no': 999999,
        },
    )
    for name, number in last.items():
        assert str(forged[name]) not in ("FORGED-1", "999999")
        assert _count(forged[name]) == number + 1
    # and it cannot be changed afterwards
    before = (await client.get(f"/orders/{forged['id']}")).json()
    await client.patch(
        f"/orders/{forged['id']}",
        json={
            'invoice_no': 'HACKED-1',
            'order_no': 'HACKED-1',
            'ticket_no': 777777,
        },
    )
    after = (await client.get(f"/orders/{forged['id']}")).json()
    for name in last:
        assert after[name] == before[name]
