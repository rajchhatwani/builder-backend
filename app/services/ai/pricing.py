"""Price table and cost maths. Integer micro-USD, rounded up so the ledger never under-bills."""

from app.services.ai.base import Usage

# micro-USD per million tokens (= USD per million tokens x 1_000_000). Defaults are list prices
# at the time of writing; the real values come from config (BUILDER_AI_PRICE_TABLE).
DEFAULT_PRICES: dict[str, dict[str, int]] = {
    "claude-haiku-5-5": {
        "input": 1_000_000,
        "output": 5_000_000,
        "cache_read": 100_000,
        "cache_write": 1_250_000,
    },
    "claude-sonnet-5-5": {
        "input": 3_000_000,
        "output": 15_000_000,
        "cache_read": 300_000,
        "cache_write": 3_750_000,
    },
}


class UnknownModelPrice(Exception):
    pass


def price_table(overrides: dict[str, dict[str, int]] | None = None) -> dict[str, dict[str, int]]:
    table = {m: dict(p) for m, p in DEFAULT_PRICES.items()}
    for model, prices in (overrides or {}).items():
        table[model] = {**table.get(model, {}), **prices}
    return table


def cost_micro_usd(model: str, usage: Usage, table: dict[str, dict[str, int]]) -> int:
    prices = table.get(model)
    if prices is None:
        raise UnknownModelPrice(model)
    total = (
        max(usage.input_tokens, 0) * prices.get("input", 0)
        + max(usage.output_tokens, 0) * prices.get("output", 0)
        + max(usage.cache_read_tokens, 0) * prices.get("cache_read", 0)
        + max(usage.cache_write_tokens, 0) * prices.get("cache_write", 0)
    )
    return -(-total // 1_000_000)  # ceil
