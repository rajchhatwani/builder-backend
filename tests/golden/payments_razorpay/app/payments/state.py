"""The payment, refund and dispute state machines (generated).

State only moves forward along these edges. Every change in the service goes through an atomic
`UPDATE ... WHERE status IN (allowed sources)`, so two processes (an API replica and a worker, a
webhook and a reconcile run) racing on the same row cannot move it backwards or skip a step.
"""

# payment
CREATING = "creating"  # row written, provider not yet called (or the call is being retried)
REQUIRES_PAYMENT = "requires_payment"  # checkout is open, waiting for the payer
PROCESSING = "processing"  # the payer paid with a slow method; funds not confirmed yet
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELED = "canceled"
EXPIRED = "expired"

PAYMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    CREATING: frozenset({REQUIRES_PAYMENT, FAILED}),
    REQUIRES_PAYMENT: frozenset({PROCESSING, SUCCEEDED, FAILED, CANCELED, EXPIRED}),
    PROCESSING: frozenset({SUCCEEDED, FAILED}),
    SUCCEEDED: frozenset(),
    # Money wins: if the provider reports a payment as paid after we closed it (cancelled,
    # expired or failed on our side), the payment becomes succeeded rather than hiding real money.
    FAILED: frozenset({SUCCEEDED}),
    CANCELED: frozenset({SUCCEEDED}),
    EXPIRED: frozenset({SUCCEEDED}),
}
# At most one of these may exist per payable row: it is what stops a double charge.
ACTIVE_PAYMENT_STATES = (CREATING, REQUIRES_PAYMENT, PROCESSING, SUCCEEDED)
OPEN_PAYMENT_STATES = (CREATING, REQUIRES_PAYMENT, PROCESSING)

# refund
PENDING_APPROVAL = "pending_approval"  # above the threshold: waits for a second person
REQUESTED = "requested"  # approved (or no approval needed); not sent to the provider yet
SUBMITTING = "submitting"  # a process is sending it to the provider
PENDING = "pending"  # the provider accepted it; money is on its way
REFUND_SUCCEEDED = "succeeded"
REFUND_FAILED = "failed"
REFUND_CANCELED = "canceled"
REJECTED = "rejected"  # the approver said no

REFUND_TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING_APPROVAL: frozenset({REQUESTED, REJECTED}),
    REQUESTED: frozenset({SUBMITTING, REFUND_FAILED}),
    SUBMITTING: frozenset({PENDING, REFUND_SUCCEEDED, REFUND_FAILED, REQUESTED}),
    PENDING: frozenset({REFUND_SUCCEEDED, REFUND_FAILED, REFUND_CANCELED}),
    REFUND_SUCCEEDED: frozenset(),
    REFUND_FAILED: frozenset(),
    REFUND_CANCELED: frozenset(),
    REJECTED: frozenset(),
}
# Money held back for a refund while it can still succeed.
REFUND_RESERVING_STATES = (PENDING_APPROVAL, REQUESTED, SUBMITTING, PENDING, REFUND_SUCCEEDED)

# dispute (chargeback): follows the provider's own status
DISPUTE_OPEN = "open"
DISPUTE_UNDER_REVIEW = "under_review"
DISPUTE_WON = "won"
DISPUTE_LOST = "lost"
DISPUTE_CLOSED = "closed"
DISPUTE_STATES = (DISPUTE_OPEN, DISPUTE_UNDER_REVIEW, DISPUTE_WON, DISPUTE_LOST, DISPUTE_CLOSED)


def can_move(transitions: dict[str, frozenset[str]], source: str, target: str) -> bool:
    return target in transitions.get(source, frozenset())


def sources_for(transitions: dict[str, frozenset[str]], target: str) -> tuple[str, ...]:
    """Every state from which `target` may be reached (sorted, for a stable SQL)."""
    return tuple(sorted(s for s, targets in transitions.items() if target in targets))
