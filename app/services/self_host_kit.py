"""Self-host kit (B3-10): the generated project (code + Dockerfile + docker-compose.yml) plus a
short guide, for people who outgrow the preview limits. Built from the spec only: provider and
auth secrets are never injected, so the archive carries no secrets."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generator import InvalidSpecError, generate
from app.core.generator.archive import build_zip
from app.core.spec_models import Spec
from app.exceptions import AppError
from app.services.spec_service import SpecService

GUIDE = """# Run {name} yourself

This archive is the complete generated project: code, `Dockerfile` and `docker-compose.yml`.
It contains no secrets. Nothing here depends on the builder platform.

## Start

```
docker compose up --build
```

The API listens on http://localhost:8000 (`API_PORT` changes the port); `/health` answers when it
is up and the interactive docs are at `/docs`.

## Before you expose it

- The compose file ships with a throwaway database password (`app`). Set your own in both
  `POSTGRES_PASSWORD` and `DATABASE_URL`, or point `DATABASE_URL` at your managed Postgres.
- Put the API behind TLS (a reverse proxy or your cloud load balancer).
- Provide any provider credentials (e-mail, payments, storage) as environment variables, as
  described in `README.md` and `.env.example`; they are not part of this archive.
{seed}
## Differences from the preview

A preview runs in a locked-down sandbox with no outbound network, demo data and enforced limits.
Self-hosted, you choose the resources, the network access and how long the data lives.
"""

SEED = """
## Demo data

This project defines a seed profile. After the first start, load it with:

```
docker compose run --rm -e APP_ENV=development api python -m app.seed --profile {profile}
```
"""


def build_kit_files(spec: Spec) -> dict[str, str]:
    try:
        files = dict(generate(spec))
    except InvalidSpecError as exc:
        raise AppError(
            "spec_invalid",
            f"spec has {len(exc.issues)} validation issue(s); fix them to generate",
            422,
            [i.model_dump() for i in exc.issues],
        ) from exc
    names = sorted(p.name for p in spec.seed)
    seed = SEED.format(profile="demo" if "demo" in names else names[0]) if names else ""
    files["SELF-HOST.md"] = GUIDE.format(name=spec.project.name, seed=seed)
    return files


async def build_kit(session: AsyncSession, project_id: uuid.UUID) -> tuple[bytes, str]:
    spec = await SpecService(session).assemble(project_id)
    files = build_kit_files(spec)
    return build_zip(spec.project.slug, files), f"{spec.project.slug}-self-host.zip"
