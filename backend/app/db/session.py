from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings


def database_url(raw: str):
    url = make_url(raw)
    if url.get_backend_name() not in {"postgres", "postgresql"}:
        raise ValueError("SecureRAG requires PostgreSQL")
    return url.set(drivername="postgresql+psycopg")


@lru_cache
def get_engine() -> Engine:
    secret = get_settings().database_url
    if secret is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(
        database_url(secret.get_secret_value()),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 10},
    )


def get_db() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
