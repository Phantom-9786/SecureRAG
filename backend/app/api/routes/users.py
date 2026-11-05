import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import Database, require_admin_write, require_permission
from app.core.security import hash_password
from app.models import Role, User
from app.schemas.identity import GoogleUserCreate, UserCreate, UserOut, UserUpdate
from app.services.authorization import ensure_active_admin

router = APIRouter(prefix="/users", tags=["user administration"])


@router.get(
    "", response_model=list[UserOut], dependencies=[Depends(require_permission("users.manage"))]
)
def list_users(
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return list(
        db.scalars(select(User).order_by(User.created_at, User.id).offset(offset).limit(limit))
    )


@router.post(
    "",
    response_model=UserOut,
    status_code=201,
    dependencies=[Depends(require_admin_write("users.manage"))],
)
def create_user(body: UserCreate, db: Database):
    return save_user(db, body.name, str(body.email), body.role_id, body.password.get_secret_value())


@router.post(
    "/google",
    response_model=UserOut,
    status_code=201,
    dependencies=[Depends(require_admin_write("users.manage"))],
)
def create_google_user(body: GoogleUserCreate, db: Database):
    # No usable password is issued. Google must verify this email before its first binding.
    return save_user(db, body.name, str(body.email), body.role_id, secrets.token_urlsafe(64))


def save_user(db: Session, name: str, email: str, role_id: UUID, password: str) -> User:
    if db.get(Role, role_id) is None:
        raise HTTPException(status_code=404, detail="Role not found")
    user = User(
        name=name,
        email=email,
        role_id=role_id,
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered") from None
    db.refresh(user)
    return user


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_admin_write("users.manage"))],
)
def update_user(user_id: UUID, body: UserUpdate, db: Database):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role_id is not None:
        if db.get(Role, body.role_id) is None:
            raise HTTPException(status_code=404, detail="Role not found")
        user.role_id = body.role_id
    if body.is_active is not None and user.is_active != body.is_active:
        user.is_active = body.is_active
        user.token_version += 1  # Old sessions stay revoked even after reactivation.
    ensure_active_admin(db)
    db.commit()
    db.refresh(user)
    return user
