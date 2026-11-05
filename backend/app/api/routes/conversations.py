from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import Authenticated, CsrfSession, Database
from app.core.config import get_settings
from app.rag.citations import GroundingError
from app.rag.embeddings import EmbeddingBusy, EmbeddingError, GeminiEmbeddings, get_embedder
from app.rag.generation import get_generator
from app.schemas.conversations import (
    ConversationCreate,
    ConversationOut,
    MessageOut,
    QuestionInput,
    QuestionResult,
)
from app.services import conversations
from app.services.gemini import GeminiBusy, GeminiError
from app.services.rag import ask_question

router = APIRouter(prefix="/conversations", tags=["conversations and secure RAG"])


@router.post("", response_model=ConversationOut, status_code=201)
def create_conversation(body: ConversationCreate, db: Database, session: CsrfSession):
    return conversations.create_conversation(db, session.user.id, body.title)


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    db: Database,
    session: Authenticated,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return conversations.list_conversations(db, session.user.id, offset, limit)


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: UUID, db: Database, session: Authenticated):
    return conversations.owned_conversation(db, session.user.id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def history(
    conversation_id: UUID,
    db: Database,
    session: Authenticated,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return conversations.conversation_history(
        db, session.user.id, session.identity.token_version, conversation_id, offset, limit
    )


@router.post("/{conversation_id}/messages", response_model=QuestionResult, status_code=201)
def question(
    conversation_id: UUID,
    body: QuestionInput,
    db: Database,
    session: CsrfSession,
    embedder: Annotated[GeminiEmbeddings, Depends(get_embedder)],
    generator: Annotated[Callable, Depends(get_generator)],
):
    try:
        return ask_question(
            db,
            session.user.id,
            session.identity.token_version,
            conversation_id,
            body,
            embedder,
            generator,
            get_settings(),
        )
    except (EmbeddingBusy, GeminiBusy) as error:
        raise HTTPException(
            status_code=429,
            detail="AI capacity is temporarily unavailable",
            headers={"Retry-After": str(error.retry_after)},
        ) from None
    except GroundingError:
        raise HTTPException(
            status_code=502, detail="Could not produce a source-grounded answer; please rephrase"
        ) from None
    except (EmbeddingError, GeminiError):
        raise HTTPException(
            status_code=503, detail="AI service is unavailable or not configured"
        ) from None
