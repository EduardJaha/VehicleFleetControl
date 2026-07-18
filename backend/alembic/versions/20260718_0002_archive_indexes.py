"""Add archive lookup indexes and enforce service timestamps.

Revision ID: 20260718_0002
Revises: 20260718_0001
Create Date: 2026-07-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260718_0002"
down_revision: Union[str, None] = "20260718_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "Vehicles", "Drivers", "Inspections", "WorkOrders", "VehiclePapers",
    "VehicleServices", "VehicleFuels", "VehicleAccidents", "VehicleReservations",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in TABLES:
        if table not in inspector.get_table_names():
            continue
        existing = {index["name"] for index in inspector.get_indexes(table)}
        name = f"ix_{table}_Archived"
        if name not in existing:
            op.create_index(name, table, ["Archived"])

    # The previous additive migration already backfilled these from ServiceDate.
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("VehicleServices")}
    if columns["CreatedAt"]["nullable"] or columns["UpdatedAt"]["nullable"]:
        bind.execute(sa.text(
            'UPDATE "VehicleServices" SET "CreatedAt" = COALESCE("CreatedAt", "ServiceDate"), '
            '"UpdatedAt" = COALESCE("UpdatedAt", "ServiceDate")'
        ))
        with op.batch_alter_table("VehicleServices") as batch:
            batch.alter_column("CreatedAt", existing_type=sa.DateTime(), nullable=False)
            batch.alter_column("UpdatedAt", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in TABLES:
        existing = {index["name"] for index in inspector.get_indexes(table)}
        name = f"ix_{table}_Archived"
        if name in existing:
            op.drop_index(name, table_name=table)
