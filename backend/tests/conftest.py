"""Pytest fixtures and configuration."""
import pytest
from starlette.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """Synchronous test client for the FastAPI application."""
    with TestClient(app) as test_client:
        yield test_client
