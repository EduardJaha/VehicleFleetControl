"""clean up scheduled assignments duplicated by legacy checkout behavior

Revision ID: 20260724_0009
Revises: 20260723_0008
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa

revision = "20260724_0009"
down_revision = "20260723_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    required_tables = {"VehicleAssignments", "VehicleConditionRecords"}
    if not required_tables.issubset(inspector.get_table_names()):
        return

    # The first checkout implementation created a new Active assignment when
    # checking out a manual Scheduled assignment. Only archive a Scheduled row
    # when a later matching assignment has an actual Checkout condition record;
    # this avoids touching legitimate future assignments for the same parties.
    within_one_day = (
        'datetime(scheduled."StartDatetime", \'+1 day\')'
        if bind.dialect.name == "sqlite"
        else 'scheduled."StartDatetime" + INTERVAL \'1 day\''
    )
    bind.execute(sa.text(
        f"""
        UPDATE "VehicleAssignments" AS scheduled
        SET "Status" = 'Cancelled',
            "Archived" = true,
            "ArchivedAt" = COALESCE("ArchivedAt", CURRENT_TIMESTAMP),
            "UpdatedAt" = CURRENT_TIMESTAMP
        WHERE scheduled."Status" = 'Scheduled'
          AND scheduled."Archived" = false
          AND EXISTS (
              SELECT 1
              FROM "VehicleAssignments" AS continued
              JOIN "VehicleConditionRecords" AS checkout_condition
                ON checkout_condition."VehicleAssignmentId" = continued."Id"
               AND checkout_condition."RecordType" = 'Checkout'
              WHERE continued."Id" > scheduled."Id"
                AND continued."Archived" = false
                AND continued."Status" IN ('Active', 'Overdue', 'Completed')
                AND continued."VehicleId" = scheduled."VehicleId"
                AND continued."DriverId" = scheduled."DriverId"
                AND continued."StartOdometerKm" = scheduled."StartOdometerKm"
                AND COALESCE(continued."ReservationId", -1) =
                    COALESCE(scheduled."ReservationId", -1)
                AND COALESCE(TRIM(continued."Purpose"), '') =
                    COALESCE(TRIM(scheduled."Purpose"), '')
                AND continued."StartDatetime" >= scheduled."StartDatetime"
                AND continued."StartDatetime" <=
                    {within_one_day}
          )
        """
    ))


def downgrade() -> None:
    # This is a conservative data repair and cannot be reversed reliably
    # without reintroducing duplicate actionable assignments.
    pass
