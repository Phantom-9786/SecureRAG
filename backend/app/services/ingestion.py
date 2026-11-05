"""Synchronous ingestion with atomic chunk publication and short authorization transactions."""

import logging
import time
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Category, Chunk, Document, User
from app.rag.chunking import chunk_pages
from app.rag.embeddings import EmbeddingBusy, EmbeddingError, GeminiEmbeddings, validate_vectors
from app.rag.extraction import PDFProcessingError, extract_pages
from app.schemas.documents import DocumentUpload
from app.services.authorization import lock_admin_changes, require_grant
from app.services.storage import PDFStorage

logger = logging.getLogger(__name__)


def recheck_uploader(db: Session, user_id: UUID, token_version: int) -> None:
    lock_admin_changes(db)
    user = db.get(User, user_id, populate_existing=True)
    if user is None or not user.is_active or user.token_version != token_version:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    require_grant(db, user, "documents.manage")


def mark_failed(db: Session, document_id: UUID) -> None:
    db.rollback()
    try:
        db.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.ingestion_status == "processing",
            )
            .values(ingestion_status="failed", active=False)
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        # An unavailable database may leave 'processing', which is still ineligible for reads.
        logger.warning(
            "Could not persist failed ingestion state", extra={"document_id": str(document_id)}
        )


def ingest_pdf(
    db: Session,
    actor_id: UUID,
    token_version: int,
    metadata: DocumentUpload,
    source: BinaryIO,
    filename: str | None,
    content_type: str | None,
    storage: PDFStorage,
    embedder: GeminiEmbeddings,
    settings: Settings,
) -> Document:
    try:
        embedder.ensure_configured()
    except EmbeddingError:
        raise HTTPException(
            status_code=503, detail="Configure GEMINI_API_KEY before uploading PDFs"
        ) from None
    if db.get(Category, metadata.category_id) is None:
        raise HTTPException(status_code=404, detail="Category not found")
    try:
        key, original_filename = storage.save(source, filename, content_type)
    except OSError:
        raise HTTPException(status_code=503, detail="Private PDF storage is unavailable") from None
    document_id = uuid4()
    try:
        recheck_uploader(db, actor_id, token_version)
        document = Document(
            id=document_id,
            title=metadata.title,
            original_filename=original_filename,
            storage_key=key,
            category_id=metadata.category_id,
            uploaded_by=actor_id,
            ingestion_status="processing",
            active=False,
        )
        db.add(document)
        db.commit()
    except Exception:
        db.rollback()
        try:
            storage.remove(key)  # No committed metadata owns this file.
        except OSError:
            logger.warning(
                "Could not remove unowned upload", extra={"document_id": str(document_id)}
            )
        raise

    deadline = time.monotonic() + settings.ingestion_timeout_seconds
    try:
        pages = extract_pages(storage.path_for(key), settings)
        chunks = chunk_pages(pages, settings.max_document_chunks)
        vectors = embedder.embed_documents([chunk.content for chunk in chunks], deadline)
        vectors = validate_vectors(vectors, len(chunks), settings.embedding_dimensions)
        if time.monotonic() > deadline:
            raise EmbeddingError("Embedding generation timed out")
        # No database transaction/global admin lock is held while PDF parsing or HTTP work runs.
        recheck_uploader(db, actor_id, token_version)
        document = db.get(Document, document_id, populate_existing=True)
        db.add_all(
            [
                Chunk(
                    document_id=document_id,
                    chunk_index=index,
                    page_number=chunk.page_number,
                    content=chunk.content,
                    embedding=vector,
                )
                for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
            ]
        )
        document.ingestion_status = "ready"
        document.active = True
        db.commit()  # All chunks and readiness are published together, never partially.
        db.refresh(document)
        return document
    except PDFProcessingError as error:
        mark_failed(db, document_id)
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(error),
                "document_id": str(document_id),
            },
        ) from None
    except EmbeddingBusy as error:
        mark_failed(db, document_id)
        raise HTTPException(
            status_code=429,
            detail={
                "message": str(error),
                "document_id": str(document_id),
            },
            headers={"Retry-After": str(error.retry_after)},
        ) from None
    except EmbeddingError as error:
        mark_failed(db, document_id)
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(error),
                "document_id": str(document_id),
            },
        ) from None
    except HTTPException:
        mark_failed(db, document_id)
        raise
    except SQLAlchemyError:
        mark_failed(db, document_id)
        raise
    except Exception:  # noqa: BLE001 -- sanitize unexpected failures without logging private payloads
        mark_failed(db, document_id)
        logger.warning("Document ingestion failed", extra={"document_id": str(document_id)})
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Document processing failed",
                "document_id": str(document_id),
            },
        ) from None
