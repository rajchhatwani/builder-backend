# app/custom/hooks/notify_approved.py
# platform:hook notify_approved  point=Invoice.after_commit  kind=effect  contract=v1
from app.hooks_gen.contracts import NotifyInput, NotifyResult


def notify_approved(data: NotifyInput) -> NotifyResult:  # platform:signature (fixed)
    # <agent:body hook=notify_approved>
    raise NotImplementedError
    # </agent:body>
