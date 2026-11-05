from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.schema import SCHEMA_REVISION
from app.main import create_app


class Connection:
    def __init__(self, revision):
        self.revision = revision

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        return self

    def scalar(self):
        return self.revision


class Engine:
    def __init__(self, revision):
        self.revision = revision

    def connect(self):
        return Connection(self.revision)


@pytest.mark.parametrize(
    "revision,expected", [("0001", 503), (SCHEMA_REVISION, 200), ("unexpected", 503)]
)
def test_readiness_requires_the_current_release_schema(monkeypatch, revision, expected):
    monkeypatch.setattr("app.api.routes.health.get_engine", lambda: Engine(revision))
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == expected
    if expected == 200:
        assert response.json() == {"status": "ready"}


def test_expected_schema_matches_alembic_head():
    config = Config("alembic.ini")
    assert ScriptDirectory.from_config(config).get_current_head() == SCHEMA_REVISION


def test_production_schema_and_docs_are_not_public(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://rag.example.com")
    monkeypatch.setenv("JWT_SECRET", "production-settings-test-only-" * 3)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/docs").status_code == 404
            assert client.get("/openapi.json").status_code == 404
            response = client.get("/api/v1/health")
            assert response.status_code == 200
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["cache-control"] == "no-store"
    finally:
        get_settings.cache_clear()


def test_docker_build_contexts_exclude_local_secrets():
    # Contexts use an allowlist; neither image COPYs environment files or PDF storage.
    root = Path(__file__).resolve().parents[2]
    for service in ("backend", "frontend"):
        ignore = (root / service / ".dockerignore").read_text()
        assert ignore.startswith("*\n")
        assert "!.env" not in ignore
        dockerfile = (root / service / "Dockerfile").read_text()
        assert "COPY . ." not in dockerfile
        assert "COPY .env" not in dockerfile
        assert "USER " in dockerfile
