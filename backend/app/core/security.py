"""Passwords and signed identity tokens; permissions deliberately do not live in JWTs."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Response

from app.core.config import Settings, get_settings

password_hasher = PasswordHasher()  # Argon2id: salted, memory-hard password hashing.
ISSUER = "securerag"
AUDIENCE = "securerag-api"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def dummy_password_hash() -> str:
    # Missing users still pay password-verification cost; no known account is required.
    return hash_password(secrets.token_urlsafe(32))


def signing_key(settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    return settings.jwt_secret.get_secret_value()


@dataclass(frozen=True)
class Identity:
    user_id: UUID
    token_version: int
    csrf: str


def issue_token(user_id: UUID, token_version: int, settings: Settings) -> tuple[str, str]:
    now = datetime.now(UTC)
    csrf = secrets.token_urlsafe(32)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "tv": token_version,
            "csrf": csrf,
            "type": "access",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=settings.jwt_access_token_minutes),
            "iss": ISSUER,
            "aud": AUDIENCE,
        },
        signing_key(settings),
        algorithm="HS256",
    )
    return token, csrf


def decode_token(token: str, settings: Settings | None = None) -> Identity:
    settings = settings or get_settings()
    key = signing_key(settings)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": ["sub", "tv", "csrf", "type", "iat", "nbf", "exp", "iss", "aud"]},
        )
        if (
            claims["type"] != "access"
            or type(claims["tv"]) is not int
            or claims["tv"] < 0
            or not isinstance(claims["csrf"], str)
            or len(claims["csrf"]) < 32
        ):
            raise ValueError("Invalid claims")
        return Identity(UUID(claims["sub"]), claims["tv"], claims["csrf"])
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid or expired session") from None


def set_auth_cookies(response: Response, token: str, csrf: str, settings: Settings) -> None:
    options = {
        "secure": settings.secure_cookies,
        "samesite": "lax",
        "path": "/",
        "max_age": settings.jwt_access_token_minutes * 60,
    }
    response.set_cookie(settings.access_cookie, token, httponly=True, **options)
    response.set_cookie(settings.csrf_cookie, csrf, httponly=False, **options)
    response.headers["Cache-Control"] = "no-store"


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.access_cookie,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        settings.csrf_cookie,
        path="/",
        secure=settings.secure_cookies,
        httponly=False,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
