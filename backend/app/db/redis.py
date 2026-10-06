"""Redis client setup and connectivity health check with event-loop awareness."""
import asyncio
from typing import Dict
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logger import logger

_loop_clients: Dict[int, aioredis.Redis] = {}


def get_redis_client() -> aioredis.Redis:
    """Return an async Redis client bound to the current running event loop."""
    try:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
    except RuntimeError:
        loop_id = 0

    client = _loop_clients.get(loop_id)
    if client is None:
        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=3.0,
            socket_connect_timeout=3.0,
        )
        if loop_id != 0:
            _loop_clients[loop_id] = client
    return client


class _LazyRedisProxy:
    """Proxy object forwarding attribute access to get_redis_client() for the active loop."""

    def __getattr__(self, name: str):
        return getattr(get_redis_client(), name)


redis_client = _LazyRedisProxy()


async def check_redis_health() -> bool:
    """Check connectivity to Redis by sending a PING command."""
    try:
        client = get_redis_client()
        res = await client.ping()
        return bool(res)
    except Exception as exc:
        logger.warning(f"Redis health check failed: {exc}")
        return False
