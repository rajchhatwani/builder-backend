# app/custom/hooks/peek.py
# platform:hook peek  point=Ticket.after_commit  kind=effect  contract=v1
from app.hooks_gen.contracts import PeekInput, PeekResult


def peek(data: PeekInput) -> PeekResult:  # platform:signature (fixed)
    # <agent:body hook=peek>
    raise NotImplementedError
    # </agent:body>
