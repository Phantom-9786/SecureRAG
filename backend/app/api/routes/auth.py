from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, update

from app.api.dependencies import Authenticated, CsrfSession, Database, require_origin
from app.core.config import get_settings
from app.core.security import (
    clear_auth_cookies,
    dummy_password_hash,
    hash_password,
    issue_token,
    password_hasher,
    set_auth_cookies,
    signing_key,
    verify_password,
)
from app.models import User
from app.schemas.identity import LoginInput, Profile
from app.services.authorization import profile

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=Profile, dependencies=[Depends(require_origin)])
def login(body: LoginInput, db: Database, response: Response) -> Profile:
    settings = get_settings()
    signing_key(settings)  # Fail before accepting credentials when auth is unconfigured.
    user = db.scalar(select(User).where(User.email == str(body.email)))
    password = body.password.get_secret_value()
    valid = verify_password(user.password_hash if user else dummy_password_hash(), password)
    if not valid or user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
        db.refresh(user)
    token, csrf = issue_token(user.id, user.token_version, settings)
    result = profile(db, user, csrf)
    set_auth_cookies(response, token, csrf, settings)
    return result


@router.get("/me", response_model=Profile)
def me(db: Database, session: Authenticated, response: Response) -> Profile:
    response.headers["Cache-Control"] = "no-store"
    return profile(db, session.user, session.identity.csrf)


@router.post("/logout", status_code=204)
def logout(db: Database, session: CsrfSession, response: Response) -> None:
    # Atomic increment avoids lost updates from simultaneous logouts.
    db.execute(
        update(User)
        .where(User.id == session.user.id)
        .values(
            token_version=User.token_version + 1,
        )
    )
    db.commit()
    clear_auth_cookies(response, get_settings())
