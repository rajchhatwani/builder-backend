"""Location settings (generated from the spec: change them in the builder). Plain data, integers only."""

# who may read / write; an empty tuple means any signed-in user
READ_ROLES: tuple[str, ...] = ('admin', 'dispatcher', 'driver',)
WRITE_ROLES: tuple[str, ...] = ('admin', 'dispatcher', 'driver',)
HISTORY_CAP = 5  # history rows kept per subject (older ones are deleted when a newer one arrives)
MAX_SUBJECTS = 1000
MAX_FUTURE_SECONDS = 300  # a recorded_at further ahead than this is refused
BOX_CAP = 500  # rows one bounding-box query returns
GEO = True  # the geo block is declared: positions are evaluated against geofences
MULTI_TENANT = True
