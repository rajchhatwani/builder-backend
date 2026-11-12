"""Money pack settings (generated from the spec: change them in the builder). Plain data, integers only."""

CURRENCIES: tuple[str, ...] = ("EUR", "JPY", "KWD", "USD")
ROUNDING = "half_even"  # banker's rounding: the only mode
# tax rate name -> basis points (1 bp = 0.01 %); static, no network
TAX_RATES_BP: dict[str, int] = {'reduced': 500, 'standard': 2000, 'zero': 0}
