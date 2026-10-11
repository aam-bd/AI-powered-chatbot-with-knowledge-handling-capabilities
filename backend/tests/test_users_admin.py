"""Acceptance and unit tests for Prompt 7d: Admin user management.

Covers:
1. test_list_users_admin_only: Admin can list users; normal user gets 403; unauthenticated gets 401.
2. test_admin_cannot_demote_themselves: 400 SELF_DEMOTION_FORBIDDEN on self-demotion.
3. test_admin_cannot_deactivate_themselves: 400 SELF_DEACTIVATION_FORBIDDEN on self-deactivation.
4. test_last_active_admin_protected_from_demotion_and_deactivation: 400 LAST_ADMIN_PROTECTED.
5. test_role_change_lifecycle: Promote user to admin; demote second admin back to user.
6. test_activate_and_deactivate_user: Toggle active state of normal user.
7. test_deactivated_user_cannot_login: Returns 403 USER_INACTIVE on login attempt.
8. test_deactivated_user_cannot_refresh: Returns 401 on refresh attempt.
9. test_deactivated_user_valid_access_token_rejected_immediately: Still-valid access token returns 403 on next request.
10. test_demoted_admin_valid_access_token_immediately_blocked: Stale admin token rejected with 403 on admin routes.
11. test_update_user_validation_and_not_found: 404 for unknown UUID, 422 for invalid role or empty payload.
12. test_admin_user_modification_logged_without_secrets: Audit logs record email and role without secrets.
"""
import uuid
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.sql_models import User
from app.core.security import hash_password


def _create_user(client: TestClient, role: str = "user", is_active: bool = True) -> dict:
    """Helper to create a user and return login headers and metadata."""
    uid = uuid.uuid4().hex[:8]
    email = f"{role}_{uid}@example.com"
    password = "TestPassword123!"
    ip = f"198.51.100.{uuid.uuid4().int % 200 + 10}"

    # Register via standard endpoint
    reg_resp = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["id"]

    # If role or active state needs override, update directly in DB
    if role != "user" or not is_active:
        import asyncio
        async def _update_db():
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
                db_user = res.scalar_one()
                db_user.role = role
                db_user.is_active = is_active
                await db.commit()
        asyncio.run(_update_db())

    # Login to obtain tokens if active
    token = None
    refresh_token = None
    if is_active:
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            headers={"X-Forwarded-For": ip},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        refresh_token = login_resp.json()["refresh_token"]

    return {
        "id": user_id,
        "email": email,
        "password": password,
        "role": role,
        "is_active": is_active,
        "token": token,
        "refresh_token": refresh_token,
        "headers": {"Authorization": f"Bearer {token}"} if token else {},
    }


def test_list_users_admin_only(client: TestClient):
    """GET /api/v1/users is restricted to admins; normal user gets 403; unauth gets 401."""
    admin = _create_user(client, role="admin")
    normal_user = _create_user(client, role="user")

    # 1. Unauthenticated gets 401
    unauth_resp = client.get("/api/v1/users")
    assert unauth_resp.status_code == 401

    # 2. Normal user gets 403
    forbidden_resp = client.get("/api/v1/users", headers=normal_user["headers"])
    assert forbidden_resp.status_code == 403
    assert forbidden_resp.json()["code"] == "FORBIDDEN"

    # 3. Admin gets 200 and list of users
    admin_resp = client.get("/api/v1/users", headers=admin["headers"])
    assert admin_resp.status_code == 200
    user_list = admin_resp.json()
    assert isinstance(user_list, list)
    assert any(u["id"] == admin["id"] for u in user_list)
    assert any(u["id"] == normal_user["id"] for u in user_list)


