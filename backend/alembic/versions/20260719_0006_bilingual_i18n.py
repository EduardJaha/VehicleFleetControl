"""add bilingual preference and language-neutral generated-content fields

Revision ID: 20260719_0006
Revises: 20260719_0005
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa

revision = "20260719_0006"
down_revision = "20260719_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "Users" in tables:
        columns = {column["name"] for column in inspector.get_columns("Users")}
        if "PreferredLanguage" not in columns:
            op.add_column(
                "Users",
                sa.Column(
                    "PreferredLanguage",
                    sa.String(length=5),
                    sa.CheckConstraint("\"PreferredLanguage\" IN ('en', 'sq')", name="ck_users_preferred_language"),
                    nullable=False,
                    server_default="en",
                ),
            )
    if "Notifications" in tables:
        columns = {column["name"] for column in inspector.get_columns("Notifications")}
        for column in (
            sa.Column("TitleKey", sa.String(length=255), nullable=True),
            sa.Column("MessageKey", sa.String(length=255), nullable=True),
            sa.Column("MessageParams", sa.JSON(), nullable=True),
        ):
            if column.name not in columns:
                op.add_column("Notifications", column)
    if "AuditLogs" in tables:
        columns = {column["name"] for column in inspector.get_columns("AuditLogs")}
        for column in (
            sa.Column("ActionCode", sa.String(length=100), nullable=True),
            sa.Column("DescriptionKey", sa.String(length=255), nullable=True),
            sa.Column("DescriptionParams", sa.JSON(), nullable=True),
        ):
            if column.name not in columns:
                op.add_column("AuditLogs", column)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, names in (
        ("AuditLogs", ("DescriptionParams", "DescriptionKey", "ActionCode")),
        ("Notifications", ("MessageParams", "MessageKey", "TitleKey")),
        ("Users", ("PreferredLanguage",)),
    ):
        if table not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        with op.batch_alter_table(table) as batch:
            for name in names:
                if name in columns:
                    batch.drop_column(name)
