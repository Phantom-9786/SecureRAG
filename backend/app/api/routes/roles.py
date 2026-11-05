from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from app.api.dependencies import Authenticated, Database, require_admin_write, require_permission
from app.models import Category, Permission, Role, RoleCategoryAccess, RolePermission
from app.schemas.identity import NamedResource, PermissionOut, RoleGrantsUpdate, RoleOut
from app.services.authorization import allowed_categories, ensure_active_admin, role_output

router = APIRouter(tags=["roles and access"])


@router.get("/categories", response_model=list[NamedResource])
def my_categories(db: Database, session: Authenticated):
    return allowed_categories(db, session.user.role_id)


@router.get(
    "/roles",
    response_model=list[RoleOut],
    dependencies=[Depends(require_permission("roles.manage"))],
)
def list_roles(db: Database):
    return [role_output(db, role) for role in db.scalars(select(Role).order_by(Role.name))]


@router.get(
    "/permissions",
    response_model=list[PermissionOut],
    dependencies=[Depends(require_permission("roles.manage"))],
)
def list_permissions(db: Database):
    return list(db.scalars(select(Permission).order_by(Permission.code)))


@router.get(
    "/admin/categories",
    response_model=list[NamedResource],
    dependencies=[Depends(require_permission("roles.manage"))],
)
def all_categories(db: Database):
    return list(db.scalars(select(Category).order_by(Category.name)))


@router.put(
    "/roles/{role_id}/grants",
    response_model=RoleOut,
    dependencies=[Depends(require_admin_write("roles.manage"))],
)
def update_grants(role_id: UUID, body: RoleGrantsUpdate, db: Database):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    categories = set(db.scalars(select(Category.id).where(Category.id.in_(body.category_ids))))
    permissions = set(
        db.scalars(select(Permission.id).where(Permission.id.in_(body.permission_ids)))
    )
    if categories != set(body.category_ids) or permissions != set(body.permission_ids):
        raise HTTPException(status_code=422, detail="Unknown category or permission ID")
    db.execute(delete(RoleCategoryAccess).where(RoleCategoryAccess.role_id == role_id))
    db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    db.add_all([RoleCategoryAccess(role_id=role_id, category_id=key) for key in categories])
    db.add_all([RolePermission(role_id=role_id, permission_id=key) for key in permissions])
    ensure_active_admin(db)
    db.commit()
    return role_output(db, role)
