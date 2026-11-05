"""Owner-scoped conversations and permission-aware history rendering."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, case, exists, literal, or_, select
from sqlalchemy.orm import Session

from app.models import Chunk, Conversation, Document, Message, MessageSource, User
from app.rag.citations import NO_EVIDENCE, WITHHELD_ANSWER, GroundingError, referenced_sources
from app.rag.retrieval import authorized_chunk_ids
from app.schemas.conversations import CitationOut, ConversationOut, MessageOut


def require_actor(db: Session, user_id: UUID, token_version: int) -> User:
    user = db.get(User, user_id, populate_existing=True)
    if user is None or not user.is_active or user.token_version != token_version:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user


def owned_conversation(db: Session, user_id: UUID, conversation_id: UUID) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def create_conversation(db: Session, user_id: UUID, title: str) -> ConversationOut:
    conversation = Conversation(user_id=user_id, title=title)
    db.add(conversation)
    db.flush()
    result = ConversationOut.model_validate(conversation)
    db.commit()
    return result


def list_conversations(db: Session, user_id: UUID, offset: int, limit: int) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .offset(offset)
            .limit(limit)
        )
    )


def history_statement(user_id: UUID, token_version: int, conversation_id: UUID):
    allowed = authorized_chunk_ids(user_id, token_version)
    source_exists = exists(
        select(MessageSource.chunk_id).where(
            MessageSource.message_id == Message.id,
        )
    ).correlate(Message)
    unavailable_source = exists(
        select(MessageSource.chunk_id).where(
            MessageSource.message_id == Message.id,
            MessageSource.chunk_id.not_in(allowed),
        )
    ).correlate(Message)
    withheld = and_(
        Message.role == "assistant",
        or_(
            unavailable_source,
            and_(~source_exists, Message.content != NO_EVIDENCE),
        ),
    )
    # SQL CASE prevents a restricted stored answer from being returned to the application at all.
    return select(
        Message.id,
        Message.role,
        Message.created_at,
        case((withheld, literal(WITHHELD_ANSWER)), else_=Message.content).label("content"),
        withheld.label("withheld"),
    ).where(Message.conversation_id == conversation_id)


def conversation_history(
    db: Session, user_id: UUID, token_version: int, conversation_id: UUID, offset: int, limit: int
) -> list[MessageOut]:
    owned_conversation(db, user_id, conversation_id)
    rows = list(
        db.execute(
            history_statement(user_id, token_version, conversation_id)
            .order_by(Message.created_at, Message.id)
            .offset(offset)
            .limit(limit)
        ).mappings()
    )
    visible_ids = [row["id"] for row in rows if row["role"] == "assistant" and not row["withheld"]]
    citation_map: dict[UUID, dict[int, CitationOut]] = {}
    if visible_ids:
        # Only metadata from currently authorized sources of visible answers is fetched.
        sources = db.execute(
            select(
                MessageSource.message_id,
                MessageSource.source_number,
                Chunk.id.label("chunk_id"),
                Chunk.page_number,
                Document.id.label("document_id"),
                Document.title,
                Document.original_filename,
            )
            .select_from(MessageSource)
            .join(Chunk, Chunk.id == MessageSource.chunk_id)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                MessageSource.message_id.in_(visible_ids),
                Chunk.id.in_(authorized_chunk_ids(user_id, token_version)),
            )
        ).mappings()
        for source in sources:
            citation_map.setdefault(source["message_id"], {})[source["source_number"]] = (
                CitationOut(
                    source_id=f"S{source['source_number']}",
                    document_id=source["document_id"],
                    chunk_id=source["chunk_id"],
                    document_title=source["title"],
                    filename=source["original_filename"],
                    page_number=source["page_number"],
                    download_url=f"/api/v1/documents/{source['document_id']}/file",
                )
            )
    result = []
    for row in rows:
        message = MessageOut(**row)
        if message.role == "assistant" and not message.withheld:
            available = citation_map.get(message.id, {})
            try:
                numbers = referenced_sources(message.content, set(available))
                message.sources = [available[number] for number in numbers]
            except GroundingError:
                message.content = WITHHELD_ANSWER
                message.withheld = True
        result.append(message)
    return result
