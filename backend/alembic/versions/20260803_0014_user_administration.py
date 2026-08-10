"""Add granular authorization, user administration, and organization master data."""

from datetime import datetime
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.authorization import DEFAULT_ROLE_NAMES, DEFAULT_ROLE_PERMISSIONS, PERMISSION_CATALOG, seed_authorization_defaults

revision: str = "20260803_0014"
down_revision: Union[str, None] = "20260803_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _code(value: str, fallback: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_").upper()
    return (result or fallback)[:50]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("Permissions"):
        session = Session(bind=bind)
        seed_authorization_defaults(session, commit=False)
        session.close()
        return

    op.create_table(
        "Permissions",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("Code", sa.String(100), nullable=False),
        sa.Column("Name", sa.String(150), nullable=False),
        sa.Column("Description", sa.Text(), nullable=True),
        sa.Column("Module", sa.String(50), nullable=False),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("Code", name="uq_permissions_code"),
    )
    op.create_index("ix_permissions_code", "Permissions", ["Code"])
    op.create_index("ix_permissions_module", "Permissions", ["Module"])
    op.create_table(
        "Roles",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("Code", sa.String(50), nullable=False),
        sa.Column("Name", sa.String(100), nullable=False),
        sa.Column("Description", sa.Text(), nullable=True),
        sa.Column("IsSystem", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("IsActive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("Code", name="uq_roles_code"),
    )
    op.create_index("ix_roles_code", "Roles", ["Code"])
    op.create_table(
        "Locations",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("Code", sa.String(50), nullable=False),
        sa.Column("Name", sa.String(150), nullable=False),
        sa.Column("IsActive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("Code", name="uq_locations_code"),
    )
    op.create_index("ix_locations_code", "Locations", ["Code"])
    op.create_table(
        "Departments",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("Code", sa.String(50), nullable=False),
        sa.Column("Name", sa.String(150), nullable=False),
        sa.Column("IsActive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("Code", name="uq_departments_code"),
    )
    op.create_index("ix_departments_code", "Departments", ["Code"])
    op.create_table(
        "CostCenters",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("Code", sa.String(50), nullable=False),
        sa.Column("Name", sa.String(150), nullable=False),
        sa.Column("IsActive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("Code", name="uq_cost_centers_code"),
    )
    op.create_index("ix_cost_centers_code", "CostCenters", ["Code"])
    op.create_table(
        "RolePermissions",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("RoleId", sa.Integer(), sa.ForeignKey("Roles.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("PermissionId", sa.Integer(), sa.ForeignKey("Permissions.Id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("RoleId", "PermissionId", name="uq_role_permissions_role_permission"),
    )
    op.create_index("ix_role_permissions_role_id", "RolePermissions", ["RoleId"])
    op.create_index("ix_role_permissions_permission_id", "RolePermissions", ["PermissionId"])
    op.create_table(
        "UserRoles",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("UserId", sa.Integer(), sa.ForeignKey("Users.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("RoleId", sa.Integer(), sa.ForeignKey("Roles.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("LocationId", sa.Integer(), sa.ForeignKey("Locations.Id", ondelete="SET NULL"), nullable=True),
        sa.Column("DepartmentId", sa.Integer(), sa.ForeignKey("Departments.Id", ondelete="SET NULL"), nullable=True),
        sa.Column("CostCenterId", sa.Integer(), sa.ForeignKey("CostCenters.Id", ondelete="SET NULL"), nullable=True),
        sa.Column("OwnRecordsOnly", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("UserId", "RoleId", name="uq_user_roles_user_role"),
    )
    op.create_index("ix_user_roles_user_id", "UserRoles", ["UserId"])
    op.create_index("ix_user_roles_role_id", "UserRoles", ["RoleId"])

    has_users = inspector.has_table("Users")
    has_vehicles = inspector.has_table("Vehicles")
    has_drivers = inspector.has_table("Drivers")
    if has_users:
        op.add_column("Users", sa.Column("LastLoginAt", sa.DateTime(), nullable=True))
        op.add_column("Users", sa.Column("SessionVersion", sa.Integer(), nullable=False, server_default="0"))
        op.add_column("Users", sa.Column("PasswordResetRequired", sa.Boolean(), nullable=False, server_default=sa.false()))
    if has_vehicles:
        location_column = sa.Column("LocationId", sa.Integer(), nullable=True)
        if bind.dialect.name != "sqlite":
            location_column.append_foreign_key(sa.ForeignKey("Locations.Id", ondelete="SET NULL"))
        op.add_column("Vehicles", location_column)
        op.create_index("ix_vehicles_location_id", "Vehicles", ["LocationId"])
    if has_drivers:
        department_column = sa.Column("DepartmentId", sa.Integer(), nullable=True)
        cost_center_column = sa.Column("CostCenterId", sa.Integer(), nullable=True)
        if bind.dialect.name != "sqlite":
            department_column.append_foreign_key(sa.ForeignKey("Departments.Id", ondelete="SET NULL"))
            cost_center_column.append_foreign_key(sa.ForeignKey("CostCenters.Id", ondelete="SET NULL"))
        op.add_column("Drivers", department_column)
        op.add_column("Drivers", cost_center_column)
        op.create_index("ix_drivers_department_id", "Drivers", ["DepartmentId"])
        op.create_index("ix_drivers_cost_center_id", "Drivers", ["CostCenterId"])

    now = datetime.utcnow()
    permissions_table = sa.table("Permissions", sa.column("Code"), sa.column("Name"), sa.column("Description"), sa.column("Module"), sa.column("CreatedAt"))
    op.bulk_insert(permissions_table, [
        {"Code": code, "Name": code, "Description": description, "Module": module, "CreatedAt": now}
        for code, (module, description) in PERMISSION_CATALOG.items()
    ])
    roles_table = sa.table("Roles", sa.column("Code"), sa.column("Name"), sa.column("IsSystem"), sa.column("IsActive"), sa.column("CreatedAt"), sa.column("UpdatedAt"))
    op.bulk_insert(roles_table, [
        {"Code": code, "Name": name, "IsSystem": True, "IsActive": True, "CreatedAt": now, "UpdatedAt": now}
        for code, name in DEFAULT_ROLE_NAMES.items()
    ])
    role_ids = dict(bind.execute(sa.text('SELECT "Code", "Id" FROM "Roles"')).all())
    permission_ids = dict(bind.execute(sa.text('SELECT "Code", "Id" FROM "Permissions"')).all())
    role_permissions_table = sa.table("RolePermissions", sa.column("RoleId"), sa.column("PermissionId"))
    op.bulk_insert(role_permissions_table, [
        {"RoleId": role_ids[role], "PermissionId": permission_ids[permission]}
        for role, permissions in DEFAULT_ROLE_PERMISSIONS.items() for permission in permissions
    ])
    user_roles_table = sa.table("UserRoles", sa.column("UserId"), sa.column("RoleId"), sa.column("OwnRecordsOnly"), sa.column("CreatedAt"))
    existing_users = bind.execute(sa.text('SELECT "Id", "Role" FROM "Users"')).all() if has_users else []
    op.bulk_insert(user_roles_table, [
        {"UserId": user_id, "RoleId": role_ids[role], "OwnRecordsOnly": False, "CreatedAt": now}
        for user_id, role in existing_users if role in role_ids
    ])

    locations: dict[str, int] = {}
    vehicle_locations = bind.execute(sa.text('SELECT DISTINCT "VehicleLocation" FROM "Vehicles" WHERE "VehicleLocation" IS NOT NULL AND TRIM("VehicleLocation") <> \'\'')).all() if has_vehicles else []
    for index, (name,) in enumerate(vehicle_locations, 1):
        base = _code(name, f"LOCATION_{index}")
        code = base
        suffix = 2
        while code in locations:
            code = f"{base[:46]}_{suffix}"
            suffix += 1
        bind.execute(sa.text('INSERT INTO "Locations" ("Code", "Name", "IsActive", "CreatedAt", "UpdatedAt") VALUES (:code, :name, :active, :now, :now)'), {"code": code, "name": name, "active": True, "now": now})
        row_id = bind.execute(sa.text('SELECT "Id" FROM "Locations" WHERE "Code" = :code'), {"code": code}).scalar_one()
        locations[code] = row_id
        bind.execute(sa.text('UPDATE "Vehicles" SET "LocationId" = :id WHERE "VehicleLocation" = :name'), {"id": row_id, "name": name})

    departments: dict[str, int] = {}
    driver_departments = bind.execute(sa.text('SELECT DISTINCT "Department" FROM "Drivers" WHERE "Department" IS NOT NULL AND TRIM("Department") <> \'\'')).all() if has_drivers else []
    for index, (name,) in enumerate(driver_departments, 1):
        base = _code(name, f"DEPARTMENT_{index}")
        code = base
        suffix = 2
        while code in departments:
            code = f"{base[:46]}_{suffix}"
            suffix += 1
        bind.execute(sa.text('INSERT INTO "Departments" ("Code", "Name", "IsActive", "CreatedAt", "UpdatedAt") VALUES (:code, :name, :active, :now, :now)'), {"code": code, "name": name, "active": True, "now": now})
        row_id = bind.execute(sa.text('SELECT "Id" FROM "Departments" WHERE "Code" = :code'), {"code": code}).scalar_one()
        departments[code] = row_id
        bind.execute(sa.text('UPDATE "Drivers" SET "DepartmentId" = :id WHERE "Department" = :name'), {"id": row_id, "name": name})


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("Drivers"):
        op.drop_index("ix_drivers_cost_center_id", table_name="Drivers")
        op.drop_index("ix_drivers_department_id", table_name="Drivers")
        op.drop_column("Drivers", "CostCenterId")
        op.drop_column("Drivers", "DepartmentId")
    if inspector.has_table("Vehicles"):
        op.drop_index("ix_vehicles_location_id", table_name="Vehicles")
        op.drop_column("Vehicles", "LocationId")
    if inspector.has_table("Users"):
        op.drop_column("Users", "PasswordResetRequired")
        op.drop_column("Users", "SessionVersion")
        op.drop_column("Users", "LastLoginAt")
    op.drop_table("UserRoles")
    op.drop_table("RolePermissions")
    op.drop_index("ix_cost_centers_code", table_name="CostCenters")
    op.drop_table("CostCenters")
    op.drop_index("ix_departments_code", table_name="Departments")
    op.drop_table("Departments")
    op.drop_index("ix_locations_code", table_name="Locations")
    op.drop_table("Locations")
    op.drop_index("ix_roles_code", table_name="Roles")
    op.drop_table("Roles")
    op.drop_index("ix_permissions_module", table_name="Permissions")
    op.drop_index("ix_permissions_code", table_name="Permissions")
    op.drop_table("Permissions")
