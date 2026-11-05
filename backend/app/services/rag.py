"""Authenticate -> scope retrieval -> rank -> authorized context -> answer -> atomic turn."""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import case, func, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Conversation, Message, MessageSource
from app.rag.citations import NO_EVIDENCE, ContextSource, build_context, referenced_sources
from app.rag.embeddings import GeminiEmbeddings, validate_vectors
from app.rag.generation import GeneratedAnswer
from app.rag.retrieval import has_authorized_content, retrieve, sources_still_authorized
from app.schemas.conversations import MessageOut, QuestionInput, QuestionResult
from app.services.conversations import owned_conversation, require_actor


def check_sources(
    db: Session, user_id: UUID, token_version: int, sources: list[ContextSource]
) -> None:
    require_actor(db, user_id, token_version)
    if not sources_still_authorized(
        db, user_id, token_version, [s.chunk.chunk_id for s in sources]
    ):
        raise HTTPException(status_code=409, detail="Document access changed; please ask again")


def persist_turn(
    db: Session,
    user_id: UUID,
    token_version: int,
    conversation_id: UUID,
    expected_updated_at: datetime,
    asked_at: datetime,
    question: str,
    generated: GeneratedAnswer,
    sources: list[ContextSource],
) -> QuestionResult:
    numbers = referenced_sources(generated.text, {source.number for source in sources})
    check_sources(db, user_id, token_version, sources)
    # The conditional UPDATE serializes only the short commit; providers run without row locks.
    changed = db.scalar(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.updated_at == expected_updated_at,
        )
        .values(
            updated_at=func.clock_timestamp(),
            title=case(
                (Conversation.title == "New conversation", question[:80]),
                else_=Conversation.title,
            ),
        )
        .returning(Conversation.id)
    )
    if changed is None:
        raise HTTPException(
            status_code=409, detail="Conversation changed; reload it before asking again"
        )
    answer_time = max(datetime.now(UTC), asked_at + timedelta(microseconds=1))
    user_message = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        role="user",
        content=question,
        created_at=asked_at,
    )
    assistant_message = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        role="assistant",
        content=generated.text,
        created_at=answer_time,
    )
    db.add_all([user_message, assistant_message])
    db.flush()
    if generated.text.strip() != NO_EVIDENCE:
        # Store ALL context chunks, not just cited ones, so revoked evidence cannot leak via history.
        db.add_all(
            [
                MessageSource(
                    message_id=assistant_message.id,
                    chunk_id=source.chunk.chunk_id,
                    source_number=source.number,
                )
                for source in sources
            ]
        )
    question_out = MessageOut(
        id=user_message.id, role="user", content=question, created_at=asked_at
    )
    by_number = {source.number: source.citation() for source in sources}
    answer_out = MessageOut(
        id=assistant_message.id,
        role="assistant",
        content=generated.text,
        created_at=answer_time,
        sources=[by_number[number] for number in numbers],
    )
    db.commit()
    return QuestionResult(
        conversation_id=conversation_id,
        question=question_out,
        answer=answer_out,
        model=generated.model,
        routing_reason=generated.routing_reason,
    )


def ask_question(
    db: Session,
    user_id: UUID,
    token_version: int,
    conversation_id: UUID,
    body: QuestionInput,
    embedder: GeminiEmbeddings,
    generator: Callable,
    settings: Settings,
) -> QuestionResult:
    asked_at = datetime.now(UTC)
    require_actor(db, user_id, token_version)
    conversation = owned_conversation(db, user_id, conversation_id)
    expected_updated_at = conversation.updated_at
    has_content = has_authorized_content(db, user_id, token_version)
    db.commit()  # Close the read transaction before an external embedding request.
    sources = []
    generated = GeneratedAnswer(NO_EVIDENCE, "none", "No relevant authorized evidence")
    if has_content:
        vector = embedder.embed_query(
            body.question, time.monotonic() + settings.embedding_timeout_seconds
        )
        vector = validate_vectors([vector], 1, settings.embedding_dimensions)[0]
        chunks = retrieve(
            db, user_id, token_version, vector, settings.rag_top_k, settings.rag_min_similarity
        )
        context, sources = build_context(chunks, settings.rag_context_max_bytes)
        check_sources(db, user_id, token_version, sources)
        db.commit()  # Only allowed context survives this boundary; no DB lock during LLM work.
        if context:
            generated = generator(
                body.question, context, len({s.chunk.document_id for s in sources}), body.model_mode
            )
    return persist_turn(
        db,
        user_id,
        token_version,
        conversation_id,
        expected_updated_at,
        asked_at,
        body.question,
        generated,
        sources,
    )
