"""Redis-backed rate limiting dependency with graceful degradation."""
from typing import Callable
from fastapi import Request, HTTPException, status
from app.db.redis import redis_client
from app.core.logger import logger


class RateLimiter:
    """FastAPI route dependency to throttle requests per client IP using Redis."""

    def __init__(
        self,
        times: int = 60,
        seconds: int = 60,
        route_name: str = "",
        dynamic_setting: str = "",
    ):
        self.times = times
        self.seconds = seconds
        self.route_name = route_name
        self.dynamic_setting = dynamic_setting

    async def __call__(self, request: Request) -> None:
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        route_key = self.route_name or request.url.path
        redis_key = f"ratelimit:{route_key}:{client_ip}"

        effective_times = self.times
        try:
            if self.dynamic_setting:
                from app.services.system_settings import system_settings_manager
                sys_settings = await system_settings_manager.get_settings()
                val = getattr(sys_settings, self.dynamic_setting, None)
                if val is not None:
                    effective_times = int(val)
            elif "/login" in route_key:
                from app.services.system_settings import system_settings_manager
                sys_settings = await system_settings_manager.get_settings()
                effective_times = int(sys_settings.rate_limit_login_per_minute)
        except Exception as exc:
            logger.debug(f"Could not load dynamic rate limit: {exc}")

        try:
            # Atomic increment and expire
            pipe = redis_client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, self.seconds, nx=True)
            results = await pipe.execute()
            current_count = results[0]

            if current_count > effective_times:
                logger.warning(
                    f"Rate limit exceeded for IP {client_ip} on {route_key}: {current_count}/{effective_times}"
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Maximum {effective_times} requests allowed per {self.seconds} seconds.",
                    headers={"code": "RATE_LIMIT_EXCEEDED", "Retry-After": str(self.seconds)},
                )
        except HTTPException:
            raise
        except Exception as exc:
            # Architecture §16: If Redis is unavailable, fallback gracefully and log
            logger.warning(f"Rate limiter degraded due to Redis error: {exc}")
            return
