"""Central database-driven RBAC and the last-administrator invariant."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Category, Permission, Role, RoleCategoryAccess, RolePermission, User
from app.schemas.identity import NamedResource, Profile, RoleOut, UserOut

# Every access-changing application transaction and bootstrap takes this same lock.
# A transaction lock avoids two simultaneous demotions both seeing another admin.
ADMIN_CHANGE_LOCK = 724191802
ADMIN_PERMISSIONS = frozenset({"users.manage", "roles.manage", "documents.manage"})


def permission_codes(db: Session, role_id: UUID) -> list[str]:
    return list(
        db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.code)
        )
    )


def allowed_categories(db: Session, role_id: UUID) -> list[Category]:
    return list(
        db.scalars(
            select(Category)
            .join(RoleCategoryAccess, RoleCategoryAccess.category_id == Category.id)
            .where(RoleCategoryAccess.role_id == role_id)
            .order_by(Category.name)
        )
    )


def require_grant(db: Session, user: User, code: str) -> None:
    if code not in permission_codes(db, user.role_id):
        raise HTTPException(status_code=403, detail="Permission denied")


def lock_admin_changes(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_CHANGE_LOCK})


def ensure_active_admin(db: Session) -> None:
    db.flush()
    admin_role_ids = (
        select(RolePermission.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(Permission.code.in_(ADMIN_PERMISSIONS))
        .group_by(RolePermission.role_id)
        .having(func.count(Permission.id) == len(ADMIN_PERMISSIONS))
    )
    exists = db.scalar(
        select(User.id)
        .where(
            User.is_active.is_(True),
            User.role_id.in_(admin_role_ids),
        )
        .limit(1)
    )
    if exists is None:
        raise HTTPException(status_code=409, detail="At least one active administrator must remain")


def profile(db: Session, user: User, csrf: str) -> Profile:
    role = db.get(Role, user.role_id)
    return Profile(
        user=UserOut.model_validate(user),
        role=NamedResource.model_validate(role),
        permissions=permission_codes(db, user.role_id),
        categories=[NamedResource.model_validate(c) for c in allowed_categories(db, user.role_id)],
        csrf_token=csrf,
    )


def role_output(db: Session, role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        category_ids=list(
            db.scalars(
                select(RoleCategoryAccess.category_id)
                .where(
                    RoleCategoryAccess.role_id == role.id,
                )
                .order_by(RoleCategoryAccess.category_id)
            )
        ),
        permission_ids=list(
            db.scalars(
                select(RolePermission.permission_id)
                .where(
                    RolePermission.role_id == role.id,
                )
                .order_by(RolePermission.permission_id)
            )
        ),
    )
