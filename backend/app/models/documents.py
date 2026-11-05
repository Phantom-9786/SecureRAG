from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import IdentityMixin, TimestampMixin


class Document(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "ingestion_status IN ('processing', 'ready', 'failed')",
            name="valid_ingestion_status",
        ),
    )
    title: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id"), index=True)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    ingestion_status: Mapped[str] = mapped_column(String(20), server_default="processing")


class Chunk(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        CheckConstraint("page_number > 0", name="positive_page"),
        CheckConstraint("chunk_index >= 0", name="nonnegative_chunk_index"),
        CheckConstraint("length(trim(content)) > 0", name="nonempty_content"),
    )
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int]
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))
