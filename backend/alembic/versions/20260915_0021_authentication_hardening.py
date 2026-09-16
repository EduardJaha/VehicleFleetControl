"""Add shared, privacy-preserving login throttle state."""

from alembic import op
import sqlalchemy as sa


revision = "20260915_0021"
down_revision = "20260915_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "LoginRateLimits" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "LoginRateLimits",
        sa.Column("KeyHash", sa.String(length=64), nullable=False),
        sa.Column("AttemptCount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("WindowStartedAt", sa.DateTime(), nullable=False),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("KeyHash"),
    )
    op.create_index("ix_login_rate_limits_updated_at", "LoginRateLimits", ["UpdatedAt"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if "LoginRateLimits" not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_index("ix_login_rate_limits_updated_at", table_name="LoginRateLimits")
    op.drop_table("LoginRateLimits")
