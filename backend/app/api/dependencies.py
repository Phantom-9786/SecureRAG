import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import Identity, decode_token
from app.db.session import get_db
from app.models import User
from app.services.authorization import lock_admin_changes, require_grant

Database = Annotated[Session, Depends(get_db)]


@dataclass
class CurrentSession:
    user: User
    identity: Identity


def current_session(request: Request, db: Database) -> CurrentSession:
    token = request.cookies.get(get_settings().access_cookie)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    identity = decode_token(token)
    user = db.get(User, identity.user_id)
    if user is None or not user.is_active or user.token_version != identity.token_version:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return CurrentSession(user, identity)


Authenticated = Annotated[CurrentSession, Depends(current_session)]


def require_origin(request: Request) -> None:
    # Require exact Origin even for login to prevent login-CSRF. CLI clients set it explicitly.
    if request.headers.get("origin") != get_settings().frontend_origin:
        raise HTTPException(status_code=403, detail="Untrusted request origin")


def require_csrf(request: Request, session: Authenticated) -> CurrentSession:
    require_origin(request)
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(get_settings().csrf_cookie, "")
    # CSRF value is bound to the signed JWT, not just a client-controlled cookie pair.
    if (
        not header
        or not cookie
        or not header.isascii()
        or not cookie.isascii()
        or not secrets.compare_digest(header, session.identity.csrf)
        or not secrets.compare_digest(cookie, session.identity.csrf)
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return session


CsrfSession = Annotated[CurrentSession, Depends(require_csrf)]


def require_permission(code: str):
    def dependency(db: Database, session: Authenticated) -> CurrentSession:
        require_grant(db, session.user, code)
        return session

    return dependency


def require_admin_write(code: str):
    def dependency(db: Database, session: CsrfSession) -> CurrentSession:
        lock_admin_changes(db)
        # Refresh after waiting for the lock: permissions/deactivation may have changed.
        db.refresh(session.user)
        if (
            not session.user.is_active
            or session.user.token_version != session.identity.token_version
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        require_grant(db, session.user, code)
        return session

    return dependency
