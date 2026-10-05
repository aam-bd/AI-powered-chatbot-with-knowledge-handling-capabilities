"""Redis client setup and connectivity health check."""
import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logger import logger

redis_client = aioredis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_timeout=3.0,
    socket_connect_timeout=3.0,
)


async def check_redis_health() -> bool:
    """Check connectivity to Redis by sending a PING command."""
    try:
        res = await redis_client.ping()
        return bool(res)
    except Exception as exc:
        logger.warning(f"Redis health check failed: {exc}")
        return False
