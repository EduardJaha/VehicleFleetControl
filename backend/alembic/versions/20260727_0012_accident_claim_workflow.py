"""Expand accidents into an accident and insurance claim workflow.

Existing VehicleAccidents and AccidentFiles rows are retained. New required
workflow columns use safe defaults so legacy rows become valid Reported/Minor
accidents without rewriting their original dates, descriptions, or files.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260727_0012"
down_revision: Union[str, None] = "20260727_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # Some supported import/test databases contain only a subset of the
    # application tables. Marking the revision complete is safe there; a
    # real fleet database always has VehicleAccidents from the base schema.
    if not inspector.has_table("VehicleAccidents"):
        return
    # A new database is initialized from current SQLAlchemy metadata by the
    # foundation revision, so the complete workflow may already be present.
    if inspector.has_table("AccidentClaims"):
        return
    with op.batch_alter_table("VehicleAccidents") as batch:
        batch.add_column(sa.Column("DriverId", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("ReservationId", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("Severity", sa.String(50), nullable=False, server_default="Minor"))
        batch.add_column(sa.Column("Status", sa.String(50), nullable=False, server_default="Reported"))
        batch.add_column(sa.Column("PoliceInvolved", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("PoliceReportNumber", sa.String(150), nullable=True))
        batch.add_column(sa.Column("VehicleAvailableAfterAccident", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("EstimatedDamageCost", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("ActualDamageCost", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("FaultDetermination", sa.String(100), nullable=True))
        batch.add_column(sa.Column("ResolvedAt", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("ClosedAt", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch.add_column(sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch.create_foreign_key("fk_vehicle_accidents_driver", "Drivers", ["DriverId"], ["Id"], ondelete="SET NULL")
        batch.create_foreign_key(
            "fk_vehicle_accidents_reservation", "VehicleReservations", ["ReservationId"], ["Id"], ondelete="SET NULL"
        )
        batch.create_index("ix_vehicleaccidents_driver_id", ["DriverId"])
        batch.create_index("ix_vehicleaccidents_reservation_id", ["ReservationId"])
        batch.create_index("ix_vehicleaccidents_status", ["Status"])

    op.create_table(
        "AccidentClaims",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("AccidentId", sa.Integer(), sa.ForeignKey("VehicleAccidents.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("InsuranceDocumentId", sa.Integer(), sa.ForeignKey("VehiclePapers.Id", ondelete="SET NULL"), nullable=True),
        sa.Column("InsuranceCompany", sa.String(255), nullable=False),
        sa.Column("PolicyNumber", sa.String(150), nullable=False),
        sa.Column("ClaimNumber", sa.String(150), nullable=False),
        sa.Column("ClaimStatus", sa.String(50), nullable=False, server_default="Open"),
        sa.Column("ClaimOpenedDate", sa.DateTime(), nullable=False),
        sa.Column("ClaimClosedDate", sa.DateTime(), nullable=True),
        sa.Column("SettlementAmount", sa.Numeric(12, 2), nullable=True),
        sa.Column("Deductible", sa.Numeric(12, 2), nullable=True),
        sa.Column("AdjusterName", sa.String(255), nullable=True),
        sa.Column("Notes", sa.Text(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("AccidentId", name="uq_accident_claims_accident_id"),
        sa.UniqueConstraint("ClaimNumber", name="uq_accident_claims_claim_number"),
    )
    op.create_index("ix_accident_claims_status", "AccidentClaims", ["ClaimStatus"])

    op.create_table(
        "AccidentParties",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("AccidentId", sa.Integer(), sa.ForeignKey("VehicleAccidents.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("PartyType", sa.String(50), nullable=False),
        sa.Column("Name", sa.String(255), nullable=False),
        sa.Column("Phone", sa.String(50), nullable=True),
        sa.Column("Email", sa.String(255), nullable=True),
        sa.Column("Address", sa.String(500), nullable=True),
        sa.Column("VehicleRegistration", sa.String(100), nullable=True),
        sa.Column("InsuranceCompany", sa.String(255), nullable=True),
        sa.Column("PolicyNumber", sa.String(150), nullable=True),
        sa.Column("Notes", sa.Text(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_accident_parties_accident_id", "AccidentParties", ["AccidentId"])

    op.create_table(
        "AccidentInjuries",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("AccidentId", sa.Integer(), sa.ForeignKey("VehicleAccidents.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("PartyId", sa.Integer(), sa.ForeignKey("AccidentParties.Id", ondelete="SET NULL"), nullable=True),
        sa.Column("InjuredPersonName", sa.String(255), nullable=False),
        sa.Column("InjurySeverity", sa.String(50), nullable=False),
        sa.Column("Description", sa.Text(), nullable=True),
        sa.Column("MedicalTreatment", sa.Text(), nullable=True),
        sa.Column("Hospitalized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("Notes", sa.Text(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_accident_injuries_accident_id", "AccidentInjuries", ["AccidentId"])

    if inspector.has_table("WorkOrders"):
        with op.batch_alter_table("WorkOrders") as batch:
            batch.add_column(sa.Column("AccidentId", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_work_orders_accident", "VehicleAccidents", ["AccidentId"], ["Id"], ondelete="SET NULL"
            )
            batch.create_index("ix_work_orders_accident_id", ["AccidentId"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("VehicleAccidents"):
        return
    if inspector.has_table("WorkOrders") and "AccidentId" in {
        column["name"] for column in inspector.get_columns("WorkOrders")
    }:
        with op.batch_alter_table("WorkOrders") as batch:
            batch.drop_index("ix_work_orders_accident_id")
            batch.drop_constraint("fk_work_orders_accident", type_="foreignkey")
            batch.drop_column("AccidentId")

    op.drop_index("ix_accident_injuries_accident_id", table_name="AccidentInjuries")
    op.drop_table("AccidentInjuries")
    op.drop_index("ix_accident_parties_accident_id", table_name="AccidentParties")
    op.drop_table("AccidentParties")
    op.drop_index("ix_accident_claims_status", table_name="AccidentClaims")
    op.drop_table("AccidentClaims")

    with op.batch_alter_table("VehicleAccidents") as batch:
        batch.drop_index("ix_vehicleaccidents_status")
        batch.drop_index("ix_vehicleaccidents_reservation_id")
        batch.drop_index("ix_vehicleaccidents_driver_id")
        batch.drop_constraint("fk_vehicle_accidents_reservation", type_="foreignkey")
        batch.drop_constraint("fk_vehicle_accidents_driver", type_="foreignkey")
        for name in (
            "UpdatedAt", "CreatedAt", "ClosedAt", "ResolvedAt", "FaultDetermination",
            "ActualDamageCost", "EstimatedDamageCost", "VehicleAvailableAfterAccident",
            "PoliceReportNumber", "PoliceInvolved", "Status", "Severity", "ReservationId", "DriverId",
        ):
            batch.drop_column(name)
