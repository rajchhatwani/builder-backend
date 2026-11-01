"""Safety limits, enforced by the parser and again by the checker."""

MAX_SOURCE_CHARS = 2000
MAX_NODES = 200
MAX_DEPTH = 16
MAX_LIST_ITEMS = 100
MAX_STRING_CHARS = 1000
MAX_DECIMAL_DIGITS = 28
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
DECIMAL_SCALE = 10  # `/` on decimals rounds half away from zero to this many places
