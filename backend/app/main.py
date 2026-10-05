"""FastAPI application initialization and middleware configuration."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logger import setup_logging, RequestIdMiddleware, logger
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown hooks."""
    setup_logging(log_level=settings.LOG_LEVEL)
    logger.info(
        f"Starting application in {settings.APP_ENV} environment (Log level: {settings.LOG_LEVEL})"
    )
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
