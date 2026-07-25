"""add transactional vehicle checkout and return workflow

Revision ID: 20260723_0008
Revises: 20260723_0007
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260723_0008"
down_revision = "20260723_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "VehicleAssignments" not in tables:
        return

    assignment_columns = {column["name"] for column in inspector.get_columns("VehicleAssignments")}
    additions = (
        ("Destination", sa.String(length=255)),
        ("DocumentsHandedOver", sa.JSON()),
        ("VehicleStatusBeforeCheckout", sa.Integer()),
    )
    with op.batch_alter_table("VehicleAssignments") as batch:
        for name, column_type in additions:
            if name not in assignment_columns:
                batch.add_column(sa.Column(name, column_type, nullable=True))

    if "VehicleConditionRecords" not in tables:
        op.create_table(
            "VehicleConditionRecords",
            sa.Column("Id", sa.Integer(), primary_key=True),
            sa.Column("VehicleAssignmentId", sa.Integer(), nullable=False),
            sa.Column("VehicleId", sa.Integer(), nullable=False),
            sa.Column("DriverId", sa.Integer(), nullable=False),
            sa.Column("RecordType", sa.String(length=20), nullable=False),
            sa.Column("RecordedAt", sa.DateTime(), nullable=False),
            sa.Column("OdometerKm", sa.Integer(), nullable=False),
            sa.Column("EnergyLevel", sa.Integer(), nullable=True),
            sa.Column("VehicleCondition", sa.String(length=50), nullable=False),
            sa.Column("DamageDescription", sa.Text(), nullable=True),
            sa.Column("DriverComments", sa.Text(), nullable=True),
            sa.Column("ReturnInspectionRequired", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("RecordedByUserId", sa.Integer(), nullable=True),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["VehicleAssignmentId"], ["VehicleAssignments.Id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["VehicleId"], ["Vehicles.Id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["DriverId"], ["Drivers.Id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["RecordedByUserId"], ["Users.Id"], ondelete="SET NULL"),
            sa.CheckConstraint(
                '"RecordType" IN (\'Checkout\', \'Return\')',
                name="ck_vehicle_condition_records_type",
            ),
            sa.CheckConstraint('"OdometerKm" >= 0', name="ck_vehicle_condition_records_odometer"),
            sa.CheckConstraint(
                '"EnergyLevel" IS NULL OR ("EnergyLevel" >= 0 AND "EnergyLevel" <= 100)',
                name="ck_vehicle_condition_records_energy",
            ),
            sa.UniqueConstraint(
                "VehicleAssignmentId",
                "RecordType",
                name="uq_vehicle_condition_assignment_type",
            ),
        )
        op.create_index(
            "ix_vehicle_condition_records_assignment_id",
            "VehicleConditionRecords",
            ["VehicleAssignmentId"],
        )
        op.create_index(
            "ix_vehicle_condition_records_vehicle_id",
            "VehicleConditionRecords",
            ["VehicleId"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "VehicleConditionRecords" in inspector.get_table_names():
        op.drop_table("VehicleConditionRecords")
    if "VehicleAssignments" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("VehicleAssignments")}
        with op.batch_alter_table("VehicleAssignments") as batch:
            for name in ("VehicleStatusBeforeCheckout", "DocumentsHandedOver", "Destination"):
                if name in columns:
                    batch.drop_column(name)
