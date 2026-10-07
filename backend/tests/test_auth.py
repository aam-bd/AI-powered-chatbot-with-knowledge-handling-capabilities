"""Acceptance tests for database models, migrations, auth, and rate limiting (Phase 1)."""
import uuid
from datetime import timedelta
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from app.db.session import AsyncSessionLocal
from app.models.sql_models import User, Document
from app.core.security import create_access_token, create_refresh_token, hash_password
from scripts.seed_admin import seed_admin


def test_register_cannot_create_admin(client: TestClient):
    """Verify that user registration ALWAYS assigns role='user', even if 'admin' is submitted."""
    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "email": unique_email,
        "password": "Password123!",
        "role": "admin",  # Malicious attempt to self-grant admin
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == unique_email
    assert data["role"] == "user"  # Must strictly be 'user'


def test_duplicate_registration_rejected(client: TestClient):
    """Verify duplicate email registration returns 409 Conflict with standard error schema."""
    unique_email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
    payload = {"email": unique_email, "password": "Password123!"}
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 409
    data = res2.json()
    assert data["code"] == "EMAIL_ALREADY_REGISTERED"
    assert "already exists" in data["detail"]


def test_login_success_and_invalid_password(client: TestClient):
    """Verify login issuing access & refresh tokens, and 401 on wrong password."""
    unique_email = f"auth_{uuid.uuid4().hex[:8]}@example.com"
    ip = f"10.1.{uuid.uuid4().hex[:4]}.1"
    password = "CorrectPassword123!"
    client.post("/api/v1/auth/register", json={"email": unique_email, "password": password})

    # 1. Correct credentials
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0

    # 2. Wrong credentials
    wrong_resp = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "WrongPassword!"},
        headers={"X-Forwarded-For": ip},
    )
    assert wrong_resp.status_code == 401
    assert wrong_resp.json()["code"] == "INVALID_CREDENTIALS"


def test_refresh_token_lifecycle(client: TestClient):
    """Verify refresh endpoint gives new access token, but rejects access token used as refresh."""
    unique_email = f"refresh_{uuid.uuid4().hex[:8]}@example.com"
    ip = f"10.2.{uuid.uuid4().hex[:4]}.1"
    password = "Password123!"
    client.post("/api/v1/auth/register", json={"email": unique_email, "password": password})
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    tokens = login_resp.json()

    # Valid refresh token
    ref_resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ref_resp.status_code == 200
    new_tokens = ref_resp.json()
    assert "access_token" in new_tokens

    # Attempt to use access token as refresh token -> rejected
    bad_ref_resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert bad_ref_resp.status_code == 401
    assert bad_ref_resp.json()["code"] == "INVALID_TOKEN_TYPE"


def test_expired_and_invalid_tokens_rejected(client: TestClient):
    """Verify that expired and malformed tokens return 401."""
    # 1. Malformed token
    bad_resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert bad_resp.status_code == 401
    assert bad_resp.json()["code"] == "INVALID_TOKEN"

    # 2. Expired token
    expired_token = create_access_token(
        user_id=str(uuid.uuid4()),
        role="user",
        expires_delta=timedelta(seconds=-30),
    )
    exp_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert exp_resp.status_code == 401
    assert exp_resp.json()["code"] == "TOKEN_EXPIRED"


