# app/custom/hooks/announce_order.py
# platform:hook announce_order  point=Order.after_commit  kind=effect  contract=v1
from app.hooks_gen.contracts import AnnounceInput, AnnounceResult


def announce_order(data: AnnounceInput) -> AnnounceResult:  # platform:signature (fixed)
    # <agent:body hook=announce_order>
    raise NotImplementedError
    # </agent:body>
