"""Pytest fixtures and configuration with strict test database isolation."""
import os
import uuid
import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from sqlalchemy import text

# Enforce isolated test database BEFORE importing application modules
raw_db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/chatbot")
if "/chatbot_test" not in raw_db_url:
    test_db_url = raw_db_url.rsplit("/", 1)[0] + "/chatbot_test"
    os.environ["DATABASE_URL"] = test_db_url
    os.environ["TEST_DATABASE_URL"] = test_db_url
else:
    test_db_url = raw_db_url

import app.db.session as db_session
from app.core.config import settings
settings.DATABASE_URL = test_db_url

# Re-bind engine and sessionmaker to isolated test database
test_engine = create_async_engine(
    test_db_url,
    poolclass=NullPool,
    echo=False,
)
test_sessionmaker = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
db_session.engine = test_engine
db_session.AsyncSessionLocal = test_sessionmaker

from starlette.testclient import TestClient
from app.main import app
from app.db.session import Base
from app.core.security import hash_password
from app.models.sql_models import User
from app.services.llm.runtime import bootstrap_llm_settings


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure chatbot_test database has tables and baseline seed data."""
    async def _init_db():
        # Verify schema is created
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed admin user if not present
        async with test_sessionmaker() as session:
            admin_email = settings.ADMIN_EMAIL or "admin@example.com"
            admin_check = await session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": admin_email},
            )
            if not admin_check.scalar_one_or_none():
                admin_user = User(
                    id=uuid.uuid4(),
                    email=admin_email,
                    password_hash=hash_password("AdminPassword123!"),
                    role="admin",
                    is_active=True,
                )
                session.add(admin_user)
                await session.commit()

            # Seed default LLM provider
            await bootstrap_llm_settings()

    asyncio.run(_init_db())


@pytest.fixture
def client():
    """Synchronous test client for the FastAPI application with isolated client IP."""
    unique_ip = f"198.51.100.{uuid.uuid4().int % 200 + 10}"
    with TestClient(app, headers={"X-Forwarded-For": unique_ip}) as test_client:
        yield test_client
