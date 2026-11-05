import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.schema import SCHEMA_REVISION
from app.db.session import get_engine

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


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
    except (RuntimeError, SQLAlchemyError) as error:
        driver_error = getattr(error, "orig", None)
        message = str(driver_error).lower()
        markers = {
            "translate host": "dns",
            "ipv4 dns lookup failed": "ipv4 dns",
            "name or service not known": "dns",
            "temporary failure in name resolution": "dns",
            "timeout expired": "timeout",
            "timed out": "timeout",
            "network is unreachable": "network",
            "connection refused": "refused",
            "password authentication failed": "authentication",
            "channel binding": "channel binding",
            "certificate verify failed": "certificate",
            "server closed the connection": "connection closed",
            "ssl connection": "tls",
            "connection reset": "connection reset",
            "endpoint is disabled": "endpoint disabled",
            "endpoint id is not specified": "endpoint routing",
            "ssl syscall error": "tls syscall",
            "eof detected": "eof",
            "connection is bad": "connection setup",
            "invalid response to ssl negotiation": "tls negotiation",
            "could not receive data from server": "receive failure",
            "connection failed": "socket connection",
            "permission denied": "permission denied",
        }
        categories = sorted({category for marker, category in markers.items() if marker in message})
        logger.warning(
            "Database readiness failed (%s, SQLSTATE %s, categories %s)",
            type(error).__name__,
            getattr(driver_error, "sqlstate", None),
            categories,
        )
        # Never return connection strings, credentials, or driver errors to clients.
        raise HTTPException(status_code=503, detail="Database is not ready") from None
    return {"status": "ready"}
