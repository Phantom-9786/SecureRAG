from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.schema import SCHEMA_REVISION
from app.db.session import get_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "securerag-api"}


@router.get("/health/ready")
def ready() -> dict[str, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if revision != SCHEMA_REVISION:
                raise RuntimeError("Database migration required")
    except (RuntimeError, SQLAlchemyError):
        # Never return connection strings, credentials, or driver errors to clients.
        raise HTTPException(status_code=503, detail="Database is not ready") from None
    return {"status": "ready"}
