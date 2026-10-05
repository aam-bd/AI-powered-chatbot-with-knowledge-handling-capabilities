"""FastAPI application initialization, error handling, and middleware configuration."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logger import setup_logging, RequestIdMiddleware, logger
from app.api.router import api_router
from scripts.seed_admin import seed_admin

# Mapping of standard HTTP status codes to standardized error codes per §8
DEFAULT_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown hooks."""
    setup_logging(log_level=settings.LOG_LEVEL)
    logger.info(
        f"Starting application in {settings.APP_ENV} environment (Log level: {settings.LOG_LEVEL})"
    )

    # Optional seeding of initial admin account at startup per §9.1
    if settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD:
        try:
            await seed_admin()
        except Exception as exc:
            logger.error(f"Failed to seed admin user on startup: {exc}")

    # Initialize Qdrant collection kb_chunks and verify embedding guard
    try:
        from app.db.qdrant import init_qdrant_collection
        init_qdrant_collection()
    except Exception as exc:
        logger.warning(f"Failed to initialize Qdrant collection on startup: {exc}")

    yield
    logger.info("Application shutting down.")


app = FastAPI(
    title="Knowledge-Base AI Chatbot API",
    description="Enterprise-grade RAG chatbot API with strict knowledge base grounding",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Request ID & Logging Middleware (must be outermost to trace entire request lifecycle)
app.add_middleware(RequestIdMiddleware)

# Cross-Origin Resource Sharing (CORS) Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Standardized error handler per architecture §8: { "detail": "...", "code": "..." }
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """Ensure all HTTP exceptions return the standardized {detail, code} JSON schema."""
    error_code = "ERROR"
    if exc.headers and "code" in exc.headers:
        error_code = exc.headers["code"]
    else:
        error_code = DEFAULT_ERROR_CODES.get(exc.status_code, "ERROR")

    headers = dict(exc.headers) if exc.headers else {}
    headers.pop("code", None)

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": error_code},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Ensure Pydantic schema validation failures return standardized {detail, code} JSON."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": str(exc.errors()[0].get("msg", "Validation error")) if exc.errors() else "Validation error",
            "code": "VALIDATION_ERROR",
        },
    )


# Mount API routers
app.include_router(api_router)


@app.get("/", tags=["root"])
async def root():
    """Root endpoint for basic service identification."""
    return {
        "name": "Knowledge-Base AI Chatbot API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/api/v1/health",
    }
