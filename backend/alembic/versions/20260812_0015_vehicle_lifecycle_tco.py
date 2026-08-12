"""Add vehicle lifecycle and total-cost-of-ownership data."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0015"
down_revision: Union[str, None] = "20260810_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    has_vehicles = inspector.has_table("Vehicles")
    if not inspector.has_table("Suppliers"):
        op.create_table(
            "Suppliers",
            sa.Column("Id", sa.Integer(), primary_key=True),
            sa.Column("Name", sa.String(255), nullable=False),
            sa.Column("IsActive", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("Name", name="uq_suppliers_name"),
        )
        op.create_index("ix_suppliers_id", "Suppliers", ["Id"])

    if not has_vehicles:
        # Some historical migration tests intentionally contain only document
        # tables. Keep that supported while advancing the revision safely.
        return

    columns = [
        sa.Column("AcquisitionDate", sa.Date(), nullable=True),
        sa.Column("PurchasePrice", sa.Numeric(14, 2), nullable=True),
        sa.Column("SupplierId", sa.Integer(), nullable=True),
        sa.Column("OwnershipType", sa.String(20), nullable=False, server_default="Owned"),
        sa.Column("LeaseStart", sa.Date(), nullable=True),
        sa.Column("LeaseEnd", sa.Date(), nullable=True),
        sa.Column("MonthlyLeasePayment", sa.Numeric(14, 2), nullable=True),
        sa.Column("WarrantyExpiry", sa.Date(), nullable=True),
        sa.Column("ExpectedServiceYears", sa.Integer(), nullable=True),
        sa.Column("ExpectedServiceKm", sa.Integer(), nullable=True),
        sa.Column("DepreciationMethod", sa.String(30), nullable=False, server_default="Straight Line"),
        sa.Column("ResidualValue", sa.Numeric(14, 2), nullable=True),
        sa.Column("SaleDate", sa.Date(), nullable=True),
        sa.Column("SalePrice", sa.Numeric(14, 2), nullable=True),
        sa.Column("DisposalReason", sa.Text(), nullable=True),
        sa.Column("FuelTankCapacityL", sa.Numeric(10, 2), nullable=True),
        sa.Column("BatteryCapacityKwh", sa.Numeric(10, 2), nullable=True),
    ]
    vehicle_columns = {column["name"] for column in sa.inspect(bind).get_columns("Vehicles")}
    existing_supplier_fk = any(
        foreign_key.get("constrained_columns") == ["SupplierId"]
        for foreign_key in sa.inspect(bind).get_foreign_keys("Vehicles")
    )
    missing_columns = [column for column in columns if column.name not in vehicle_columns]
    if missing_columns or not existing_supplier_fk:
        with op.batch_alter_table("Vehicles") as batch:
            for column in missing_columns:
                batch.add_column(column)
            if not existing_supplier_fk:
                batch.create_foreign_key("fk_vehicles_supplier", "Suppliers", ["SupplierId"], ["Id"], ondelete="SET NULL")

    if sa.inspect(bind).has_table("VehicleOperatingCosts"):
        return
    op.create_table(
        "VehicleOperatingCosts",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("VehicleId", sa.Integer(), sa.ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("Category", sa.String(30), nullable=False),
        sa.Column("CostDate", sa.Date(), nullable=False),
        sa.Column("Amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("SupplierId", sa.Integer(), sa.ForeignKey("Suppliers.Id", ondelete="SET NULL"), nullable=True),
        sa.Column("Description", sa.Text(), nullable=True),
        sa.Column("Archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("\"Category\" IN ('Insurance', 'Registration', 'Other Operating')", name="ck_vehicle_operating_cost_category"),
        sa.CheckConstraint('"Amount" >= 0', name="ck_vehicle_operating_cost_amount_nonnegative"),
    )
    op.create_index("ix_vehicle_operating_costs_id", "VehicleOperatingCosts", ["Id"])
    op.create_index("ix_vehicle_operating_costs_archived", "VehicleOperatingCosts", ["Archived"])
    op.create_index("ix_vehicle_operating_costs_vehicle_date", "VehicleOperatingCosts", ["VehicleId", "CostDate"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("VehicleOperatingCosts"):
        op.drop_table("VehicleOperatingCosts")
    if inspector.has_table("Vehicles") and "AcquisitionDate" in {column["name"] for column in inspector.get_columns("Vehicles")}:
        with op.batch_alter_table("Vehicles") as batch:
            for name in (
                "BatteryCapacityKwh", "FuelTankCapacityL", "DisposalReason", "SalePrice", "SaleDate",
                "ResidualValue", "DepreciationMethod", "ExpectedServiceKm", "ExpectedServiceYears",
                "WarrantyExpiry", "MonthlyLeasePayment", "LeaseEnd", "LeaseStart", "OwnershipType",
                "SupplierId", "PurchasePrice", "AcquisitionDate",
            ):
                batch.drop_column(name)
    if inspector.has_table("Suppliers"):
        op.drop_table("Suppliers")
