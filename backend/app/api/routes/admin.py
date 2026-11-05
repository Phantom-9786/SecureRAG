from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import Authenticated, Database
from app.core.config import get_settings
from app.models import Category, Permission, Role
from app.schemas.identity import NamedResource, PermissionOut
from app.services.authorization import ADMIN_PERMISSIONS, permission_codes

router = APIRouter(prefix="/admin", tags=["administration"])


class AdminOptions(BaseModel):
    roles: list[NamedResource]
    categories: list[NamedResource]
    permissions: list[PermissionOut]
    max_upload_mb: int


@router.get("/options", response_model=AdminOptions)
def options(db: Database, session: Authenticated):
    grants = set(permission_codes(db, session.user.role_id))
    if not grants.intersection(ADMIN_PERMISSIONS):
        raise HTTPException(403, "Permission denied")
    return AdminOptions(
        roles=list(db.scalars(select(Role).order_by(Role.name)))
        if "users.manage" in grants
        else [],
        categories=list(db.scalars(select(Category).order_by(Category.name)))
        if grants.intersection({"roles.manage", "documents.manage"})
        else [],
        permissions=list(db.scalars(select(Permission).order_by(Permission.code)))
        if "roles.manage" in grants
        else [],
        max_upload_mb=get_settings().max_upload_mb,
    )
