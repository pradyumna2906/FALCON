"""Atomic Redis sliding windows and expiring concurrency leases.

Redis TIME avoids clock skew between API replicas. Keys expire after idle use.
Lease duration exceeds the enforced request deadline, including cancellation.
"""

from contextlib import asynccontextmanager
import asyncio
import hashlib
from uuid import uuid4

from falcon_api.core.errors import ApplicationError


RESERVE = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60000)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[2]) then return 1 end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 2 end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('ZADD', KEYS[2], now + 120000, ARGV[3])
redis.call('PEXPIRE', KEYS[1], 60000)
redis.call('PEXPIRE', KEYS[2], 120000)
return 0
"""


class RedisRequestLimiter:
    def __init__(self, client, *, namespace: str, requests_per_minute: int,
                 max_concurrent_requests: int):
        self.client = client
        self.namespace = namespace
        self.rate = requests_per_minute
        self.concurrency = max_concurrent_requests

    @asynccontextmanager
    async def permit(self, user_id):
        owner = hashlib.sha256(str(user_id).encode()).hexdigest()
        prefix = f"falcon:{self.namespace}:{{{owner}}}"
        token = uuid4().hex
        try:
            result = await self.client.eval(RESERVE, 2, prefix + ":rate", prefix + ":leases",
                                            self.rate, self.concurrency, token)
        except Exception:
            raise ApplicationError(code="rate_limit_unavailable", message="Service temporarily unavailable.", status_code=503) from None
        if result:
            raise ApplicationError(code="assistant_busy" if result == 1 else "assistant_rate_limited",
                                   message="Request limit reached. Please try again later.", status_code=429)
        try:
            async with asyncio.timeout(90):
                yield
        finally:
            try:
                await self.client.zrem(prefix + ":leases", token)
            except Exception:
                # Lease expiry recovers a disconnected or terminated replica.
                pass
