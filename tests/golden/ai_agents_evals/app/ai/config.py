"""AI gateway settings (generated from the spec: change them in the builder). Plain data, integers only."""

# who may call / read / manage; an empty tuple means any signed-in user
CALL_ROLES: tuple[str, ...] = ('admin',)
READ_ROLES: tuple[str, ...] = ('admin', 'agent',)
MANAGE_ROLES: tuple[str, ...] = ('admin',)
MULTI_TENANT = True
REGION = 'eu'  # data: where the provider endpoint would run
ZERO_RETENTION = False  # True: prompt and output text are never stored, only hashes and counts

# budget: integer micro-USD (1 USD = 1_000_000) per period; the worst case of a call is reserved before it runs
BUDGET_PERIOD = 'day'  # "day" | "month" (UTC)
BUDGET_LIMIT_MICRO_USD = 5000000
PER_CALL_CAP_MICRO_USD = 1000000

# UNVERIFIED (owner): micro-USD per 1,000,000 tokens as (input, output). Fake models only; check before any real provider.
PRICES: dict[str, tuple[int, int]] = {'fake-embed': (20000, 0), 'fake-large': (3000000, 15000000), 'fake-small': (150000, 600000)}

# providers: name -> kind (only "fake") and the NAME of the env var that would hold a BYO key (data only, never read)
PROVIDERS: dict[str, dict[str, str | None]] = {'main': {'byo_key_env': None, 'kind': 'fake'}}

# per-stage router: stage -> provider, model, output cap, optional fallback model
STAGES: dict[str, dict[str, str | int | None]] = {'answer': {'fallback_model': None,
            'max_output_tokens': 512,
            'model': 'fake-small',
            'provider': 'main'}}

MAX_MESSAGES = 50
MAX_CONTENT_CHARS = 20_000
STALE_RESERVATION_SECONDS = 300  # a reservation older than this (crashed worker) is released as `abandoned`
WAIT_FOR_DUPLICATE_SECONDS = 30
MAX_TOTAL_CHARS = 400_000  # all message texts of one call together (a hostile body cannot make the gateway chew on megabytes)
# Test switch of the FAKE provider: [[fake:...]] and [[conf=...]] markers in message text are honoured only when this is True.
# Off by default: document text, knowledge chunks and user messages are untrusted and must never steer the provider.
FAKE_DIRECTIVES = False
