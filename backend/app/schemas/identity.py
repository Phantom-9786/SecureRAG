from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Password = Annotated[SecretStr, Field(min_length=12, max_length=128)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EmailInput(InputModel):
    email: EmailStr = Field(max_length=254)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class LoginInput(EmailInput):
    password: SecretStr = Field(min_length=1, max_length=128)


class UserCreate(EmailInput):
    name: Name
    password: Password
    role_id: UUID


class GoogleUserCreate(EmailInput):
    name: Name
    role_id: UUID


class UserUpdate(InputModel):
    role_id: UUID | None = None
    is_active: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def nonempty_update(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Provide role_id and/or is_active, without null values")
        return self


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    email: str
    role_id: UUID
    is_active: bool
    created_at: datetime


class NamedResource(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str


class Profile(BaseModel):
    user: UserOut
    role: NamedResource
    permissions: list[str]
    categories: list[NamedResource]
    csrf_token: str


class RoleOut(NamedResource):
    category_ids: list[UUID]
    permission_ids: list[UUID]


class RoleGrantsUpdate(InputModel):
    # Full replacement: omitted lists cannot accidentally wipe grants.
    category_ids: list[UUID] = Field(max_length=100)
    permission_ids: list[UUID] = Field(max_length=100)

    @field_validator("category_ids", "permission_ids")
    @classmethod
    def unique_grants(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Duplicate grant IDs are not allowed")
        return values
