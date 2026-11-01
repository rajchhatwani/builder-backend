"""Move every stored credential to the current master key (generated).

    PROVIDER_VAULT_KEY=<new> PROVIDER_VAULT_KEY_VERSION=2 PROVIDER_VAULT_KEY_PREVIOUS=1=<old> \\
        python -m app.providers.reencrypt

Run it after raising PROVIDER_VAULT_KEY_VERSION; once it reports 0 left you can drop the old key."""

import asyncio

from app.db import session_factory
from app.providers import vault


async def main() -> int:
    async with session_factory() as session:
        changed = await vault.reencrypt_all(session)
        await session.commit()
    return changed


if __name__ == "__main__":
    print(f"re-encrypted {asyncio.run(main())} credential(s)")
