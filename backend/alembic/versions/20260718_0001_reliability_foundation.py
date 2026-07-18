"""Reliability foundation: numeric types, archiving, audit, notifications, files.

Revision ID: 20260718_0001
Revises:
Create Date: 2026-07-18
"""

from decimal import Decimal, InvalidOperation
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.session import Base
from app.models import Attachment, AuditLog, Notification

revision: str = "20260718_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARCHIVABLE_TABLES = (
    "Vehicles",
    "Drivers",
    "Inspections",
    "WorkOrders",
    "VehiclePapers",
    "VehicleServices",
    "VehicleFuels",
    "VehicleAccidents",
    "VehicleReservations",
)

NUMERIC_FIELDS = {
    "WorkOrders": {
        "LaborCost": (sa.String(), sa.Numeric(12, 2), True),
        "PartsCost": (sa.String(), sa.Numeric(12, 2), True),
        "TotalCost": (sa.String(), sa.Numeric(12, 2), True),
    },
    "VehicleServices": {
        "Cost": (sa.String(), sa.Numeric(12, 2), True),
        "LaborCost": (sa.String(), sa.Numeric(12, 2), True),
        "PartsCost": (sa.String(), sa.Numeric(12, 2), True),
    },
    "VehicleFuels": {
        "Liters": (sa.String(), sa.Numeric(12, 3), False),
        "CostPerLiter": (sa.String(), sa.Numeric(12, 3), False),
        "TotalCost": (sa.String(), sa.Numeric(12, 2), False),
    },
}


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _validate_and_normalize_numeric_data(bind, inspector: sa.Inspector) -> None:
    invalid: list[str] = []
    for table, fields in NUMERIC_FIELDS.items():
        if table not in inspector.get_table_names():
            continue
        columns = _column_names(inspector, table)
        for field, (_, _, nullable) in fields.items():
            if field not in columns:
                continue
            rows = bind.execute(
                sa.text(f'SELECT "Id", "{field}" FROM "{table}" WHERE "{field}" IS NOT NULL')
            ).all()
            for row_id, raw in rows:
                text_value = str(raw).strip()
                if text_value == "":
                    if table == "VehicleFuels" and field == "Liters":
                        invalid.append(f"{table}.Id={row_id} {field}=blank")
                    else:
                        replacement = None if nullable else Decimal("0")
                        bind.execute(
                            sa.text(f'UPDATE "{table}" SET "{field}" = :value WHERE "Id" = :id'),
                            {"value": replacement, "id": row_id},
                        )
                    continue
                try:
                    value = Decimal(text_value)
                except (InvalidOperation, ValueError):
                    invalid.append(f"{table}.Id={row_id} {field}={raw!r}")
                    continue
                if not value.is_finite() or value < 0:
                    invalid.append(f"{table}.Id={row_id} {field}={raw!r}")
            if table == "VehicleFuels" and not nullable:
                replacement = "NULL" if field == "Liters" else "0"
                if replacement == "0":
                    bind.execute(sa.text(
                        f'UPDATE "{table}" SET "{field}" = 0 WHERE "{field}" IS NULL'
                    ))
    if invalid:
        details = "\n".join(f"- {item}" for item in invalid)
        raise RuntimeError(
            "Numeric migration stopped because invalid legacy values were found:\n"
            f"{details}\nCorrect these values and run 'alembic upgrade head' again."
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "Users" not in inspector.get_table_names():
        Base.metadata.create_all(bind=bind)
        return

    _validate_and_normalize_numeric_data(bind, inspector)

    for table in ARCHIVABLE_TABLES:
        inspector = sa.inspect(bind)
        if table not in inspector.get_table_names():
            continue
        columns = _column_names(inspector, table)
        with op.batch_alter_table(table) as batch:
            if "Archived" not in columns:
                batch.add_column(sa.Column("Archived", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "ArchivedAt" not in columns:
                batch.add_column(sa.Column("ArchivedAt", sa.DateTime(), nullable=True))
            if "ArchivedBy" not in columns:
                batch.add_column(sa.Column("ArchivedBy", sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    f"fk_{table.lower()}_archived_by_users",
                    "Users",
                    ["ArchivedBy"],
                    ["Id"],
                    ondelete="SET NULL",
                )

    inspector = sa.inspect(bind)
    for table, fields in NUMERIC_FIELDS.items():
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        with op.batch_alter_table(table) as batch:
            for field, (legacy_type, target_type, nullable) in fields.items():
                if field in columns and not isinstance(columns[field]["type"], sa.Numeric):
                    dialect_options = {}
                    if bind.dialect.name == "postgresql":
                        dialect_options["postgresql_using"] = f"""NULLIF(TRIM("{field}"), '')::numeric"""
                    batch.alter_column(
                        field,
                        existing_type=legacy_type,
                        type_=target_type,
                        existing_nullable=nullable,
                        nullable=nullable,
                        **dialect_options,
                    )

    AuditLog.__table__.create(bind=bind, checkfirst=True)
    Notification.__table__.create(bind=bind, checkfirst=True)
    Attachment.__table__.create(bind=bind, checkfirst=True)

    inspector = sa.inspect(bind)
    service_indexes = {item["name"] for item in inspector.get_indexes("VehicleServices")}
    if "uq_vehicle_services_work_order" not in service_indexes:
        op.create_index(
            "uq_vehicle_services_work_order",
            "VehicleServices",
            ["WorkOrderId"],
            unique=True,
            sqlite_where=sa.text('"WorkOrderId" IS NOT NULL'),
            postgresql_where=sa.text('"WorkOrderId" IS NOT NULL'),
        )


def downgrade() -> None:
    bind = op.get_bind()
    Attachment.__table__.drop(bind=bind, checkfirst=True)
    Notification.__table__.drop(bind=bind, checkfirst=True)
    AuditLog.__table__.drop(bind=bind, checkfirst=True)
    # Numeric-to-string and archive-column reversal are intentionally omitted:
    # preserving production data is safer than a lossy downgrade.
