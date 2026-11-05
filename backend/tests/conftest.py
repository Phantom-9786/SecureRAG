"""Shared PostgreSQL fixtures; all writes are rolled back in a private test schema."""

import os
import secrets
from contextlib import ExitStack
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from app.core.config import get_settings
from app.db.base import Base
from app.db.bootstrap_admin import bootstrap_admin
from app.db.seed import seed_initial
from app.db.session import database_url, get_db
from app.main import create_app

ORIGIN = {"Origin": "http://localhost:3000"}
PASSWORD = "integration-password-only-482!"


@pytest.fixture(scope="module")
def database_connection():
    if os.environ.get("SECURERAG_RUN_DB_TESTS") != "1":
        pytest.skip("Set SECURERAG_RUN_DB_TESTS=1 to use the configured development database")
    get_settings.cache_clear()
    secret = get_settings().database_url_unpooled
    assert secret is not None, "Configure the Neon development database first"
    engine = create_engine(
        database_url(secret.get_secret_value()),
        connect_args={"connect_timeout": 10},
        pool_pre_ping=True,
    )
    try:
        connection = engine.connect()
    except SQLAlchemyError:
        # Driver tracebacks may include connection parameter dictionaries; never echo them.
        engine.dispose()
        pytest.fail(
            "Development database connection failed; check Neon connectivity", pytrace=False
        )
    try:
        yield connection
    finally:
        connection.close()
        engine.dispose()


@pytest.fixture
def api(monkeypatch, database_connection):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("FRONTEND_ORIGIN", ORIGIN["Origin"])
    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(48))
    get_settings.cache_clear()
    connection = database_connection
    transaction = connection.begin()
    try:
        schema = "securerag_test_" + uuid4().hex
        connection.execute(CreateSchema(schema))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        # Do not let checkfirst discover same-named public application tables via search_path.
        Base.metadata.create_all(connection, checkfirst=False)
        resolved_schema = connection.scalar(
            text(
                "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.oid='users'::regclass"
            )
        )
        assert resolved_schema == schema
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            seed_initial(db)
            bootstrap_admin(db, "Test Admin", "admin@example.com", PASSWORD)
            db.commit()
        app = create_app()

        def override_db():
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        with ExitStack() as stack:
            clients = [stack.enter_context(TestClient(app)) for _ in range(3)]
            yield clients, connection
    finally:
        transaction.rollback()  # Includes schema creation, users, grants and all request writes.
        get_settings.cache_clear()
