from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

import app.models  # noqa: F401
from app.core.config import Settings
from app.db.base import Base
from app.main import create_app


def test_liveness_without_database():
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"


def test_readiness_does_not_leak_errors(monkeypatch):
    def unavailable():
        raise RuntimeError("secret database credentials")

    monkeypatch.setattr("app.api.routes.health.get_engine", unavailable)
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert "secret" not in response.text


def test_schema_compiles_with_pgvector_and_constraints():
    ddl = "\n".join(
        str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for table in Base.metadata.sorted_tables
    )
    assert len(Base.metadata.tables) == 12
    assert "VECTOR(1536)" in ddl
    assert "FOREIGN KEY" in ddl
    assert "normalized_email" in ddl


def test_secrets_are_redacted():
    settings = Settings(_env_file=None, database_url="postgresql://user:password@localhost/db")
    assert "password" not in repr(settings)


def test_embedding_dimensions_load_from_environment(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")
    assert Settings(_env_file=None).embedding_dimensions == 1536


def test_initial_migration_snapshot_is_immutable():
    # Later migrations evolve the models; the original migration stays reproducible.
    import hashlib

    snapshot = Path("migrations/versions/0001_initial.sql").read_bytes()
    assert hashlib.sha256(snapshot).hexdigest() == (
        "659b6106fcce06ff8d370118f85b8798291b914eb6b76be4bcf72bfbf9b186ef"
    )
