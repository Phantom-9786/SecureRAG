from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dependencies import (
    Authenticated,
    CsrfSession,
    CurrentSession,
    Database,
    require_admin_write,
    require_permission,
)
from app.api.upload_limits import BODY_LIMIT_DETAIL
from app.core.config import get_settings
from app.models import Document
from app.rag.embeddings import GeminiEmbeddings, get_embedder
from app.schemas.documents import DocumentActivation, DocumentOut, DocumentUpload
from app.services.authorization import require_grant
from app.services.documents import visible_document, visible_documents
from app.services.ingestion import ingest_pdf
from app.services.storage import PDFStorage, get_storage

router = APIRouter(tags=["documents"])
Storage = Annotated[PDFStorage, Depends(get_storage)]
Embedder = Annotated[GeminiEmbeddings, Depends(get_embedder)]


def document_writer(db: Database, session: CsrfSession) -> CurrentSession:
    # Upload does not hold the global admin lock during the potentially slow ingestion pipeline.
    require_grant(db, session.user, "documents.manage")
    return session


@router.post(
    "/admin/documents",
    response_model=DocumentOut,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file", "title", "category_id"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "title": {"type": "string", "maxLength": 255},
                            "category_id": {"type": "string", "format": "uuid"},
                        },
                    }
                }
            },
        }
    },
)
async def upload_document(
    request: Request,
    db: Database,
    session: Annotated[CurrentSession, Depends(document_writer)],
    storage: Storage,
    embedder: Embedder,
):
    # Manually parse after auth dependencies run; unauthorized requests never parse/spool PDFs.
    try:
        async with request.form(max_files=1, max_fields=2, max_part_size=4096) as form:
            if len(form.multi_items()) != 3 or set(form) != {"file", "title", "category_id"}:
                raise HTTPException(
                    status_code=422, detail="Provide one file, title and category_id"
                )
            upload = form["file"]
            if not isinstance(upload, UploadFile):
                raise HTTPException(status_code=422, detail="Provide a PDF file")
            try:
                metadata = DocumentUpload.model_validate(
                    {
                        "title": form["title"],
                        "category_id": form["category_id"],
                    }
                )
            except ValidationError:
                raise HTTPException(
                    status_code=422, detail="Invalid title or category_id"
                ) from None
            return await run_in_threadpool(
                ingest_pdf,
                db,
                session.user.id,
                session.identity.token_version,
                metadata,
                upload.file,
                upload.filename,
                upload.content_type,
                storage,
                embedder,
                get_settings(),
            )
    except StarletteHTTPException as error:
        if error.status_code == 400 and error.detail == BODY_LIMIT_DETAIL:
            raise HTTPException(status_code=413, detail=BODY_LIMIT_DETAIL) from None
        raise


@router.get(
    "/admin/documents",
    response_model=list[DocumentOut],
    dependencies=[Depends(require_permission("documents.manage"))],
)
def admin_documents(
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return list(
        db.scalars(
            select(Document)
            .order_by(Document.created_at.desc(), Document.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.patch(
    "/admin/documents/{document_id}",
    response_model=DocumentOut,
    dependencies=[Depends(require_admin_write("documents.manage"))],
)
def activate_document(document_id: UUID, body: DocumentActivation, db: Database):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.ingestion_status != "ready":
        raise HTTPException(
            status_code=409, detail="Only fully ingested documents can change activation"
        )
    document.active = body.active
    db.commit()
    db.refresh(document)
    return document


@router.get("/documents", response_model=list[DocumentOut])
def my_documents(
    db: Database,
    session: Authenticated,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return list(
        db.scalars(
            visible_documents(session.user)
            .order_by(Document.created_at.desc(), Document.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.get("/documents/{document_id}", response_model=DocumentOut)
def document_details(document_id: UUID, db: Database, session: Authenticated):
    return visible_document(db, session.user, document_id)


@router.get("/documents/{document_id}/file")
def download_document(document_id: UUID, db: Database, session: Authenticated, storage: Storage):
    document = visible_document(db, session.user, document_id)
    path = storage.path_for(document.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.original_filename,
        content_disposition_type="attachment",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
