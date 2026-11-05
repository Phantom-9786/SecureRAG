from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import (
    AUDIENCE,
    ISSUER,
    decode_token,
    hash_password,
    issue_token,
    set_auth_cookies,
    verify_password,
)
from app.db.session import get_db
from app.main import create_app
from app.schemas.identity import UserCreate, UserUpdate


@pytest.fixture
def settings():
    return Settings(_env_file=None, jwt_secret="test-only-signing-key-" * 3)


def test_passwords_are_salted_argon2id():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first.startswith("$argon2id$")
    assert first != second
    assert verify_password(first, "correct horse battery staple")
    assert not verify_password(first, "wrong password")
    assert not verify_password("not-a-password-hash", "anything")


def test_identity_token_has_no_permissions_and_rejects_tampering(settings):
    user_id = uuid4()
    token, csrf = issue_token(user_id, 7, settings)
    identity = decode_token(token, settings)
    assert (identity.user_id, identity.token_version, identity.csrf) == (user_id, 7, csrf)
    claims = jwt.decode(
        token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"], audience=AUDIENCE
    )
    assert "role" not in claims and "permissions" not in claims
    with pytest.raises(HTTPException) as error:
        decode_token(token + "tampered", settings)
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "override",
    [
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"aud": "another-api"},
        {"iss": "another-issuer"},
        {"tv": True},
        {"type": "refresh"},
        {"sub": "not-a-uuid"},
        {"csrf": "short"},
    ],
)
def test_invalid_claims_are_rejected(settings, override):
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid4()),
        "tv": 0,
        "csrf": "x" * 43,
        "type": "access",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=30),
        "iss": ISSUER,
        "aud": AUDIENCE,
    }
    claims.update(override)
    token = jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(HTTPException) as error:
        decode_token(token, settings)
    assert error.value.status_code == 401


def test_production_cookie_flags(settings):
    production = Settings(
        _env_file=None,
        app_env="production",
        frontend_origin="https://app.example.com",
        jwt_secret=settings.jwt_secret,
    )
    response = Response()
    set_auth_cookies(response, "signed-token", "csrf-value", production)
    access, csrf = response.headers.getlist("set-cookie")
    assert "__Host-securerag_access=" in access and "HttpOnly" in access
    assert "Secure" in access and "SameSite=lax" in access and "Path=/" in access
    assert "__Host-securerag_csrf=" in csrf and "HttpOnly" not in csrf
    assert "Domain=" not in access


def test_unsafe_production_configuration_fails():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", jwt_secret=None)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="short")


def test_inputs_forbid_self_assigned_privileges_and_empty_patches():
    with pytest.raises(ValidationError):
        UserCreate(
            name="User",
            email="user@example.com",
            password="long-enough-password",
            role_id=uuid4(),
            is_active=True,
        )
    for body in ({}, {"role_id": None}, {"is_active": "false"}):
        with pytest.raises(ValidationError):
            UserUpdate(**body)


def test_origin_auth_and_validation_boundaries():
    app = create_app()

    def unused_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = unused_db
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.get("/api/v1/users").status_code == 401
        assert client.post("/api/v1/auth/login", json={}).status_code == 403
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:3000"},
            json={"email": "bad-email", "password": "private-input"},
        )
        assert response.status_code == 422
        assert "private-input" not in response.text
        assert "bad-email" not in response.text
        assert response.headers["cache-control"] == "no-store"


def test_database_failures_do_not_echo_secrets():
    app = create_app()

    def unavailable_db():
        raise SQLAlchemyError("secret connection parameters")

    app.dependency_overrides[get_db] = unavailable_db
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 503
        assert "secret" not in response.text
