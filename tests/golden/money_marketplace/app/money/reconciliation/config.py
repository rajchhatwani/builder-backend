"""Reconciliation settings (generated from the spec: change them in the builder). Plain data, integers only."""

# who may read / run reconciliations; an empty tuple means any signed-in user
READ_ROLES: tuple[str, ...] = ('admin', 'member',)
RUN_ROLES: tuple[str, ...] = ('admin',)
TOLERANCE_MINOR = 5  # the automatic matcher also pairs amounts this close (minor units)
MAX_LINES = 500  # statement lines per run
MULTI_TENANT = True
ENTRY_CAP = 5000  # ledger entries considered per run (a bigger account needs a period_start / period_end)
