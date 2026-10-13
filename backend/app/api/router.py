"""API v1 router aggregating all modular endpoints."""
from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.users import router as users_router
from app.api.v1.admin_llm import router as admin_llm_router

api_router = APIRouter(prefix="/api/v1")

# Mount sub-routers
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(documents_router)
api_router.include_router(users_router)
api_router.include_router(admin_llm_router)
