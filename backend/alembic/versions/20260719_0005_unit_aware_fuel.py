"""Add unit-aware Fuel quantities while preserving legacy values.

Revision ID: 20260719_0005
Revises: 20260718_0004
Create Date: 2026-07-19

The downgrade intentionally refuses to proceed while kWh records exist. A
kilowatt-hour value cannot be copied back into a column named Liters without
misrepresenting historical data.
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.session import Base

revision: str = "20260719_0005"
down_revision: Union[str, None] = "20260718_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENERGY_UNIT_INDEX = "ix_vehicle_fuels_energy_unit"
QUANTITY_CHECK = "ck_vehicle_fuels_quantity_nonnegative"
UNIT_COST_CHECK = "ck_vehicle_fuels_unit_cost_nonnegative"
ENERGY_UNIT_CHECK = "ck_vehicle_fuels_energy_unit"


def _column_names(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _report_electric_conversions(bind, rows) -> None:
    if not rows:
        print("\n[fuel-unit migration] No historical Electric Fuel records require review.")
        return

    print("\n[fuel-unit migration] Historical Electric Fuel records converted to KWH and marked for review:")
    for row in rows:
        print(
            "  - Fuel Id={fuel_id}, Vehicle Id={vehicle_id}, Licence Plate={plate}, "
            "Old Value={old_value}, New Unit=KWH".format(
                fuel_id=row["fuel_id"],
                vehicle_id=row["vehicle_id"],
                plate=row["license_plate"],
                old_value=row["old_value"],
            )
        )

    if "AuditLogs" not in sa.inspect(bind).get_table_names():
        return
    for row in rows:
        new_values = json.dumps({
            "vehicle_id": row["vehicle_id"],
            "fuel_type": "Electric",
            "quantity": str(row["old_value"]),
            "unit": "KWH",
            "unit_review_required": True,
        })
        bind.execute(sa.text(
            'INSERT INTO "AuditLogs" '
            '("Username", "Action", "EntityType", "EntityId", "NewValues", "Description", "CreatedAt") '
            "VALUES ('System', 'Historical Electric record migrated to kWh', 'VehicleFuel', "
            ":fuel_id, :new_values, :description, CURRENT_TIMESTAMP)"
        ), {
            "fuel_id": row["fuel_id"],
            "new_values": new_values,
            "description": (
                f"Historical Electric Fuel record #{row['fuel_id']} for "
                f"{row['license_plate']} was converted to KWH and requires review."
            ),
        })


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "VehicleFuels" not in inspector.get_table_names():
        Base.metadata.create_all(bind=bind)
        return

    columns = _column_names(bind, "VehicleFuels")
    with op.batch_alter_table("VehicleFuels") as batch:
        if "Quantity" not in columns:
            batch.add_column(sa.Column("Quantity", sa.Numeric(12, 3), nullable=True))
        if "EnergyUnit" not in columns:
            batch.add_column(sa.Column("EnergyUnit", sa.String(8), nullable=True))
        if "UnitCost" not in columns:
            batch.add_column(sa.Column("UnitCost", sa.Numeric(12, 4), nullable=True))
        if "UnitReviewRequired" not in columns:
            batch.add_column(sa.Column(
                "UnitReviewRequired",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ))

    electric_rows = bind.execute(sa.text(
        'SELECT f."Id" AS fuel_id, f."VehicleId" AS vehicle_id, '
        'v."LicensePlate" AS license_plate, f."Liters" AS old_value '
        'FROM "VehicleFuels" f '
        'JOIN "Vehicles" v ON v."Id" = f."VehicleId" '
        "WHERE LOWER(TRIM(f.\"FuelType\")) = 'electric' "
        'ORDER BY f."Id"'
    )).mappings().all()

    bind.execute(sa.text(
        'UPDATE "VehicleFuels" '
        'SET "Quantity" = COALESCE("Quantity", "Liters"), '
        '"UnitCost" = COALESCE("UnitCost", "CostPerLiter"), '
        '"EnergyUnit" = COALESCE("EnergyUnit", '
        "CASE WHEN LOWER(TRIM(\"FuelType\")) = 'electric' THEN 'KWH' ELSE 'L' END), "
        '"UnitReviewRequired" = CASE '
        "WHEN LOWER(TRIM(\"FuelType\")) = 'electric' THEN true "
        'ELSE COALESCE("UnitReviewRequired", false) END'
    ))

    missing = bind.execute(sa.text(
        'SELECT "Id" FROM "VehicleFuels" '
        'WHERE "Quantity" IS NULL OR "UnitCost" IS NULL OR "EnergyUnit" IS NULL'
    )).scalars().all()
    if missing:
        raise RuntimeError(
            "Fuel unit migration stopped because generic fields could not be "
            f"backfilled for Fuel record Ids: {', '.join(map(str, missing))}."
        )

    invalid = bind.execute(sa.text(
        'SELECT "Id" FROM "VehicleFuels" '
        'WHERE "Quantity" < 0 OR "UnitCost" < 0 '
        'OR "EnergyUnit" NOT IN (\'L\', \'KWH\')'
    )).scalars().all()
    if invalid:
        raise RuntimeError(
            "Fuel unit migration stopped because invalid historical values were "
            f"found for Fuel record Ids: {', '.join(map(str, invalid))}."
        )

    constraints = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_check_constraints("VehicleFuels")
    }
    with op.batch_alter_table("VehicleFuels") as batch:
        batch.alter_column(
            "Quantity",
            existing_type=sa.Numeric(12, 3),
            nullable=False,
        )
        batch.alter_column(
            "EnergyUnit",
            existing_type=sa.String(8),
            nullable=False,
        )
        batch.alter_column(
            "UnitCost",
            existing_type=sa.Numeric(12, 4),
            nullable=False,
        )
        batch.alter_column(
            "Liters",
            existing_type=sa.Numeric(12, 3),
            nullable=True,
        )
        batch.alter_column(
            "CostPerLiter",
            existing_type=sa.Numeric(12, 3),
            nullable=True,
        )
        if QUANTITY_CHECK not in constraints:
            batch.create_check_constraint(QUANTITY_CHECK, '"Quantity" >= 0')
        if UNIT_COST_CHECK not in constraints:
            batch.create_check_constraint(UNIT_COST_CHECK, '"UnitCost" >= 0')
        if ENERGY_UNIT_CHECK not in constraints:
            batch.create_check_constraint(
                ENERGY_UNIT_CHECK,
                '"EnergyUnit" IN (\'L\', \'KWH\')',
            )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("VehicleFuels")}
    if ENERGY_UNIT_INDEX not in indexes:
        op.create_index(ENERGY_UNIT_INDEX, "VehicleFuels", ["EnergyUnit"])

    _report_electric_conversions(bind, electric_rows)


def downgrade() -> None:
    bind = op.get_bind()
    if "VehicleFuels" not in sa.inspect(bind).get_table_names():
        return
    columns = _column_names(bind, "VehicleFuels")
    if "EnergyUnit" not in columns:
        return

    kwh_count = bind.execute(sa.text(
        'SELECT COUNT(*) FROM "VehicleFuels" WHERE "EnergyUnit" = \'KWH\''
    )).scalar_one()
    if kwh_count:
        raise RuntimeError(
            "Cannot downgrade the unit-aware Fuel migration while KWH records "
            "exist. Export or explicitly correct those records first; copying "
            "kWh into Liters would corrupt their meaning."
        )

    bind.execute(sa.text(
        'UPDATE "VehicleFuels" '
        'SET "Liters" = COALESCE("Liters", "Quantity"), '
        '"CostPerLiter" = COALESCE("CostPerLiter", "UnitCost")'
    ))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("VehicleFuels")}
    if ENERGY_UNIT_INDEX in indexes:
        op.drop_index(ENERGY_UNIT_INDEX, table_name="VehicleFuels")

    constraints = {
        constraint["name"]
        for constraint in sa.inspect(bind).get_check_constraints("VehicleFuels")
    }
    with op.batch_alter_table("VehicleFuels") as batch:
        for name in (QUANTITY_CHECK, UNIT_COST_CHECK, ENERGY_UNIT_CHECK):
            if name in constraints:
                batch.drop_constraint(name, type_="check")
        batch.alter_column(
            "Liters",
            existing_type=sa.Numeric(12, 3),
            nullable=False,
        )
        batch.alter_column(
            "CostPerLiter",
            existing_type=sa.Numeric(12, 3),
            nullable=False,
        )
        for name in ("UnitReviewRequired", "UnitCost", "EnergyUnit", "Quantity"):
            if name in columns:
                batch.drop_column(name)
