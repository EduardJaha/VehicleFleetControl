"""Tenant API keys and durable webhook outbox."""
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = "20260917_0023"
down_revision = "20260917_0022"
branch_labels = None
depends_on = None


def company_column():
    return sa.Column("CompanyId", sa.Integer(), sa.ForeignKey("Companies.Id", ondelete="RESTRICT"), nullable=False, server_default="1")


def upgrade():
    bind = op.get_bind()
    existing = sa.inspect(bind).get_table_names()
    if "APIKeys" not in existing:
        op.create_table("APIKeys",
            sa.Column("Id", sa.Integer(), primary_key=True), company_column(),
            sa.Column("Name", sa.String(100), nullable=False), sa.Column("KeyPrefix", sa.String(24), nullable=False),
            sa.Column("KeyHash", sa.String(64), nullable=False, unique=True), sa.Column("Scopes", sa.JSON(), nullable=False),
            sa.Column("ExpiresAt", sa.DateTime()), sa.Column("LastUsedAt", sa.DateTime()), sa.Column("RevokedAt", sa.DateTime()),
            sa.Column("CreatedBy", sa.Integer(), sa.ForeignKey("Users.Id"), nullable=False),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False))
        op.create_index("ix_APIKeys_CompanyId", "APIKeys", ["CompanyId"])
    if "WebhookEndpoints" not in existing:
        op.create_table("WebhookEndpoints",
            sa.Column("Id", sa.Integer(), primary_key=True), company_column(),
            sa.Column("Name", sa.String(100), nullable=False), sa.Column("Url", sa.String(2048), nullable=False),
            sa.Column("Events", sa.JSON(), nullable=False), sa.Column("SecretCiphertext", sa.Text(), nullable=False),
            sa.Column("SecretVersion", sa.Integer(), nullable=False), sa.Column("RevokedAt", sa.DateTime()),
            sa.Column("CreatedBy", sa.Integer(), sa.ForeignKey("Users.Id"), nullable=False),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False))
        op.create_index("ix_WebhookEndpoints_CompanyId", "WebhookEndpoints", ["CompanyId"])
    if "WebhookDeliveries" not in existing:
        op.create_table("WebhookDeliveries",
            sa.Column("Id", sa.Integer(), primary_key=True), company_column(),
            sa.Column("EndpointId", sa.Integer(), sa.ForeignKey("WebhookEndpoints.Id"), nullable=False),
            sa.Column("EventId", sa.String(36), nullable=False), sa.Column("DeliveryId", sa.String(36), nullable=False, unique=True),
            sa.Column("EventType", sa.String(80), nullable=False), sa.Column("Payload", sa.Text(), nullable=False),
            sa.Column("Status", sa.String(16), nullable=False), sa.Column("AttemptCount", sa.Integer(), nullable=False),
            sa.Column("Attempts", sa.JSON(), nullable=False), sa.Column("NextAttemptAt", sa.DateTime(), nullable=False),
            sa.Column("LeaseToken", sa.String(36)), sa.Column("LeaseUntil", sa.DateTime()), sa.Column("DeliveredAt", sa.DateTime()),
            sa.Column("ResendOf", sa.Integer(), sa.ForeignKey("WebhookDeliveries.Id")), sa.Column("CreatedAt", sa.DateTime(), nullable=False),
            sa.CheckConstraint('"Status" IN (\'Pending\', \'Delivered\', \'Failed\', \'Retrying\', \'Dead\')', name="ck_webhook_delivery_status"))
        op.create_index("ix_WebhookDeliveries_CompanyId", "WebhookDeliveries", ["CompanyId"])
        op.create_index("uq_webhook_original_event", "WebhookDeliveries", ["CompanyId", "EndpointId", "EventId"],
                        unique=True, sqlite_where=sa.text('"ResendOf" IS NULL'), postgresql_where=sa.text('"ResendOf" IS NULL'))
        op.create_index("ix_webhook_deliveries_due", "WebhookDeliveries", ["Status", "NextAttemptAt"])
        op.create_index("ix_webhook_deliveries_event", "WebhookDeliveries", ["CompanyId", "EventId", "EndpointId"])
    if not {"Permissions", "Roles", "RolePermissions"}.issubset(existing):
        return
    metadata = sa.MetaData()
    permissions = sa.Table("Permissions", metadata, autoload_with=bind)
    roles = sa.Table("Roles", metadata, autoload_with=bind)
    links = sa.Table("RolePermissions", metadata, autoload_with=bind)
    pid = bind.execute(sa.select(permissions.c.Id).where(permissions.c.Code == "integrations.manage")).scalar()
    if pid is None:
        pid = bind.execute(permissions.insert().values(Code="integrations.manage", Name="Manage API keys and webhooks",
                            Module="Administration", CreatedAt=datetime.utcnow())).inserted_primary_key[0]
    for rid in bind.execute(sa.select(roles.c.Id).where(roles.c.Code == "admin")).scalars():
        if not bind.execute(sa.select(links.c.RoleId).where(links.c.RoleId == rid, links.c.PermissionId == pid)).first():
            bind.execute(links.insert().values(RoleId=rid, PermissionId=pid))


def downgrade():
    op.drop_table("WebhookDeliveries")
    op.drop_table("WebhookEndpoints")
    op.drop_table("APIKeys")
