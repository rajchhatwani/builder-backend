"""Knowledge library settings (generated from the spec: change them in the builder). Plain data, integers only."""

MANAGE_ROLES: tuple[str, ...] = ('admin',)  # may create sources
READ_ROLES: tuple[str, ...] = ()  # may search / ask / list; an empty tuple means any signed-in user
KNOWN_ROLES: tuple[str, ...] = ('admin', 'agent', 'customer',)  # the roles a source may be shared with
STAGE = 'answer'  # the gateway stage /ai/knowledge/ask runs on
CHUNK_CHARS = 200
MAX_SOURCES = 1000
MAX_TEXT_CHARS = 500000
