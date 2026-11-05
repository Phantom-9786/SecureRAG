from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.identity import InputModel


class DocumentUpload(InputModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    category_id: UUID


class DocumentActivation(InputModel):
    active: bool = Field(strict=True)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    original_filename: str
    category_id: UUID
    uploaded_by: UUID
    active: bool
    ingestion_status: Literal["processing", "ready", "failed"]
    created_at: datetime
