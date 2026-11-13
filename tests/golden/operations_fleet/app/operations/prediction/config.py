"""Prediction settings (generated from the spec: change them in the builder). Plain data, integers only."""

# who may read / write; an empty tuple means any signed-in user
READ_ROLES: tuple[str, ...] = ('admin', 'dispatcher',)
WRITE_ROLES: tuple[str, ...] = ('admin', 'dispatcher',)
MODEL_ID = "fake-linear-v1"  # recorded on every prediction (the deterministic fake predictor)
UNIT = "minutes"  # what the integer value / low / high / actual are counted in
INTERVAL_BP = 2000  # the fake predictor's interval: value +- value * INTERVAL_BP / 10000 (at least 1)
MAX_FEATURES = 50
MULTI_TENANT = True
