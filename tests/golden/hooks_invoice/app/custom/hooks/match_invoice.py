# app/custom/hooks/match_invoice.py
# platform:hook match_invoice  point=Invoice.transition_guard(submit)  kind=pure  contract=v1
from app.hooks_gen.contracts import MatchInput, MatchResult


def match_invoice(data: MatchInput) -> MatchResult:  # platform:signature (fixed)
    # <agent:body hook=match_invoice>
    raise NotImplementedError
    # </agent:body>
