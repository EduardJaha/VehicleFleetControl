"""Durable notification preferences and channel delivery tracking."""

from alembic import op
import sqlalchemy as sa


revision = "20260915_0020"
down_revision = "20260914_0019"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "NotificationPreferences" not in existing:
        op.create_table(
            "NotificationPreferences",
            sa.Column("Id", sa.Integer(), nullable=False),
            sa.Column("UserId", sa.Integer(), nullable=False),
            sa.Column("NotificationType", sa.String(length=100), nullable=False),
            sa.Column("InAppEnabled", sa.Boolean(), nullable=False),
            sa.Column("EmailEnabled", sa.Boolean(), nullable=False),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False),
            sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
            sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
            sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["UserId"], ["Users.Id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("Id"),
            sa.UniqueConstraint("CompanyId", "UserId", "NotificationType", name="uq_notification_preferences_user_type"),
        )
        op.create_index("ix_notification_preferences_user", "NotificationPreferences", ["UserId"], unique=False)
        op.create_index(op.f("ix_NotificationPreferences_CompanyId"), "NotificationPreferences", ["CompanyId"], unique=False)
    if "NotificationDeliveries" not in existing:
        op.create_table(
            "NotificationDeliveries",
            sa.Column("Id", sa.Integer(), nullable=False),
            sa.Column("NotificationId", sa.Integer(), nullable=False),
            sa.Column("Channel", sa.String(length=20), nullable=False),
            sa.Column("Recipient", sa.String(length=255), nullable=False),
            sa.Column("Status", sa.String(length=20), nullable=False),
            sa.Column("AttemptCount", sa.Integer(), nullable=False),
            sa.Column("LastAttempt", sa.DateTime(), nullable=True),
            sa.Column("NextAttemptAt", sa.DateTime(), nullable=True),
            sa.Column("SentAt", sa.DateTime(), nullable=True),
            sa.Column("FailureReason", sa.Text(), nullable=True),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False),
            sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
            sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
            sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["NotificationId"], ["Notifications.Id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("Id"),
            sa.UniqueConstraint("CompanyId", "NotificationId", "Channel", name="uq_notification_deliveries_notification_channel"),
        )
        op.create_index("ix_notification_deliveries_status_attempt", "NotificationDeliveries", ["Status", "NextAttemptAt"], unique=False)
        op.create_index(op.f("ix_NotificationDeliveries_CompanyId"), "NotificationDeliveries", ["CompanyId"], unique=False)


def downgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in ("NotificationDeliveries", "NotificationPreferences"):
        if table in existing:
            op.drop_table(table)
