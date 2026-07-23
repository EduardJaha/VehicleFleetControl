"""add vehicle assignment history and event links

Revision ID: 20260723_0007
Revises: 20260719_0006
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260723_0007"
down_revision = "20260719_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required_tables = {"Users", "Vehicles", "Drivers", "VehicleReservations"}
    # Some migration tests and data-recovery workflows intentionally operate
    # on partial legacy schemas. Leave those partial schemas untouched.
    if not required_tables.issubset(tables):
        return

    if "VehicleAssignments" not in tables:
        op.create_table(
            "VehicleAssignments",
            sa.Column("Id", sa.Integer(), primary_key=True),
            sa.Column("VehicleId", sa.Integer(), nullable=False),
            sa.Column("DriverId", sa.Integer(), nullable=False),
            sa.Column("ReservationId", sa.Integer(), nullable=True),
            sa.Column("AssignedByUserId", sa.Integer(), nullable=True),
            sa.Column("EndedByUserId", sa.Integer(), nullable=True),
            sa.Column("StartDatetime", sa.DateTime(), nullable=False),
            sa.Column("EndDatetime", sa.DateTime(), nullable=True),
            sa.Column("StartOdometerKm", sa.Integer(), nullable=False),
            sa.Column("EndOdometerKm", sa.Integer(), nullable=True),
            sa.Column("StartEnergyLevel", sa.Integer(), nullable=True),
            sa.Column("EndEnergyLevel", sa.Integer(), nullable=True),
            sa.Column("Purpose", sa.String(length=255), nullable=True),
            sa.Column("Notes", sa.Text(), nullable=True),
            sa.Column("ReturnNotes", sa.Text(), nullable=True),
            sa.Column("Status", sa.String(length=50), nullable=False, server_default="Scheduled"),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("Archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ArchivedAt", sa.DateTime(), nullable=True),
            sa.Column("ArchivedBy", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["VehicleId"], ["Vehicles.Id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["DriverId"], ["Drivers.Id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["ReservationId"], ["VehicleReservations.Id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["AssignedByUserId"], ["Users.Id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["EndedByUserId"], ["Users.Id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["ArchivedBy"], ["Users.Id"], ondelete="SET NULL"),
            sa.CheckConstraint(
                '"Status" IN (\'Scheduled\', \'Active\', \'Completed\', \'Cancelled\', \'Overdue\')',
                name="ck_vehicle_assignments_status",
            ),
            sa.CheckConstraint('"StartOdometerKm" >= 0', name="ck_vehicle_assignments_start_odometer_nonnegative"),
            sa.CheckConstraint(
                '"EndOdometerKm" IS NULL OR "EndOdometerKm" >= "StartOdometerKm"',
                name="ck_vehicle_assignments_end_odometer",
            ),
            sa.CheckConstraint(
                '"StartEnergyLevel" IS NULL OR ("StartEnergyLevel" >= 0 AND "StartEnergyLevel" <= 100)',
                name="ck_vehicle_assignments_start_energy",
            ),
            sa.CheckConstraint(
                '"EndEnergyLevel" IS NULL OR ("EndEnergyLevel" >= 0 AND "EndEnergyLevel" <= 100)',
                name="ck_vehicle_assignments_end_energy",
            ),
            sa.CheckConstraint(
                '"EndDatetime" IS NULL OR "EndDatetime" >= "StartDatetime"',
                name="ck_vehicle_assignments_end_datetime",
            ),
        )

    inspector = sa.inspect(bind)
    assignment_indexes = {
        item["name"] for item in inspector.get_indexes("VehicleAssignments")
    }
    for name, columns in (
        ("ix_vehicle_assignments_vehicle_id", ["VehicleId"]),
        ("ix_vehicle_assignments_driver_id", ["DriverId"]),
        ("ix_vehicle_assignments_reservation_id", ["ReservationId"]),
        ("ix_vehicle_assignments_start_datetime", ["StartDatetime"]),
        ("ix_vehicle_assignments_status", ["Status"]),
        ("ix_vehicle_assignments_archived", ["Archived"]),
    ):
        if name not in assignment_indexes:
            op.create_index(name, "VehicleAssignments", columns)
    if "uq_vehicle_assignments_active_vehicle" not in assignment_indexes:
        op.create_index(
            "uq_vehicle_assignments_active_vehicle",
            "VehicleAssignments",
            ["VehicleId"],
            unique=True,
            sqlite_where=sa.text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = 0'),
            postgresql_where=sa.text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = false'),
        )
    if "uq_vehicle_assignments_active_driver" not in assignment_indexes:
        op.create_index(
            "uq_vehicle_assignments_active_driver",
            "VehicleAssignments",
            ["DriverId"],
            unique=True,
            sqlite_where=sa.text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = 0'),
            postgresql_where=sa.text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = false'),
        )

    for table in ("VehicleAccidents", "VehicleFuels", "Inspections"):
        inspector = sa.inspect(bind)
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "VehicleAssignmentId" not in columns:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("VehicleAssignmentId", sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    f"fk_{table.lower()}_vehicle_assignment",
                    "VehicleAssignments",
                    ["VehicleAssignmentId"],
                    ["Id"],
                    ondelete="SET NULL",
                )
                batch.create_index(
                    f"ix_{table.lower()}_vehicle_assignment_id",
                    ["VehicleAssignmentId"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("VehicleAccidents", "VehicleFuels", "Inspections"):
        if table not in inspector.get_table_names():
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "VehicleAssignmentId" in columns:
            with op.batch_alter_table(table) as batch:
                batch.drop_column("VehicleAssignmentId")
    inspector = sa.inspect(bind)
    if "VehicleAssignments" in inspector.get_table_names():
        op.drop_table("VehicleAssignments")
