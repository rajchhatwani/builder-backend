"""Where refresh tokens live: Redis.

The service only talks to the `TokenStore` interface. A refresh token is single use: redeeming
it ("rotating") marks it revoked and the caller issues a replacement in the same family. If a
token that was already rotated is presented again, the whole family is revoked, because only
a thief holding an old copy can do that.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import redis.asyncio as redis_asyncio
from redis.exceptions import RedisError

from app.auth import config
from app.core.errors import AppError


@dataclass(frozen=True)
class Rotation:
    # "ok", "unknown" (never issued or expired), "expired" or "reused" (family revoked)
    status: str
    user_id: uuid.UUID | None = None
    family_id: uuid.UUID | None = None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)

_PREFIX = "auth:rt:"  # one hash per token: user_id, family_id, revoked
_FAMILY = "auth:rtf:"  # set of the token hashes in a family
_USER = "auth:rtu:"  # set of every token hash of a user

# Atomically: find the token, report reuse, or mark it revoked and return its owner.
_ROTATE = """
local d = redis.call('HMGET', KEYS[1], 'user_id', 'family_id', 'revoked')
if not d[1] then return {0} end
if d[3] == '1' then return {2, d[2]} end
redis.call('HSET', KEYS[1], 'revoked', '1')
return {1, d[1], d[2]}
"""
# Mark every live token listed in a set as revoked (kept until it expires, to spot reuse).
_REVOKE_SET = """
for _, h in ipairs(redis.call('SMEMBERS', KEYS[1])) do
  local k = ARGV[1] .. h
  if redis.call('EXISTS', k) == 1 then redis.call('HSET', k, 'revoked', '1') end
end
return 1
"""


@lru_cache
def _client(url: str) -> Any:
    return redis_asyncio.from_url(url, decode_responses=True)


class TokenStore:
    """Refresh tokens in Redis, expiring on their own. Nothing here touches the database."""

    def __init__(self, _session: object = None) -> None:
        self.client = _client(config.get_auth_settings().redis_url)

    async def add(
        self, user_id: uuid.UUID, family_id: uuid.UUID, token_hash: str, expires_at: dt.datetime
    ) -> None:
        ttl = max(1, int((expires_at - _now()).total_seconds()))
        try:
            pipe = self.client.pipeline(transaction=True)
            key = _PREFIX + token_hash
            pipe.hset(
                key, mapping={"user_id": str(user_id), "family_id": str(family_id), "revoked": "0"}
            )
            pipe.expire(key, ttl)
            for set_key, member in ((_FAMILY + str(family_id), token_hash), (_USER + str(user_id), token_hash)):
                pipe.sadd(set_key, member)
                pipe.expire(set_key, ttl)
            await pipe.execute()
        except RedisError as exc:
            raise _unavailable(exc) from exc

    async def rotate(self, token_hash: str) -> Rotation:
        try:
            result = await self.client.eval(_ROTATE, 1, _PREFIX + token_hash)
            if result[0] == 0:
                return Rotation("unknown")
            if result[0] == 2:
                await self.client.eval(_REVOKE_SET, 1, _FAMILY + result[1], _PREFIX)
                return Rotation("reused")
        except RedisError as exc:
            raise _unavailable(exc) from exc
        return Rotation("ok", uuid.UUID(result[1]), uuid.UUID(result[2]))

    async def revoke_family_of(self, token_hash: str) -> None:
        try:
            family_id = await self.client.hget(_PREFIX + token_hash, "family_id")
            if family_id is not None:
                await self.client.eval(_REVOKE_SET, 1, _FAMILY + family_id, _PREFIX)
        except RedisError as exc:
            raise _unavailable(exc) from exc

    async def revoke_all(self, user_id: uuid.UUID) -> None:
        try:
            await self.client.eval(_REVOKE_SET, 1, _USER + str(user_id), _PREFIX)
        except RedisError as exc:
            raise _unavailable(exc) from exc


def _unavailable(exc: RedisError) -> AppError:
    return AppError("token_store_unavailable", "the token store is unavailable", 503)
