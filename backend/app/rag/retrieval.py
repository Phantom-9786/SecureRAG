"""Database authorization precedes exact vector ranking; no Python post-filtering."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, RoleCategoryAccess, User


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    filename: str
    page_number: int
    content: str
    similarity: float


def authorized_chunks(user_id: UUID, token_version: int):
    return (
        select(
            Chunk.id.label("chunk_id"),
            Document.id.label("document_id"),
            Document.title.label("document_title"),
            Document.original_filename.label("filename"),
            Chunk.page_number,
            Chunk.content,
            Chunk.embedding,
        )
        .select_from(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .join(RoleCategoryAccess, RoleCategoryAccess.category_id == Document.category_id)
        .join(User, User.role_id == RoleCategoryAccess.role_id)
        .where(
            User.id == user_id,
            User.is_active.is_(True),
            User.token_version == token_version,
            Document.active.is_(True),
            Document.ingestion_status == "ready",
        )
    )


def authorized_chunk_ids(user_id: UUID, token_version: int):
    return authorized_chunks(user_id, token_version).with_only_columns(Chunk.id)


def has_authorized_content(db: Session, user_id: UUID, token_version: int) -> bool:
    return db.scalar(authorized_chunk_ids(user_id, token_version).limit(1)) is not None


def retrieval_statement(
    user_id: UUID, token_version: int, vector: list[float], top_k: int, min_similarity: float
):
    # MATERIALIZED prevents the authorized relation being folded into an unrestricted rank step.
    scope = (
        authorized_chunks(user_id, token_version)
        .cte("authorized_chunks")
        .prefix_with("MATERIALIZED")
    )
    distance = scope.c.embedding.cosine_distance(vector)
    return (
        select(
            scope.c.chunk_id,
            scope.c.document_id,
            scope.c.document_title,
            scope.c.filename,
            scope.c.page_number,
            scope.c.content,
            (1 - distance).label("similarity"),
        )
        .where(distance <= 1 - min_similarity)
        .order_by(distance, scope.c.chunk_id)
        .limit(top_k)
    )


def retrieve(
    db: Session,
    user_id: UUID,
    token_version: int,
    vector: list[float],
    top_k: int,
    min_similarity: float,
) -> list[RetrievedChunk]:
    rows = db.execute(
        retrieval_statement(user_id, token_version, vector, top_k, min_similarity)
    ).mappings()
    return [RetrievedChunk(**row) for row in rows]


def sources_still_authorized(
    db: Session, user_id: UUID, token_version: int, chunk_ids: list[UUID]
) -> bool:
    if not chunk_ids:
        return True
    allowed = set(
        db.scalars(authorized_chunk_ids(user_id, token_version).where(Chunk.id.in_(chunk_ids)))
    )
    return allowed == set(chunk_ids)
