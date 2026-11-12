"""Ledger settings (generated from the spec: change them in the builder). Plain data."""

# who may read / post; an empty tuple means any signed-in user
READ_ROLES: tuple[str, ...] = ('admin', 'member',)
POST_ROLES: tuple[str, ...] = ('admin', 'member',)
MAX_AMOUNT_MINOR = 9007199254740991  # largest |amount| of one entry line, in minor units
MAX_ENTRIES = 100  # lines per transaction
MULTI_TENANT = True
BALANCE_ROW_CAP = 1000  # GET /ledger/balances returns at most this many accounts (ordered by code)
