from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GeminiRateLimit(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    project_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    rpm: int = Field(ge=1)
    tpm: int = Field(ge=1)
    rpd: int = Field(ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    frontend_origin: str = "http://localhost:3000"
    database_url: SecretStr | None = None
    database_url_unpooled: SecretStr | None = None
    embedding_dimensions: int = Field(default=1536, ge=1536, le=1536)
    pdf_storage_root: Path = Path("storage/pdfs")
    jwt_secret: SecretStr | None = None
    jwt_access_token_minutes: int = Field(default=30, ge=1, le=120)
    google_client_id: str | None = None
    gemini_api_key: SecretStr | None = None
    gemini_api_key_2: SecretStr | None = None
    gemini_api_key_3: SecretStr | None = None
    # Unknown project IDs share one conservative quota bucket; accounts are not quota IDs.
    gemini_project_id: str = Field(default="shared-project", min_length=1)
    gemini_project_id_2: str = Field(default="shared-project", min_length=1)
    gemini_project_id_3: str = Field(default="shared-project", min_length=1)
    gemini_rate_limits: list[GeminiRateLimit] = Field(default_factory=list)
    # These are local safety budgets, NOT promises about Google's actual quotas.
    gemini_default_rpm: int = Field(default=5, ge=1)
    gemini_default_tpm: int = Field(default=10000, ge=1)
    gemini_default_rpd: int = Field(default=100, ge=1)
    gemini_max_parallel_requests: int = Field(default=3, ge=1, le=3)
    gemini_max_wait_seconds: int = Field(default=5, ge=0, le=30)
    gemini_basic_model: str | None = None
    gemini_advanced_model: str | None = None
    gemini_advanced_thinking_level: Literal["low", "medium", "high"] | None = None
    gemini_generation_timeout_seconds: int = Field(default=60, ge=10, le=120)
    # Keep one embedding space in V1; changing this requires re-embedding every document.
    embedding_model: Literal["gemini-embedding-001"] = "gemini-embedding-001"
    max_upload_mb: int = Field(default=10, ge=1, le=25)
    max_pdf_pages: int = Field(default=100, ge=1, le=200)
    max_document_characters: int = Field(default=500_000, ge=1000, le=1_000_000)
    max_page_stream_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    max_document_chunks: int = Field(default=300, ge=1, le=500)
    embedding_timeout_seconds: int = Field(default=30, ge=1, le=60)
    ingestion_timeout_seconds: int = Field(default=120, ge=10, le=300)
    rag_top_k: int = Field(default=5, ge=1, le=10)
    rag_min_similarity: float = Field(default=0.60, ge=0, le=1)
    rag_context_max_bytes: int = Field(default=6000, ge=4096, le=16000)

    @field_validator(
        "gemini_api_key",
        "google_client_id",
        "gemini_api_key_2",
        "gemini_api_key_3",
        "gemini_basic_model",
        "gemini_advanced_model",
        "gemini_advanced_thinking_level",
        mode="before",
    )
    @classmethod
    def optional_provider_key(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("google_client_id")
    @classmethod
    def valid_google_client(cls, value: str | None) -> str | None:
        import re

        if value is not None and not re.fullmatch(
            r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", value
        ):
            raise ValueError("GOOGLE_CLIENT_ID must be a Web application OAuth Client ID")
        return value

    @model_validator(mode="after")
    def unique_gemini_configuration(self) -> "Settings":
        keys = [
            key.get_secret_value()
            for key in (
                self.gemini_api_key,
                self.gemini_api_key_2,
                self.gemini_api_key_3,
            )
            if key is not None
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Gemini credential slots must contain different keys")
        scopes = [(limit.project_id, limit.model) for limit in self.gemini_rate_limits]
        if len(scopes) != len(set(scopes)):
            raise ValueError("Duplicate Gemini project/model rate-limit configuration")
        return self

    @field_validator("jwt_secret")
    @classmethod
    def strong_signing_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 bytes")
        return value

    @field_validator("frontend_origin")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError(
                "FRONTEND_ORIGIN must be an HTTP(S) origin without path or credentials"
            )
        return value

    @model_validator(mode="after")
    def production_settings(self) -> "Settings":
        if self.app_env == "production":
            if self.jwt_secret is None:
                raise ValueError("JWT_SECRET is required in production")
            if not self.frontend_origin.startswith("https://"):
                raise ValueError("Production FRONTEND_ORIGIN requires HTTPS")
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.app_env == "production"

    @property
    def access_cookie(self) -> str:
        return "__Host-securerag_access" if self.secure_cookies else "securerag_access"

    @property
    def csrf_cookie(self) -> str:
        return "__Host-securerag_csrf" if self.secure_cookies else "securerag_csrf"


@lru_cache
def get_settings() -> Settings:
    return Settings()
