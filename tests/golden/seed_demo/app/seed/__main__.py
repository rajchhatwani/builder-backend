"""Command line (generated): python -m app.seed --profile demo [--reset] [--check] ...

Exit codes: 0 done, 2 bad usage, 3 refused by the production guard, 4 conflict with existing data,
5 invariant check failed.
"""

import argparse
import asyncio
import sys

from app.db import engine as db_engine
from app.seed import guard, runner
from app.seed.plan import PROFILES


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description="Deterministic demo/dev data. Development only: refuses to run in production.",
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), help="seed profile to create")
    parser.add_argument(
        "--reset", action="store_true", help="delete the rows a seed created (only those), then seed again"
    )
    parser.add_argument("--reset-only", action="store_true", help="delete the seeded rows and stop")
    parser.add_argument("--check", action="store_true", help="check the seeded rows now in the database")
    parser.add_argument("--list", action="store_true", help="list the profiles")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help=f"override the production guard (also needs {guard.OVERRIDE_ENV}={guard.OVERRIDE_VALUE})",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.check:
            problems = await runner.check()
            for problem in problems:
                print(f"INVARIANT FAILED: {problem}", file=sys.stderr)
            print("all invariants hold" if not problems else f"{len(problems)} problem(s)")
            return 5 if problems else 0
        if args.reset or args.reset_only:
            report = await runner.reset(allow_production=args.allow_production)
            print("removed seeded rows:", dict(sorted(report.counts.items())) or "none")
            if report.kept:
                print(f"kept {len(report.kept)} seeded tenant(s) that other data still uses")
        if args.profile and not args.reset_only:
            report = await runner.seed(args.profile, allow_production=args.allow_production)
            print(f"{report.status}: profile {report.profile}")
            print("rows:", dict(sorted(report.counts.items())))
            print("digest:", report.digest)
        return 0
    except guard.SeedRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    except runner.InvariantFailure as exc:
        print(f"INVARIANTS FAILED (nothing was written): {exc}", file=sys.stderr)
        return 5
    except runner.SeedError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4
    finally:
        await db_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(sorted(PROFILES)))
        return 0
    if not (args.profile or args.reset_only or args.check):
        parser.error("give --profile NAME (or --reset-only / --check / --list)")
    if args.reset_only and args.profile:
        parser.error("--reset-only does not take --profile")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
