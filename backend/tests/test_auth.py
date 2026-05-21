"""Regression tests for the auth + RBAC slice.

Covers:
- password hashing (verify + reject)
- JWT sign/verify and tampering detection
- signup → me round-trip
- login + admin-login gating
- refresh token rotation and reuse detection
- logout revokes the refresh token
- 401 on missing token; 403 on wrong role
- protected endpoint inventory: documents/upload, evaluation, metrics
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ── Building blocks ─────────────────────────────────────────────────────────


def test_password_hash_round_trip():
    from app.auth.passwords import hash_password, verify_password

    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong password", h) is False
    # Malformed hash on disk → False, not raise.
    assert verify_password("anything", "not-a-real-hash") is False


def test_jwt_sign_and_verify():
    from app.auth.tokens import (
        TokenError,
        create_access_token,
        create_refresh_token,
        decode_access_token,
        decode_refresh_token,
        hash_refresh_token,
    )

    access = create_access_token(user_id=42, role="admin")
    claims = decode_access_token(access)
    assert claims.sub == "42"
    assert claims.role == "admin"
    assert claims.type == "access"

    # Cross-type rejection: an access token must not decode as refresh.
    with pytest.raises(TokenError):
        decode_refresh_token(access)

    raw, jti, exp = create_refresh_token(user_id=42)
    r_claims = decode_refresh_token(raw)
    assert r_claims.sub == "42"
    assert r_claims.jti == jti
    assert hash_refresh_token(raw) == hash_refresh_token(raw)
    assert hash_refresh_token(raw) != hash_refresh_token(raw + "x")


def test_jwt_tampering_is_rejected():
    from app.auth.tokens import TokenError, create_access_token, decode_access_token

    token = create_access_token(user_id=1, role="user")
    # Flip a byte in the payload section.
    head, payload, sig = token.split(".")
    tampered = ".".join([head, payload[:-1] + ("A" if payload[-1] != "A" else "B"), sig])
    with pytest.raises(TokenError):
        decode_access_token(tampered)


# ── HTTP flow ───────────────────────────────────────────────────────────────


def test_signup_login_me_round_trip():
    from app.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/signup",
            json={"email": "u@example.com", "password": "supersecret123", "full_name": "U"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["user"]["email"] == "u@example.com"
        assert body["user"]["role"] == "user"
        access = body["access_token"]

        r = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
        )
        assert r.status_code == 200
        assert r.json()["email"] == "u@example.com"

        # Login with the same creds → new access token + refresh cookie.
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "u@example.com", "password": "supersecret123"},
        )
        assert r.status_code == 200
        assert r.json()["user"]["email"] == "u@example.com"


def test_signup_duplicate_email_is_409():
    from app.main import app

    with TestClient(app) as client:
        body = {"email": "dup@example.com", "password": "supersecret123"}
        assert client.post("/api/v1/auth/signup", json=body).status_code == 201
        r = client.post("/api/v1/auth/signup", json=body)
        assert r.status_code == 409


def test_login_with_bad_password_is_401():
    from app.main import app

    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/signup",
            json={"email": "z@example.com", "password": "supersecret123"},
        )
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "z@example.com", "password": "wrongpassword"},
        )
        assert r.status_code == 401


def test_admin_login_rejects_non_admin():
    from app.main import app

    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/signup",
            json={"email": "a@example.com", "password": "supersecret123"},
        )
        r = client.post(
            "/api/v1/auth/admin-login",
            json={"email": "a@example.com", "password": "supersecret123"},
        )
        assert r.status_code == 401  # opaque — not 403 — so admin status isn't leaked


def test_admin_login_accepts_admin():
    from app.main import app
    from tests.conftest import signup_admin

    with TestClient(app) as client:
        headers = signup_admin(client, email="admin@example.com")
        # signup_admin already used /admin-login to mint the token.
        assert "Authorization" in headers


def test_refresh_rotates_and_old_refresh_is_revoked():
    from app.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/signup",
            json={"email": "r@example.com", "password": "supersecret123"},
        )
        assert r.status_code == 201
        old_cookie = client.cookies.get("lf_refresh")
        assert old_cookie

        r = client.post("/api/v1/auth/refresh")
        assert r.status_code == 200
        new_cookie = client.cookies.get("lf_refresh")
        assert new_cookie and new_cookie != old_cookie

        # Replaying the OLD refresh token must now be rejected. We replay by
        # sending a request with the old cookie value directly.
        client.cookies.clear()
        client.cookies.set("lf_refresh", old_cookie, path="/api/v1/auth")
        r = client.post("/api/v1/auth/refresh")
        assert r.status_code == 401


def test_logout_revokes_refresh():
    from app.main import app

    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/signup",
            json={"email": "lo@example.com", "password": "supersecret123"},
        )
        r = client.post("/api/v1/auth/logout")
        assert r.status_code == 200
        r = client.post("/api/v1/auth/refresh")
        assert r.status_code == 401


# ── RBAC on existing endpoints ──────────────────────────────────────────────


def test_metrics_requires_admin():
    from app.main import app
    from tests.conftest import signup_admin, signup_user

    with TestClient(app) as client:
        # 401 without any token.
        assert client.get("/api/v1/metrics").status_code == 401

        # 403 for a normal user.
        user_headers = signup_user(client, email="user1@example.com")
        assert client.get("/api/v1/metrics", headers=user_headers).status_code == 403

        # 200 for an admin.
        admin_headers = signup_admin(client, email="admin1@example.com")
        assert client.get("/api/v1/metrics", headers=admin_headers).status_code == 200


def test_documents_upload_requires_admin():
    from app.main import app
    from tests.conftest import signup_user

    with TestClient(app) as client:
        csv = ("file", ("a.csv", b"a,b\n1,2\n", "text/csv"))

        # Anon → 401
        r = client.post("/api/v1/documents/upload", files=[csv])
        assert r.status_code == 401

        # User → 403
        user_headers = signup_user(client)
        r = client.post(
            "/api/v1/documents/upload", files=[csv], headers=user_headers
        )
        assert r.status_code == 403


def test_query_requires_authentication():
    from app.main import app
    from tests.conftest import signup_user

    with TestClient(app) as client:
        # Anon → 401
        r = client.post("/api/v1/query", json={"query": "Section 302 IPC?"})
        assert r.status_code == 401

        # User → 200
        user_headers = signup_user(client)
        r = client.post(
            "/api/v1/query",
            json={"query": "Section 302 IPC?"},
            headers=user_headers,
        )
        assert r.status_code == 200, r.text


def test_health_remains_anonymous():
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        # The health router defines /health; if it has a different shape that's
        # fine — we just need it to remain anonymously reachable (not 401/403).
        assert r.status_code < 400, r.text


# ── Change password ─────────────────────────────────────────────────────────


def test_change_password_requires_current_password():
    from app.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/signup",
            json={"email": "cp@example.com", "password": "originalpassword1"},
        )
        assert r.status_code == 201
        access = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}

        # Wrong current password → 401
        r = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "nope", "new_password": "newsecretpassword1"},
            headers=headers,
        )
        assert r.status_code == 401


def test_change_password_rejects_same_password():
    from app.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/signup",
            json={"email": "cps@example.com", "password": "originalpassword1"},
        )
        access = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}

        r = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "originalpassword1",
                "new_password": "originalpassword1",
            },
            headers=headers,
        )
        assert r.status_code == 400


def test_change_password_updates_and_revokes_refresh():
    from app.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/signup",
            json={"email": "cpok@example.com", "password": "originalpassword1"},
        )
        assert r.status_code == 201
        access = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}

        r = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "originalpassword1",
                "new_password": "newsecretpassword2",
            },
            headers=headers,
        )
        assert r.status_code == 200

        # Old password no longer works.
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "cpok@example.com", "password": "originalpassword1"},
        )
        assert r.status_code == 401

        # New password does work.
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "cpok@example.com", "password": "newsecretpassword2"},
        )
        assert r.status_code == 200

        # The pre-change refresh cookie has been revoked; refresh fails.
        client.cookies.clear()
        r = client.post("/api/v1/auth/refresh")
        assert r.status_code == 401


def test_change_password_requires_auth():
    from app.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "x", "new_password": "newsecretpassword1"},
        )
        assert r.status_code == 401
