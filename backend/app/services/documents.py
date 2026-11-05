from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, RoleCategoryAccess, User


def visible_documents(user: User):
    # The role comes from current_session's database user, never a client-provided filter.
    categories = select(RoleCategoryAccess.category_id).where(
        RoleCategoryAccess.role_id == user.role_id,
    )
    return select(Document).where(
        Document.active.is_(True),
        Document.ingestion_status == "ready",
        Document.category_id.in_(categories),
    )


def visible_document(db: Session, user: User, document_id: UUID) -> Document:
    document = db.scalar(visible_documents(user).where(Document.id == document_id))
    if document is None:
        # Missing, inactive and unauthorized IDs all give the same response.
        raise HTTPException(status_code=404, detail="Document not found")
    return document
