from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.identity import InputModel


class ConversationCreate(InputModel):
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = "New conversation"

    @field_validator("title")
    @classmethod
    def plain_title(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("Conversation title contains invalid control characters")
        return value


class QuestionInput(InputModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    model_mode: Literal["auto", "basic", "advanced"] = "auto"

    @field_validator("question")
    @classmethod
    def bounded_plain_text(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 2500 or any(
            ord(char) < 32 and char not in "\n\t" for char in value
        ):
            raise ValueError(
                "Question exceeds the byte budget or contains invalid control characters"
            )
        return value


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class CitationOut(BaseModel):
    source_id: str
    document_id: UUID
    chunk_id: UUID
    document_title: str
    filename: str
    page_number: int
    download_url: str


class MessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    withheld: bool = False
    sources: list[CitationOut] = Field(default_factory=list)


class QuestionResult(BaseModel):
    conversation_id: UUID
    question: MessageOut
    answer: MessageOut
    model: str
    routing_reason: str
