"""Pytest fixtures and configuration."""
import uuid
import pytest
from starlette.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """Synchronous test client for the FastAPI application with isolated client IP."""
    # Assign a unique client IP per test to avoid rate limiter counter pollution across tests
    unique_ip = f"198.51.100.{uuid.uuid4().int % 200 + 10}"
    with TestClient(app, headers={"X-Forwarded-For": unique_ip}) as test_client:
        yield test_client

