"""Tests for health endpoint, Request-ID middleware, and API docs."""
import json
from pathlib import Path
from starlette.testclient import TestClient


def test_health_endpoint_structure(client: TestClient):
    """Verify GET /api/v1/health returns valid schema without requiring LLM or throwing."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()

    assert "status" in data
    assert data["status"] in ("healthy", "degraded")
    assert "postgres" in data
    assert "redis" in data
    assert "qdrant" in data
    assert "llm_configured" in data
    assert isinstance(data["llm_configured"], bool)
    assert data["version"] == "1.0.0"


def test_request_id_middleware_and_header(client: TestClient):
    """Verify X-Request-ID header generation and propagation."""
    # 1. Without header -> auto-generated
    resp1 = client.get("/api/v1/health")
    assert resp1.status_code == 200
    assert "X-Request-ID" in resp1.headers
    req_id1 = resp1.headers["X-Request-ID"]
    assert len(req_id1) > 0

    # 2. With header -> propagated
    custom_id = "test-req-id-12345"
    resp2 = client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Request-ID") == custom_id


def test_log_file_contains_json_with_request_id(client: TestClient):
    """Verify logs/app.log exists and includes structured JSON with request_id."""
    custom_id = "probe-unique-uuid-99999"
    resp = client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 200

    log_path = Path("logs/app.log")
    assert log_path.exists(), "logs/app.log must be created"

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) > 0

    found = False
    for line in lines:
        try:
            entry = json.loads(line)
            if entry.get("request_id") == custom_id:
                found = True
                assert "timestamp" in entry
                assert "level" in entry
                assert "message" in entry
                break
        except json.JSONDecodeError:
            continue

    assert found, f"Expected log line with request_id '{custom_id}' not found in logs/app.log"


def test_api_documentation_loads(client: TestClient):
    """Verify /docs and /redoc OpenAPI documentation endpoints load successfully."""
    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200
    assert "swagger" in docs_resp.text.lower() or "openapi" in docs_resp.text.lower()

    redoc_resp = client.get("/redoc")
    assert redoc_resp.status_code == 200
    assert "redoc" in redoc_resp.text.lower()
