from collections.abc import Iterator
from functools import lru_cache
from socket import AF_INET, SOCK_STREAM, gaierror, getaddrinfo

from psycopg import OperationalError
from sqlalchemy import Engine, create_engine, event
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
    settings = get_settings()
    secret = settings.database_url
    if secret is None:
        raise RuntimeError("DATABASE_URL is not configured")
    url = database_url(secret.get_secret_value())
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 10},
    )
    if settings.database_ipv4_only and url.host:
        @event.listens_for(engine, "do_connect")
        def resolve_ipv4(dialect, connection_record, args, params):
            try:
                addresses = getaddrinfo(url.host, url.port or 5432, AF_INET, SOCK_STREAM)
            except gaierror:
                raise OperationalError("Database IPv4 DNS lookup failed") from None
            hosts = list(dict.fromkeys(address[4][0] for address in addresses))
            # Keep the hostname for TLS/SNI and allow libpq to try all IPv4 results.
            params["hostaddr"] = ",".join(hosts)
            params["host"] = ",".join([url.host] * len(hosts))
            params["port"] = ",".join([str(url.port or 5432)] * len(hosts))

    return engine


def get_db() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
