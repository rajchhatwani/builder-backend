"""Document AI settings (generated from the spec: change them in the builder). Plain data, integers only."""

UPLOAD_ROLES: tuple[str, ...] = ('agent', 'customer',)  # an empty tuple means any signed-in user
REVIEW_ROLES: tuple[str, ...] = ('admin',)
READ_ROLES: tuple[str, ...] = ('agent',)
STAGE = 'extract'  # the gateway stage extraction runs on
REVIEW_BELOW_BP = 8000  # a field below this confidence (basis points) goes to review
MAX_TEXT_CHARS = 200000
ALLOW_SELF_REVIEW = False  # may the uploader review their own document

# document kind -> ordered fields: (name, required)
KINDS: dict[str, list[tuple[str, bool]]] = {'invoice': [('vendor', False), ('total', True), ('due_date', False)],
 'receipt': [('merchant', True), ('amount', True)]}
