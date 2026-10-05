"""Loguru structured logging configuration with JSON output and Request-ID tracing.

Complies with architecture.md section 10:
- Loguru JSON formatting to stdout and logs/app.log
- 10 MB file rotation, 14 days retention
- Automatic creation of the logs/ directory
- Request-ID middleware and context propagation
"""
import contextvars
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Callable
from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable for tracing request IDs across async boundaries
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Return the current request ID from context."""
    return request_id_ctx.get("-")


def json_log_formatter(record: dict) -> str:
    """Format Loguru records into clean, top-level JSON strings containing request_id."""
    req_id = record["extra"].get("request_id") or request_id_ctx.get("-")
    log_entry = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "request_id": req_id,
        "message": record["message"],
        "module": record["name"],
        "line": record["line"],
    }
    
    # Include exception info if present
    if record["exception"]:
        log_entry["exception"] = {
            "type": str(record["exception"].type),
            "value": str(record["exception"].value),
            "traceback": bool(record["exception"].traceback),
        }
        
    # Include any additional structured extra fields
    for k, v in record["extra"].items():
        if k not in ("request_id", "serialized") and k not in log_entry:
            log_entry[k] = v
            
    record["extra"]["serialized"] = json.dumps(log_entry)
    return "{extra[serialized]}\n"


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """Configure Loguru sinks for stdout and rotating file app.log.
    
    Args:
        log_level: Minimum log level (DEBUG, INFO, etc.)
        log_dir: Directory where logs should be stored
    """
    # Ensure logs directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "app.log"

    # Remove default handler
    logger.remove()

    # Patcher to ensure request_id is always present in record["extra"]
    def patch_record(record):
        if "request_id" not in record["extra"]:
            record["extra"]["request_id"] = request_id_ctx.get("-")

    logger.configure(patcher=patch_record)

    # 1. Stdout JSON sink
    logger.add(
        sys.stdout,
        level=log_level,
        format=json_log_formatter,
        enqueue=True,
    )

    # 2. Rotating file JSON sink (10MB rotation, 14 days retention)
    logger.add(
        str(log_file),
        level=log_level,
        format=json_log_formatter,
        rotation="10 MB",
        retention="14 days",
        compression=None,
        enqueue=True,
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware to manage request IDs and request logging.
    
    - Extracts or generates X-Request-ID
    - Binds request ID to context variable and log record
    - Attaches X-Request-ID to the HTTP response
    - Logs request method, path, status, and duration
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(req_id)
        start_time = time.perf_counter()

        logger.bind(request_id=req_id).info(
            f"Started {request.method} {request.url.path}"
        )

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            response.headers["X-Request-ID"] = req_id

            logger.bind(
                request_id=req_id,
                status_code=response.status_code,
                duration_ms=duration_ms,
            ).info(
                f"Completed {request.method} {request.url.path} with status {response.status_code} in {duration_ms}ms"
            )
            return response
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.bind(
                request_id=req_id,
                duration_ms=duration_ms,
            ).error(
                f"Failed {request.method} {request.url.path} after {duration_ms}ms: {exc}"
            )
            raise
        finally:
            request_id_ctx.reset(token)
