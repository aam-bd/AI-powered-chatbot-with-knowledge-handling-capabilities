"""Qdrant client and health check."""
import httpx
from app.core.config import settings
from app.core.logger import logger


async def check_qdrant_health() -> bool:
    """Check connectivity to Qdrant via its HTTP healthz endpoint."""
    url = f"{settings.QDRANT_URL.rstrip('/')}/healthz"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except Exception as exc:
        logger.warning(f"Qdrant health check failed: {exc}")
        return False
