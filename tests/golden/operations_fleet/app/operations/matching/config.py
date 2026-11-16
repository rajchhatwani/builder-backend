"""Matching settings (generated from the spec: change them in the builder). Plain data, integers only."""

# who may read / assign; an empty tuple means any signed-in user
READ_ROLES: tuple[str, ...] = ('admin', 'dispatcher',)
ASSIGN_ROLES: tuple[str, ...] = ('admin', 'dispatcher',)
WEIGHT_DISTANCE = 600
WEIGHT_LOAD = 300
WEIGHT_RATING = 100
MAX_DISTANCE_M = 20000  # a candidate farther away than this is not eligible
MAX_LOAD = 5  # a candidate with this many open jobs (or more) is not eligible
POSITION_MAX_AGE_SECONDS = 900  # a stored /location position older than this is not used to rank a candidate
OFFER_TTL_SECONDS = 300
MAX_CANDIDATES = 200
MAX_BATCH_REQUESTS = 100
EXACT_MAX_REQUESTS = 8  # the batch solver is exact up to this many requests and EXACT_MAX_CANDIDATES candidates
EXACT_MAX_CANDIDATES = 12
LOCATION = True  # the location block is declared: candidates may omit coordinates
MULTI_TENANT = True
