"""Mobile retry receipts and narrowly scoped driver self-service grants."""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = "20260917_0022"
down_revision = "20260915_0021"
branch_labels = None
depends_on = None

GRANTS = {
    "assignments.self_service": ("Assignments", "Check out and return own assigned vehicles"),
    "accidents.report": ("Accidents", "Report accidents for own vehicles"),
    "maintenance.report_issue": ("Maintenance", "Report issues for own vehicles"),
}

def upgrade():
    bind = op.get_bind()
    if "MobileOperations" not in sa.inspect(bind).get_table_names():
        op.create_table("MobileOperations",
            sa.Column("Id", sa.Integer(), primary_key=True),
            sa.Column("CompanyId", sa.Integer(), sa.ForeignKey("Companies.Id"), nullable=False),
            sa.Column("UserId", sa.Integer(), sa.ForeignKey("Users.Id"), nullable=False),
            sa.Column("OperationKey", sa.String(100), nullable=False),
            sa.Column("PayloadHash", sa.String(64), nullable=False),
            sa.Column("Result", sa.JSON(), nullable=True),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("CompanyId", "UserId", "OperationKey", name="uq_mobile_operation"))
        op.create_index("ix_MobileOperations_CompanyId", "MobileOperations", ["CompanyId"])
    # Minimal historical bridge fixtures may not have authorization tables yet.
    if not {"Permissions", "Roles", "RolePermissions"}.issubset(sa.inspect(bind).get_table_names()):
        return
    metadata = sa.MetaData()
    permissions = sa.Table("Permissions", metadata, autoload_with=bind)
    roles = sa.Table("Roles", metadata, autoload_with=bind)
    links = sa.Table("RolePermissions", metadata, autoload_with=bind)
    for code, (module, name) in GRANTS.items():
        pid = bind.execute(sa.select(permissions.c.Id).where(permissions.c.Code == code)).scalar()
        if pid is None:
            pid = bind.execute(permissions.insert().values(Code=code, Name=name, Module=module, CreatedAt=datetime.utcnow())).inserted_primary_key[0]
        for rid in bind.execute(sa.select(roles.c.Id).where(roles.c.Code.in_(["driver", "admin", "fleet_manager"])) ).scalars():
            if not bind.execute(sa.select(links.c.RoleId).where(links.c.RoleId == rid, links.c.PermissionId == pid)).first():
                bind.execute(links.insert().values(RoleId=rid, PermissionId=pid))

def downgrade():
    op.drop_table("MobileOperations")
    # Permission definitions are retained to preserve customized grants.
