"""Google verifies identity; application users and grants remain locally provisioned."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import GoogleLoginChallenge, User

LOGIN_DENIED = "Google account is not enabled for this workspace. Contact your administrator."


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def challenge_cookie(settings: Settings) -> str:
    return "__Host-securerag_google" if settings.secure_cookies else "securerag_google"


def require_google(settings: Settings) -> str:
    if not settings.google_client_id:
        raise HTTPException(503, "Google sign-in is not configured")
    return settings.google_client_id


def create_challenge(db: Session) -> tuple[str, str]:
    cookie, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.execute(delete(GoogleLoginChallenge).where(GoogleLoginChallenge.expires_at <= now))
    db.add(
        GoogleLoginChallenge(
            challenge_hash=digest(cookie),
            nonce_hash=digest(nonce),
            expires_at=now + timedelta(minutes=5),
        )
    )
    db.commit()
    return cookie, nonce


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    authoritative_email: bool
    nonce: str


def validate_claims(claims: dict) -> GoogleIdentity:
    subject, email, nonce = (claims.get(key) for key in ("sub", "email", "nonce"))
    if (
        not isinstance(subject, str)
        or not 1 <= len(subject) <= 255
        or not isinstance(email, str)
        or len(email) > 254
        or email.count("@") != 1
        or claims.get("email_verified") is not True
        or not isinstance(nonce, str)
        or not 32 <= len(nonce) <= 256
    ):
        raise HTTPException(401, "Invalid Google sign-in")
    email = email.strip().lower()
    hosted_domain = claims.get("hd")
    authoritative = email.endswith("@gmail.com") or (
        isinstance(hosted_domain, str) and bool(hosted_domain.strip())
    )
    return GoogleIdentity(subject, email, authoritative, nonce)


def verify_google_credential(credential: str, client_id: str) -> GoogleIdentity:
    # google-auth checks Google signature, audience, issuer, issued-at and expiry.
    # Bound certificate fetches; never log the credential or raw provider exception.
    transport = Request()

    def bounded_request(*args, **kwargs):
        kwargs["timeout"] = 10
        return transport(*args, **kwargs)

    try:
        claims = id_token.verify_oauth2_token(credential, bounded_request, audience=client_id)
    except TransportError:
        raise HTTPException(503, "Google verification is temporarily unavailable") from None
    except (ValueError, GoogleAuthError):
        raise HTTPException(401, "Invalid Google sign-in") from None
    return validate_claims(claims)


def sign_in_google(db: Session, identity: GoogleIdentity, cookie: str) -> User:
    # Atomic DELETE consumes a browser-bound nonce once, including concurrent replays.
    challenge = db.execute(
        delete(GoogleLoginChallenge)
        .where(
            GoogleLoginChallenge.challenge_hash == digest(cookie),
            GoogleLoginChallenge.nonce_hash == digest(identity.nonce),
            GoogleLoginChallenge.expires_at > datetime.now(UTC),
        )
        .returning(GoogleLoginChallenge.challenge_hash)
    ).scalar_one_or_none()
    if challenge is None:
        raise HTTPException(401, "Google sign-in expired. Please try again.")
    user = db.scalar(select(User).where(User.google_subject == identity.subject).with_for_update())
    if user is None and identity.authoritative_email:
        user = db.scalar(select(User).where(User.email == identity.email).with_for_update())
        if user is not None and user.google_subject not in (None, identity.subject):
            user = None
    if user is None or not user.is_active:
        db.commit()  # Consume a valid challenge even when the provisioned account is denied.
        raise HTTPException(403, LOGIN_DENIED)
    user.google_subject = identity.subject
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(403, LOGIN_DENIED) from None
    return user
