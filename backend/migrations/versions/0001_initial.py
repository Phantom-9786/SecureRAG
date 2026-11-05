"""Initial SecureRAG schema; immutable SQL snapshot, independent of future models."""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "message_sources",
        "messages",
        "conversations",
        "chunks",
        "documents",
        "users",
        "role_permissions",
        "role_category_access",
        "permissions",
        "categories",
        "roles",
    ):
        op.drop_table(table)
    # The vector extension may be shared with other applications; leave it installed.
