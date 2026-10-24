"""Create (or promote to) a platform administrator.

    docker compose exec api uv run python /app/scripts/create_admin.py you@example.com
    ... create_admin.py you@example.com --role platform_support
    ... create_admin.py you@example.com --adopt-projects   # claim projects made before accounts

The password is read from a prompt (never from the command line, where it would land in shell
history and process lists). For automation, pipe it in: `echo "$PW" | ... --password-stdin`.
Re-running for an existing account changes its platform role and, with a new password, replaces it.
"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from anywhere

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core import platform_security as sec  # noqa: E402
from app.db import get_session_factory  # noqa: E402
from app.models.enums import PlatformRole  # noqa: E402
from app.models.platform import PlatformUser  # noqa: E402
from app.services import audit_service  # noqa: E402
from app.services.platform_auth_service import (  # noqa: E402
    PlatformAuthService,
    RequestInfo,
    normalize_email,
)

ADMIN_ROLES = (PlatformRole.platform_admin, PlatformRole.platform_support)


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("The passwords do not match.")
    return first


async def main(
    email: str, role: PlatformRole, password: str | None, adopt_projects: bool = False
) -> None:
    settings = get_settings()
    async with get_session_factory()() as session:
        existing = (
            await session.execute(
                select(PlatformUser).where(PlatformUser.email == normalize_email(email))
            )
        ).scalar_one_or_none()
        service = PlatformAuthService(session, settings)
        if existing is None:
            if not password:
                raise SystemExit("A password is required to create a new account.")
            user = await service.create_user(
                email=email,
                password=password,
                name="Administrator",
                role=role,
                info=RequestInfo(),
            )
            verb = "created"
        else:
            user = existing
            user.platform_role = role
            if password:
                problems = sec.password_problems(password, user.email)
                if problems:
                    raise SystemExit("Password " + "; ".join(problems))
                user.password_hash = sec.hash_password(password)
                user.must_change_password = False
            await service.revoke_all_sessions(user)
            verb = "updated"
        adopted = await service.adopt_unclaimed_projects(user) if adopt_projects else 0
        await audit_service.record(
            session,
            action="admin.cli_user",
            actor_email="cli",
            via="cli",
            target_type="user",
            target_id=user.id,
            detail={"role": role.value, "result": verb, "adopted_projects": adopted},
        )
        await session.commit()
    print(f"{verb}: {user.email} is now {role.value}")
    if adopt_projects:
        print(f"adopted {adopted} project(s) that had no owner")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("email")
    parser.add_argument("--role", choices=[r.value for r in ADMIN_ROLES], default="platform_admin")
    parser.add_argument(
        "--password-stdin", action="store_true", help="read the password from stdin"
    )
    parser.add_argument(
        "--adopt-projects",
        action="store_true",
        help="become the owner of projects created before accounts existed (they have no owner)",
    )
    parser.add_argument(
        "--keep-password",
        action="store_true",
        help="for an existing account: change only the role",
    )
    args = parser.parse_args()
    chosen = None if args.keep_password else read_password(args.password_stdin)
    asyncio.run(main(args.email, PlatformRole(args.role), chosen, args.adopt_projects))
