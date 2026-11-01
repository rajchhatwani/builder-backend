# app/custom/hooks/check_request.py
# platform:hook check_request  point=LeaveRequest.validate  kind=pure  contract=v1
from app.hooks_gen.contracts import RequestInput, RequestResult


def check_request(data: RequestInput) -> RequestResult:  # platform:signature (fixed)
    # <agent:body hook=check_request>
    raise NotImplementedError
    # </agent:body>