def test_admin_cannot_demote_themselves(client: TestClient):
    """An admin attempting to change their own role to 'user' receives 400 SELF_DEMOTION_FORBIDDEN."""
    admin = _create_user(client, role="admin")

    resp = client.patch(
        f"/api/v1/users/{admin['id']}",
        json={"role": "user"},
        headers=admin["headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SELF_DEMOTION_FORBIDDEN"


def test_admin_cannot_deactivate_themselves(client: TestClient):
    """An admin attempting to deactivate their own account receives 400 SELF_DEACTIVATION_FORBIDDEN."""
    admin = _create_user(client, role="admin")

    resp = client.patch(
        f"/api/v1/users/{admin['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SELF_DEACTIVATION_FORBIDDEN"


def test_last_active_admin_protected_from_demotion_and_deactivation(client: TestClient, monkeypatch):
    """The last active admin cannot be demoted or deactivated (returns 400 LAST_ADMIN_PROTECTED)."""
    admin_a = _create_user(client, role="admin")
    admin_b = _create_user(client, role="admin")

    # 1. While multiple active admins exist, demoting admin_b succeeds
    resp_demote = client.patch(
        f"/api/v1/users/{admin_b['id']}",
        json={"role": "user"},
        headers=admin_a["headers"],
    )
    assert resp_demote.status_code == 200
    assert resp_demote.json()["role"] == "user"

    # Promote admin_b back
    client.patch(
        f"/api/v1/users/{admin_b['id']}",
        json={"role": "admin"},
        headers=admin_a["headers"],
    )

    # 2. Simulate concurrent race condition where active_admins query returns <= 1 admin
    from sqlalchemy.ext.asyncio import AsyncSession
    orig_execute = AsyncSession.execute

    class MockScalarResult:
        def __init__(self, items):
            self._items = items
        def scalars(self):
            return self
        def all(self):
            return self._items
        def scalar_one_or_none(self):
            return self._items[0] if self._items else None

    async def mock_execute(self, statement, *args, **kwargs):
        stmt_str = str(statement)
        # Intercept the active admins lock query (which selects active admins with FOR UPDATE)
        if "is_active" in stmt_str and "role" in stmt_str and "FOR UPDATE" in stmt_str:
            return MockScalarResult(["mock_single_active_admin"])
        return await orig_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", mock_execute)

    # Attempt demoting admin_b -> triggers LAST_ADMIN_PROTECTED
    resp = client.patch(
        f"/api/v1/users/{admin_b['id']}",
        json={"role": "user"},
        headers=admin_a["headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "LAST_ADMIN_PROTECTED"

    # Attempt deactivating admin_b -> also triggers LAST_ADMIN_PROTECTED
    resp_deact = client.patch(
        f"/api/v1/users/{admin_b['id']}",
        json={"is_active": False},
        headers=admin_a["headers"],
    )
    assert resp_deact.status_code == 400
    assert resp_deact.json()["code"] == "LAST_ADMIN_PROTECTED"


def test_role_change_lifecycle(client: TestClient):
    """Admin promotes normal user to admin, then demotes back to user."""
    admin = _create_user(client, role="admin")
    user = _create_user(client, role="user")

    # 1. Promote user to admin
    resp1 = client.patch(
        f"/api/v1/users/{user['id']}",
        json={"role": "admin"},
        headers=admin["headers"],
    )
    assert resp1.status_code == 200
    assert resp1.json()["role"] == "admin"

    # Verify user can now access admin endpoint
    resp_check = client.get("/api/v1/users", headers=user["headers"])
    assert resp_check.status_code == 200

    # 2. Demote user back to user
    resp2 = client.patch(
        f"/api/v1/users/{user['id']}",
        json={"role": "user"},
        headers=admin["headers"],
    )
    assert resp2.status_code == 200
    assert resp2.json()["role"] == "user"

    # Verify user is immediately blocked from admin endpoint
    resp_check2 = client.get("/api/v1/users", headers=user["headers"])
    assert resp_check2.status_code == 403


def test_activate_and_deactivate_user(client: TestClient):
    """Admin can deactivate and reactivate a standard user."""
    admin = _create_user(client, role="admin")
    user = _create_user(client, role="user")

    # 1. Deactivate user
    resp_deact = client.patch(
        f"/api/v1/users/{user['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert resp_deact.status_code == 200
    assert resp_deact.json()["is_active"] is False

    # 2. Reactivate user
    resp_act = client.patch(
        f"/api/v1/users/{user['id']}",
        json={"is_active": True},
        headers=admin["headers"],
    )
    assert resp_act.status_code == 200
    assert resp_act.json()["is_active"] is True


def test_deactivated_user_cannot_login(client: TestClient):
    """A deactivated user receives 403 USER_INACTIVE on login attempt."""
    admin = _create_user(client, role="admin")
    user = _create_user(client, role="user")

    # Admin deactivates user
    client.patch(
        f"/api/v1/users/{user['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )

    # User attempts login
    ip = f"198.51.100.{uuid.uuid4().int % 200 + 10}"
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": user["password"]},
        headers={"X-Forwarded-For": ip},
    )
    assert login_resp.status_code == 403
    assert login_resp.json()["code"] == "USER_INACTIVE"


def test_deactivated_user_cannot_refresh(client: TestClient):
    """A deactivated user cannot refresh tokens; returns 401."""
    admin = _create_user(client, role="admin")
    user = _create_user(client, role="user")
    refresh_token = user["refresh_token"]

    # Admin deactivates user
    client.patch(
        f"/api/v1/users/{user['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )

    # Attempt to refresh token
    ref_resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert ref_resp.status_code == 401


def test_deactivated_user_valid_access_token_rejected_immediately(client: TestClient):
    """A deactivated user's still-valid access token gets 401 or 403 on the next request."""
    admin = _create_user(client, role="admin")
    user = _create_user(client, role="user")

    # Verify access token works initially
    me_resp = client.get("/api/v1/auth/me", headers=user["headers"])
    assert me_resp.status_code == 200

    # Admin deactivates user
    client.patch(
        f"/api/v1/users/{user['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )

    # User's still-valid access token is used on the next request -> 401 or 403
    next_resp = client.get("/api/v1/auth/me", headers=user["headers"])
    assert next_resp.status_code in (401, 403)
    assert next_resp.json()["code"] in ("USER_INACTIVE", "USER_NOT_FOUND")


def test_demoted_admin_valid_access_token_immediately_blocked(client: TestClient):
    """Demoted admin's still-valid access token is immediately blocked from admin routes."""
    super_admin = _create_user(client, role="admin")
    test_user = _create_user(client, role="user")

    # Promote to admin
    client.patch(f"/api/v1/users/{test_user['id']}", json={"role": "admin"}, headers=super_admin["headers"])

    # Test user logs in and obtains access token with role='admin'
    ip = f"198.51.100.{uuid.uuid4().int % 200 + 10}"
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
        headers={"X-Forwarded-For": ip},
    )
    admin_token = login_resp.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Verify admin route works
    resp_init = client.get("/api/v1/users", headers=admin_headers)
    assert resp_init.status_code == 200

    # Super admin demotes test user back to user
    client.patch(f"/api/v1/users/{test_user['id']}", json={"role": "user"}, headers=super_admin["headers"])

    # Demoted admin makes immediate request to admin route using same access token
    # get_current_user must read role from PostgreSQL and reject with 403
    resp_blocked = client.get("/api/v1/users", headers=admin_headers)
    assert resp_blocked.status_code == 403
    assert resp_blocked.json()["code"] == "FORBIDDEN"


def test_update_user_validation_and_not_found(client: TestClient):
    """PATCH /users/{id} returns 404 for non-existent users and 422 for invalid payloads."""
    admin = _create_user(client, role="admin")
    fake_id = uuid.uuid4()

    # 1. User not found -> 404
    resp_404 = client.patch(
        f"/api/v1/users/{fake_id}",
        json={"role": "admin"},
        headers=admin["headers"],
    )
    assert resp_404.status_code == 404
    assert resp_404.json()["code"] == "USER_NOT_FOUND"

    # 2. Invalid role string -> 422
    resp_bad_role = client.patch(
        f"/api/v1/users/{fake_id}",
        json={"role": "superadmin"},
        headers=admin["headers"],
    )
    assert resp_bad_role.status_code == 422

    # 3. Empty payload -> 422 (must provide role or is_active)
    resp_empty = client.patch(
        f"/api/v1/users/{fake_id}",
        json={},
        headers=admin["headers"],
    )
    assert resp_empty.status_code == 422


def test_admin_user_modification_logged_without_secrets(client: TestClient):
    """Administrative user modifications are logged with user ID/email but no passwords or tokens."""
    from pathlib import Path

    admin = _create_user(client, role="admin")
    target = _create_user(client, role="user")

    client.patch(
        f"/api/v1/users/{target['id']}",
        json={"role": "admin"},
        headers=admin["headers"],
    )

    # Check Loguru logs/app.log file
    log_file = Path("logs/app.log")
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "modified user" in content
    assert target["email"] in content
    assert admin["email"] in content
    assert "TestPassword123" not in content
    assert admin["token"] not in content
