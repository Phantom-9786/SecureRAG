from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401 -- register model metadata for autogenerate
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import database_url

secret = get_settings().database_url_unpooled
if secret is None:
    raise RuntimeError("Set DATABASE_URL_UNPOOLED before running migrations")
url = database_url(secret.get_secret_value())
if url.host and "-pooler" in url.host:
    raise RuntimeError("Migrations require the direct Neon URL, without -pooler")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
