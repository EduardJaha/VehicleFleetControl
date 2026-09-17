"""Add company tenancy and backfill all existing business data.

The migration deliberately uses an expand/backfill/validate/contract sequence
and Alembic batch operations so it works on PostgreSQL and SQLite.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0016"
down_revision: Union[str, None] = "20260812_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = (
    "Users", "Locations", "Departments", "CostCenters", "UserRoles", "Suppliers",
    "Vehicles", "Drivers", "VehicleAssignments", "VehicleConditionRecords",
    "Inspections", "InspectionItems", "WorkOrders", "DocumentRequirements",
    "VehiclePapers", "DocumentVersions", "VehicleServices", "ServiceBills",
    "VehicleFuels", "VehicleOperatingCosts", "VehicleAccidents", "AccidentClaims",
    "AccidentParties", "AccidentInjuries", "AccidentFiles", "VehicleReservations",
    "AuditLogs", "ImportJobs", "ImportRowResults", "Notifications", "Attachments",
    # These tables exist in installations that used the expanded-maintenance branch.
    "Vendors", "Parts", "Technicians", "InventoryTransactions", "PurchaseOrders",
    "PurchaseOrderItems", "WorkOrderParts", "WorkOrderLabor",
)


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _has_broken_foreign_keys(bind, table: str, tables: set[str], seen: set[str] | None = None) -> bool:
    """Historical migration fixtures may intentionally contain table fragments."""
    seen = set(seen or ())
    if table in seen:
        return False
    seen.add(table)
    for fk in sa.inspect(bind).get_foreign_keys(table):
        referred = fk.get("referred_table")
        if referred not in tables:
            return True
        if referred and _has_broken_foreign_keys(bind, referred, tables, seen):
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    if "Companies" not in tables:
        op.create_table(
            "Companies",
            sa.Column("Id", sa.Integer(), primary_key=True),
            sa.Column("Name", sa.String(255), nullable=False),
            sa.Column("Slug", sa.String(100), nullable=False),
            sa.Column("IsActive", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("Slug", name="uq_companies_slug"),
        )
        op.create_index("ix_companies_slug", "Companies", ["Slug"])
    bind.execute(sa.text(
        'INSERT INTO "Companies" ("Id", "Name", "Slug", "IsActive", "CreatedAt", "UpdatedAt") '
        'SELECT 1, :name, :slug, :active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP '
        'WHERE NOT EXISTS (SELECT 1 FROM "Companies" WHERE "Id" = 1)'
    ), {"name": "Default Company", "slug": "default-company", "active": True})

    tables = _tables(bind)
    present = [table for table in TENANT_TABLES if table in tables]
    broken_tables = {
        table for table in present
        if bind.dialect.name == "sqlite" and _has_broken_foreign_keys(bind, table, tables)
    }
    for table in present:
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        if "CompanyId" not in columns:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("CompanyId", sa.Integer(), nullable=True))

    for table in present:
        bind.execute(sa.text(f'UPDATE "{table}" SET "CompanyId" = 1 WHERE "CompanyId" IS NULL'))

    unassigned = {
        table: bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}" WHERE "CompanyId" IS NULL')).scalar_one()
        for table in present
    }
    failures = {table: count for table, count in unassigned.items() if count}
    if failures:
        raise RuntimeError(f"Tenant backfill validation failed: {failures}")

    for table in present:
        # A few supported historical snapshots intentionally omit referenced
        # tables. They can be backfilled, but SQLite cannot batch-rebuild such
        # a fragment because reflection requires every FK target to exist.
        if table in broken_tables:
            continue
        inspector = sa.inspect(bind)
        foreign_keys = inspector.get_foreign_keys(table)
        constraint_name = f"fk_{table.lower()}_company_id"
        has_company_fk = any(
            fk.get("constrained_columns") == ["CompanyId"] and fk.get("referred_table") == "Companies"
            for fk in foreign_keys
        )
        company_column = next(column for column in inspector.get_columns(table) if column["name"] == "CompanyId")
        if company_column.get("nullable") or not has_company_fk:
            with op.batch_alter_table(table) as batch:
                if company_column.get("nullable"):
                    batch.alter_column("CompanyId", existing_type=sa.Integer(), nullable=False)
                if not has_company_fk:
                    batch.create_foreign_key(constraint_name, "Companies", ["CompanyId"], ["Id"], ondelete="RESTRICT")
        has_company_index = any(index.get("column_names") == ["CompanyId"] for index in sa.inspect(bind).get_indexes(table))
        if not has_company_index:
            with op.batch_alter_table(table) as batch:
                batch.create_index(f"ix_{table.lower()}_company_id", ["CompanyId"])

    if "CompanySettings" not in _tables(bind):
        op.create_table(
            "CompanySettings",
            sa.Column("Id", sa.Integer(), primary_key=True),
            sa.Column("CompanyId", sa.Integer(), sa.ForeignKey("Companies.Id", ondelete="CASCADE"), nullable=False),
            sa.Column("LogoPath", sa.String(500), nullable=True),
            sa.Column("Address", sa.Text(), nullable=True),
            sa.Column("DefaultLanguage", sa.String(5), nullable=False, server_default="en"),
            sa.Column("Timezone", sa.String(100), nullable=False, server_default="UTC"),
            sa.Column("Currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("NotificationRules", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("CompanyId", name="uq_company_settings_company"),
        )
        op.create_index("ix_companysettings_company_id", "CompanySettings", ["CompanyId"])
    bind.execute(sa.text(
        'INSERT INTO "CompanySettings" ("CompanyId", "DefaultLanguage", "Timezone", "Currency", "NotificationRules", "CreatedAt", "UpdatedAt") '
        "SELECT 1, 'en', 'UTC', 'EUR', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        'WHERE NOT EXISTS (SELECT 1 FROM "CompanySettings" WHERE "CompanyId" = 1)'
    ))

    if "CompanyUsers" not in _tables(bind):
        op.create_table(
            "CompanyUsers",
            sa.Column("Id", sa.Integer(), primary_key=True),
            sa.Column("CompanyId", sa.Integer(), sa.ForeignKey("Companies.Id", ondelete="CASCADE"), nullable=False),
            sa.Column("UserId", sa.Integer(), sa.ForeignKey("Users.Id", ondelete="CASCADE"), nullable=False),
            sa.Column("Role", sa.String(50), nullable=False, server_default="viewer"),
            sa.Column("IsActive", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("IsDefault", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("CompanyId", "UserId", name="uq_company_users_company_user"),
        )
        op.create_index("ix_companyusers_company_id", "CompanyUsers", ["CompanyId"])
        op.create_index("ix_companyusers_user_id", "CompanyUsers", ["UserId"])
    if "Users" in present:
        bind.execute(sa.text(
            'INSERT INTO "CompanyUsers" ("CompanyId", "UserId", "Role", "IsActive", "IsDefault", "CreatedAt") '
            'SELECT "CompanyId", "Id", "Role", "IsActive", :default, CURRENT_TIMESTAMP FROM "Users" '
            'WHERE NOT EXISTS (SELECT 1 FROM "CompanyUsers" cu WHERE cu."CompanyId" = "Users"."CompanyId" AND cu."UserId" = "Users"."Id")'
        ), {"default": True})

    if bind.dialect.name == "postgresql":
        # An explicit legacy Id does not advance a PostgreSQL identity sequence.
        bind.execute(sa.text("SELECT setval(pg_get_serial_sequence('\"Companies\"', 'Id'), (SELECT MAX(\"Id\") FROM \"Companies\"))"))

    _replace_company_aware_uniques(bind, set(present), broken_tables)
    _replace_active_assignment_indexes(bind, set(present), broken_tables)


def _replace_company_aware_uniques(bind, present: set[str], broken_tables: set[str]) -> None:
    replacements = {
        "Locations": (("uq_locations_code",), "uq_locations_company_code", ["CompanyId", "Code"]),
        "Departments": (("uq_departments_code",), "uq_departments_company_code", ["CompanyId", "Code"]),
        "CostCenters": (("uq_cost_centers_code",), "uq_cost_centers_company_code", ["CompanyId", "Code"]),
        "UserRoles": (("uq_user_roles_user_role",), "uq_user_roles_company_user_role", ["CompanyId", "UserId", "RoleId"]),
        "Suppliers": (("uq_suppliers_name",), "uq_suppliers_company_name", ["CompanyId", "Name"]),
        "Vehicles": (("uq_vehicles_registration_country_license_plate_normalized",), "uq_vehicles_company_registration_country_license_plate_normalized", ["CompanyId", "RegistrationCountry", "LicensePlateNormalized"]),
        "Drivers": (("uq_drivers_email", "uq_drivers_employee_number", "uq_drivers_license_number"), None, None),
        "AccidentClaims": (("uq_accident_claims_claim_number",), "uq_accident_claims_company_claim_number", ["CompanyId", "ClaimNumber"]),
        "Notifications": (("uq_notifications_deduplication_key",), "uq_notifications_company_deduplication_key", ["CompanyId", "DeduplicationKey"]),
    }
    for table, (old_names, new_name, columns) in replacements.items():
        if table not in present:
            continue
        if table in broken_tables:
            continue
        existing = {item.get("name") for item in sa.inspect(bind).get_unique_constraints(table)}
        with op.batch_alter_table(table) as batch:
            for name in old_names:
                if name in existing:
                    batch.drop_constraint(name, type_="unique")
            rendered_name = (bind.dialect.identifier_preparer.truncate_and_render_constraint_name(
                sa.schema.conv(new_name), _alembic_quote=False) if new_name else None)
            if new_name and rendered_name not in existing:
                batch.create_unique_constraint(sa.schema.conv(new_name), columns)
            if table == "Drivers":
                for name, driver_columns in (
                    ("uq_drivers_company_email", ["CompanyId", "Email"]),
                    ("uq_drivers_company_employee_number", ["CompanyId", "EmployeeNumber"]),
                    ("uq_drivers_company_license_number", ["CompanyId", "LicenseNumber"]),
                    ("uq_drivers_company_user", ["CompanyId", "UserId"]),
                ):
                    if name not in existing:
                        batch.create_unique_constraint(name, driver_columns)


def _replace_active_assignment_indexes(bind, present: set[str], broken_tables: set[str]) -> None:
    table = "VehicleAssignments"
    if table not in present or table in broken_tables:
        return
    existing = {item.get("name") for item in sa.inspect(bind).get_indexes(table)}
    for name, owned_column in (
        ("uq_vehicle_assignments_active_vehicle", "VehicleId"),
        ("uq_vehicle_assignments_active_driver", "DriverId"),
    ):
        if name in existing:
            op.drop_index(name, table_name=table)
        op.create_index(
            name,
            table,
            ["CompanyId", owned_column],
            unique=True,
            sqlite_where=sa.text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = 0'),
            postgresql_where=sa.text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = false'),
        )


def downgrade() -> None:
    # Removing tenant ownership would merge independent customer data and can
    # violate the old global unique constraints. Require an explicit data export
    # and consolidation procedure instead of offering a destructive downgrade.
    raise RuntimeError(
        "Cannot downgrade multi-company tenancy automatically; company data could be merged. "
        "KWH and other later-revision data must also remain protected."
    )
