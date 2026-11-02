from dataclasses import dataclass

from fastapi import Depends, Query

from app.api.security import acting_principal, forbidden
from app.services.access_service import Principal
from app.services.platform_auth_service import is_staff


@dataclass
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


async def require_verified_email(principal: Principal = Depends(acting_principal)) -> Principal:
    """CO3-7: unverified accounts (public sign-up that never clicked the e-mail link) may sign
    in and look around but not generate, preview or deploy. Staff are exempt. Accounts that
    existed before verification was introduced were backfilled as verified."""
    user = principal.user
    if user.email_verified_at is None and not is_staff(user):
        raise forbidden("confirm your e-mail address first", "email_not_verified")
    return principal