def test_role_authorization_admin_vs_normal_user(client: TestClient):
    """Verify normal user gets 403 on admin route, while admin gets 200."""
    user_email = f"user_norm_{uuid.uuid4().hex[:8]}@example.com"
    admin_email = f"admin_role_{uuid.uuid4().hex[:8]}@example.com"
    ip = f"10.3.{uuid.uuid4().hex[:4]}.1"
    password = "Password123!"

    # Create normal user
    client.post("/api/v1/auth/register", json={"email": user_email, "password": password})
    user_login = client.post(
        "/api/v1/auth/login",
        json={"email": user_email, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    assert user_login.status_code == 200
    user_token = user_login.json()["access_token"]

    # Seed admin user
    import asyncio
    asyncio.run(seed_admin(email=admin_email, password=password))
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]

    # 1. Normal user tries to access admin-only endpoint -> 403 Forbidden
    resp_user = client.get("/api/v1/auth/admin-only", headers={"Authorization": f"Bearer {user_token}"})
    assert resp_user.status_code == 403
    assert resp_user.json()["code"] == "FORBIDDEN"

    # 2. Admin user accesses admin-only endpoint -> 200 OK
    resp_admin = client.get("/api/v1/auth/admin-only", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_admin.status_code == 200
    assert resp_admin.json()["role"] == "admin"


def test_login_rate_limiting(client: TestClient):
    """Verify that exceeding 5 login attempts per minute triggers HTTP 429."""
    dummy_email = "ratelimit_test@example.com"
    triggered = False

    # Send 10 consecutive login attempts
    for _ in range(10):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": dummy_email, "password": "wrong_password"},
            headers={"X-Forwarded-For": "198.51.100.1"},  # Custom IP
        )
        if resp.status_code == 429:
            triggered = True
            assert resp.json()["code"] == "RATE_LIMIT_EXCEEDED"
            assert "Retry-After" in resp.headers
            break

    assert triggered, "Expected rate limit (429) was not triggered within 10 requests"


def test_partial_unique_index_on_document_sha256():
    """Verify unique sha256 among non-deleted documents; allowed after soft-delete."""
    import asyncio

    async def _test_index():
        test_sha = f"sha256_{uuid.uuid4().hex}"
        async with AsyncSessionLocal() as session:
            # 1. Insert first document
            doc1 = Document(
                name="Doc 1",
                source_type="pdf",
                source_uri="/tmp/doc1.pdf",
                sha256=test_sha,
                size_bytes=1000,
                status="active",
            )
            session.add(doc1)
            await session.commit()

            # 2. Try inserting second document with same sha256 and active status -> fails
            doc2 = Document(
                name="Doc 2",
                source_type="pdf",
                source_uri="/tmp/doc2.pdf",
                sha256=test_sha,
                size_bytes=1000,
                status="pending",
            )
            session.add(doc2)
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            # 3. Soft-delete the first document (status = 'deleting')
            doc1.status = "deleting"
            session.add(doc1)
            await session.commit()

            # 4. Now inserting a new document with the same sha256 must succeed
            doc3 = Document(
                name="Doc 3",
                source_type="pdf",
                source_uri="/tmp/doc3.pdf",
                sha256=test_sha,
                size_bytes=1000,
                status="active",
            )
            session.add(doc3)
            await session.commit()
            assert doc3.id is not None

    asyncio.run(_test_index())


def test_register_weak_password_rejected(client: TestClient):
    """Verify registration rejects passwords shorter than PASSWORD_MIN_LENGTH (10 chars)."""
    unique_email = f"shortpass_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "email": unique_email,
        "password": "Short1!",  # 7 chars < 10
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "code" in data or "detail" in data


def test_logout_revokes_refresh_token(client: TestClient):
    """Verify that POST /auth/logout marks refresh token as revoked, preventing subsequent /refresh."""
    unique_email = f"logout_{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePassword123!"
    reg_resp = client.post("/api/v1/auth/register", json={"email": unique_email, "password": password})
    assert reg_resp.status_code == 201

    login_resp = client.post("/api/v1/auth/login", json={"email": unique_email, "password": password})
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    refresh_token = tokens["refresh_token"]

    # 1. First verify refresh token works before logout
    ref_resp1 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert ref_resp1.status_code == 200

    # 2. Call logout with refresh token
    logout_resp = client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_resp.status_code == 200
    assert "Logged out successfully" in logout_resp.json()["detail"]

    # 3. Subsequent refresh with revoked token MUST return 401
    ref_resp2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert ref_resp2.status_code == 401
    data = ref_resp2.json()
    assert data["code"] == "TOKEN_REVOKED"


def test_change_password_invalidates_old_password(client: TestClient):
    """Verify changing password requires current password, rejects weak passwords, and invalidates old password."""
    unique_email = f"changepw_{uuid.uuid4().hex[:8]}@example.com"
    old_password = "OldPassword123!"
    new_password = "NewPassword123!"

    # Register & Login
    client.post("/api/v1/auth/register", json={"email": unique_email, "password": old_password})
    login_resp = client.post("/api/v1/auth/login", json={"email": unique_email, "password": old_password})
    access_token = login_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    # 1. Invalid current password -> 400
    bad_current = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "WrongPassword123!", "new_password": new_password},
        headers=auth_headers,
    )
    assert bad_current.status_code == 400
    assert bad_current.json()["code"] == "INVALID_CURRENT_PASSWORD"

    # 2. Weak new password (< 10 chars) -> 422
    weak_new = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": old_password, "new_password": "Short1!"},
        headers=auth_headers,
    )
    assert weak_new.status_code == 422

    # 3. Successful password change -> 200
    success_change = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": old_password, "new_password": new_password},
        headers=auth_headers,
    )
    assert success_change.status_code == 200
    assert "Password changed successfully" in success_change.json()["detail"]

    # 4. Old password must fail login
    old_login = client.post("/api/v1/auth/login", json={"email": unique_email, "password": old_password})
    assert old_login.status_code == 401

    # 5. New password must succeed
    new_login = client.post("/api/v1/auth/login", json={"email": unique_email, "password": new_password})
    assert new_login.status_code == 200
    assert "access_token" in new_login.json()

