"""Geo settings (generated from the spec: change them in the builder). Plain data, integers only."""

# who may read / write; an empty tuple means any signed-in user
READ_ROLES: tuple[str, ...] = ('admin', 'dispatcher', 'driver',)
WRITE_ROLES: tuple[str, ...] = ('admin', 'dispatcher',)
PROVIDER = "fake"  # deterministic fake adapters: no outbound call is ever made
GRID_CELL_MICRO = 10000  # size of one index cell in micro-degrees.
# FIXED once places exist: stored `cell` values use it, so changing it later makes radius queries miss old
# places. Re-index first (UPDATE geo_places SET cell = ...) or keep the old value.
MAX_PLACES = 1000
MAX_GEOFENCES = 20
MAX_POLYGON_VERTICES = 12
MAX_RADIUS_M = 5000000
SCAN_CAP = 5000  # rows one radius query reads before it reports `truncated`
MULTI_TENANT = True
