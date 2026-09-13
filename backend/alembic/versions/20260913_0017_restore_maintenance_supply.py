"""Restore maintenance supply without resetting historical migrations or data.

Definitions below are frozen at this revision (no imports from app models).
Existing tables are inspected and expanded; only absent tables are created.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260913_0017"
down_revision = "20260812_0016"
branch_labels = None
depends_on = None


def table_Vendors():
    return sa.Table(
        "Vendors",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("Name", sa.String(length=200), nullable=False),
        sa.Column("VendorType", sa.String(length=50), nullable=False),
        sa.Column("City", sa.String(length=150), nullable=True),
        sa.Column("Country", sa.String(length=100), nullable=True),
        sa.Column("Notes", sa.Text(), nullable=True),
        sa.Column("IsActive", sa.Boolean(), nullable=False),
        sa.Column("ContactName", sa.String(length=150), nullable=True),
        sa.Column("Email", sa.String(length=255), nullable=True),
        sa.Column("Phone", sa.String(length=50), nullable=True),
        sa.Column("Address", sa.Text(), nullable=True),
        sa.Column("PaymentTerms", sa.String(length=150), nullable=True),
        sa.Column("TaxNumber", sa.String(length=100), nullable=True),
        sa.Column("SupportedServices", sa.JSON(), nullable=False),
        sa.Column("Status", sa.String(length=30), nullable=False),
        sa.Column("Rating", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("Archived", sa.Boolean(), nullable=False),
        sa.Column("ArchivedAt", sa.DateTime(), nullable=True),
        sa.Column("ArchivedBy", sa.Integer(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            '"Rating" IS NULL OR ("Rating" >= 0 AND "Rating" <= 5)',
            name="ck_vendors_rating",
        ),
        sa.ForeignKeyConstraint(["ArchivedBy"], ["Users.Id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint("CompanyId", "Name", name="uq_vendors_company_name"),
    )


def table_PartCategories():
    return sa.Table(
        "PartCategories",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("Name", sa.String(length=150), nullable=False),
        sa.Column("Description", sa.Text(), nullable=True),
        sa.Column("IsActive", sa.Boolean(), nullable=False),
        sa.Column("Archived", sa.Boolean(), nullable=False),
        sa.Column("ArchivedAt", sa.DateTime(), nullable=True),
        sa.Column("ArchivedBy", sa.Integer(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["ArchivedBy"], ["Users.Id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint(
            "CompanyId", "Name", name="uq_part_categories_company_name"
        ),
    )


def table_Parts():
    return sa.Table(
        "Parts",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("PartNumber", sa.String(length=100), nullable=False),
        sa.Column("Name", sa.String(length=200), nullable=False),
        sa.Column("Manufacturer", sa.String(length=200), nullable=True),
        sa.Column("Description", sa.Text(), nullable=True),
        sa.Column("CategoryId", sa.Integer(), nullable=False),
        sa.Column("Unit", sa.String(length=30), nullable=False),
        sa.Column("UnitCost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("SupplierId", sa.Integer(), nullable=True),
        sa.Column("Barcode", sa.String(length=100), nullable=True),
        sa.Column("MinimumStock", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("IsActive", sa.Boolean(), nullable=False),
        sa.Column("Archived", sa.Boolean(), nullable=False),
        sa.Column("ArchivedAt", sa.DateTime(), nullable=True),
        sa.Column("ArchivedBy", sa.Integer(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint('"MinimumStock" >= 0', name="ck_parts_minimum_stock"),
        sa.CheckConstraint('"UnitCost" >= 0', name="ck_parts_unit_cost"),
        sa.ForeignKeyConstraint(["ArchivedBy"], ["Users.Id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["CategoryId"], ["PartCategories.Id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["SupplierId"], ["Vendors.Id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint("CompanyId", "Barcode", name="uq_parts_company_barcode"),
        sa.UniqueConstraint("CompanyId", "PartNumber", name="uq_parts_company_number"),
    )


def table_PartInventories():
    return sa.Table(
        "PartInventories",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("PartId", sa.Integer(), nullable=False),
        sa.Column("LocationId", sa.Integer(), nullable=False),
        sa.Column(
            "ReservedQuantity", sa.Numeric(precision=14, scale=3), nullable=False
        ),
        sa.Column("MinimumStock", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("QuantityOnHand", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            '"MinimumStock" IS NULL OR "MinimumStock" >= 0', name="ck_inventory_minimum"
        ),
        sa.CheckConstraint(
            '"QuantityOnHand" >= 0', name="ck_part_inventory_nonnegative"
        ),
        sa.CheckConstraint(
            '"ReservedQuantity" >= 0 AND "ReservedQuantity" <= "QuantityOnHand"',
            name="ck_inventory_reserved",
        ),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["LocationId"], ["Locations.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["PartId"], ["Parts.Id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint(
            "PartId", "LocationId", name="uq_part_inventory_part_location"
        ),
    )


def table_Technicians():
    return sa.Table(
        "Technicians",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("UserId", sa.Integer(), nullable=True),
        sa.Column("Specialization", sa.String(length=200), nullable=True),
        sa.Column("IsActive", sa.Boolean(), nullable=False),
        sa.Column("EmployeeNumber", sa.String(length=100), nullable=False),
        sa.Column("FullName", sa.String(length=200), nullable=False),
        sa.Column("Email", sa.String(length=255), nullable=True),
        sa.Column("Phone", sa.String(length=50), nullable=True),
        sa.Column("HourlyRate", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("Status", sa.String(length=30), nullable=False),
        sa.Column("Archived", sa.Boolean(), nullable=False),
        sa.Column("ArchivedAt", sa.DateTime(), nullable=True),
        sa.Column("ArchivedBy", sa.Integer(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["ArchivedBy"], ["Users.Id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["UserId"], ["Users.Id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint(
            "CompanyId", "EmployeeNumber", name="uq_technicians_company_number"
        ),
    )


def table_PurchaseOrders():
    return sa.Table(
        "PurchaseOrders",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("OrderNumber", sa.String(length=100), nullable=False),
        sa.Column("VendorId", sa.Integer(), nullable=False),
        sa.Column("StorageLocationId", sa.Integer(), nullable=False),
        sa.Column("Status", sa.String(length=40), nullable=False),
        sa.Column("OrderDate", sa.DateTime(), nullable=True),
        sa.Column("ExpectedDate", sa.DateTime(), nullable=True),
        sa.Column("Notes", sa.Text(), nullable=True),
        sa.Column("Subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("TaxAmount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("DiscountAmount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("TotalAmount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("Archived", sa.Boolean(), nullable=False),
        sa.Column("ArchivedAt", sa.DateTime(), nullable=True),
        sa.Column("ArchivedBy", sa.Integer(), nullable=True),
        sa.Column("CreatedBy", sa.Integer(), nullable=True),
        sa.Column("ApprovedBy", sa.Integer(), nullable=True),
        sa.Column("ApprovedAt", sa.DateTime(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["ApprovedBy"], ["Users.Id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ArchivedBy"], ["Users.Id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["CreatedBy"], ["Users.Id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["StorageLocationId"], ["Locations.Id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["VendorId"], ["Vendors.Id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint(
            "CompanyId", "OrderNumber", name="uq_purchase_orders_company_number"
        ),
    )


def table_PurchaseOrderItems():
    return sa.Table(
        "PurchaseOrderItems",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("PurchaseOrderId", sa.Integer(), nullable=False),
        sa.Column("PartId", sa.Integer(), nullable=False),
        sa.Column("QuantityOrdered", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "QuantityReceived", sa.Numeric(precision=14, scale=3), nullable=False
        ),
        sa.Column("UnitCost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("LineTotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            '"QuantityOrdered" > 0', name="ck_purchase_order_items_ordered_positive"
        ),
        sa.CheckConstraint(
            '"QuantityReceived" >= 0 AND "QuantityReceived" <= "QuantityOrdered"',
            name="ck_purchase_order_items_received",
        ),
        sa.CheckConstraint('"UnitCost" >= 0', name="ck_purchase_order_items_unit_cost"),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["PartId"], ["Parts.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["PurchaseOrderId"], ["PurchaseOrders.Id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint(
            "PurchaseOrderId", "PartId", name="uq_purchase_order_items_part"
        ),
    )


def table_InventoryTransactions():
    return sa.Table(
        "InventoryTransactions",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("PartId", sa.Integer(), nullable=False),
        sa.Column("TransactionType", sa.String(length=40), nullable=False),
        sa.Column("Quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("UnitCost", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("FromLocationId", sa.Integer(), nullable=True),
        sa.Column("ToLocationId", sa.Integer(), nullable=True),
        sa.Column("WorkOrderId", sa.Integer(), nullable=True),
        sa.Column("PurchaseOrderItemId", sa.Integer(), nullable=True),
        sa.Column("Notes", sa.Text(), nullable=True),
        sa.Column("PerformedBy", sa.Integer(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            '"Quantity" <> 0', name="ck_inventory_transactions_quantity_nonzero"
        ),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["FromLocationId"], ["Locations.Id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["PartId"], ["Parts.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["PerformedBy"], ["Users.Id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["PurchaseOrderItemId"], ["PurchaseOrderItems.Id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["ToLocationId"], ["Locations.Id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["WorkOrderId"], ["WorkOrders.Id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("Id"),
    )


def table_WorkOrderParts():
    return sa.Table(
        "WorkOrderParts",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("WorkOrderId", sa.Integer(), nullable=False),
        sa.Column("PartId", sa.Integer(), nullable=False),
        sa.Column("LocationId", sa.Integer(), nullable=False),
        sa.Column("InventoryTransactionId", sa.Integer(), nullable=False),
        sa.Column(
            "QuantityReturned", sa.Numeric(precision=14, scale=3), nullable=False
        ),
        sa.Column("Quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("UnitCost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("TotalCost", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("Archived", sa.Boolean(), nullable=False),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            '"Quantity" > 0', name="ck_work_order_parts_quantity_positive"
        ),
        sa.CheckConstraint(
            '"QuantityReturned" >= 0 AND "QuantityReturned" <= "Quantity"',
            name="ck_work_order_parts_returned",
        ),
        sa.CheckConstraint('"UnitCost" >= 0', name="ck_work_order_parts_unit_cost"),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["InventoryTransactionId"],
            ["InventoryTransactions.Id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["LocationId"], ["Locations.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["PartId"], ["Parts.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["WorkOrderId"], ["WorkOrders.Id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint("InventoryTransactionId"),
    )


def table_WorkOrderTechnicians():
    return sa.Table(
        "WorkOrderTechnicians",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("WorkOrderId", sa.Integer(), nullable=False),
        sa.Column("TechnicianId", sa.Integer(), nullable=False),
        sa.Column("EstimatedHours", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("TaskDescription", sa.Text(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            '"EstimatedHours" >= 0', name="ck_work_order_technicians_estimated_hours"
        ),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["TechnicianId"], ["Technicians.Id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["WorkOrderId"], ["WorkOrders.Id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("Id"),
        sa.UniqueConstraint(
            "WorkOrderId", "TechnicianId", name="uq_work_order_technicians_assignment"
        ),
    )


def table_LaborEntries():
    return sa.Table(
        "LaborEntries",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("WorkOrderId", sa.Integer(), nullable=False),
        sa.Column("TechnicianId", sa.Integer(), nullable=False),
        sa.Column("Notes", sa.Text(), nullable=True),
        sa.Column("ActualHours", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("ClockIn", sa.DateTime(), nullable=True),
        sa.Column("ClockOut", sa.DateTime(), nullable=True),
        sa.Column("HourlyRate", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("LaborCost", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("TaskDescription", sa.Text(), nullable=True),
        sa.Column("Archived", sa.Boolean(), nullable=False),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint('"ActualHours" >= 0', name="ck_labor_entries_actual_hours"),
        sa.CheckConstraint('"HourlyRate" >= 0', name="ck_labor_entries_hourly_rate"),
        sa.CheckConstraint('"LaborCost" >= 0', name="ck_labor_entries_labor_cost"),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["TechnicianId"], ["Technicians.Id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["WorkOrderId"], ["WorkOrders.Id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("Id"),
    )


def table_WorkOrderVendorCharges():
    return sa.Table(
        "WorkOrderVendorCharges",
        sa.MetaData(),
        sa.Column("Id", sa.Integer(), nullable=False),
        sa.Column("WorkOrderId", sa.Integer(), nullable=False),
        sa.Column("VendorId", sa.Integer(), nullable=False),
        sa.Column("Description", sa.String(length=255), nullable=False),
        sa.Column("InvoiceNumber", sa.String(length=150), nullable=True),
        sa.Column("AttachmentId", sa.Integer(), nullable=True),
        sa.Column("Amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("Archived", sa.Boolean(), nullable=False),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False),
        sa.Column("CompanyId", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint('"Amount" >= 0', name="ck_work_order_vendor_charges_amount"),
        sa.ForeignKeyConstraint(
            ["AttachmentId"], ["Attachments.Id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["CompanyId"], ["Companies.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["VendorId"], ["Vendors.Id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["WorkOrderId"], ["WorkOrders.Id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("Id"),
    )


TABLES = {
    "Vendors": table_Vendors,
    "PartCategories": table_PartCategories,
    "Parts": table_Parts,
    "PartInventories": table_PartInventories,
    "Technicians": table_Technicians,
    "PurchaseOrders": table_PurchaseOrders,
    "PurchaseOrderItems": table_PurchaseOrderItems,
    "InventoryTransactions": table_InventoryTransactions,
    "WorkOrderParts": table_WorkOrderParts,
    "WorkOrderTechnicians": table_WorkOrderTechnicians,
    "LaborEntries": table_LaborEntries,
    "WorkOrderVendorCharges": table_WorkOrderVendorCharges,
}


PARENTS = {
    "PartInventories": ("Parts", "PartId"),
    "WorkOrderTechnicians": ("WorkOrders", "WorkOrderId"),
    "LaborEntries": ("WorkOrders", "WorkOrderId"),
    "WorkOrderVendorCharges": ("WorkOrders", "WorkOrderId"),
    "PurchaseOrderItems": ("PurchaseOrders", "PurchaseOrderId"),
    "WorkOrderParts": ("WorkOrders", "WorkOrderId"),
}
UNIQUE_REPLACEMENTS = {
    "Vendors": (
        ["uq_vendors_name_type"],
        "uq_vendors_company_name",
        ["CompanyId", "Name"],
    ),
    "PartCategories": (
        ["uq_part_categories_name"],
        "uq_part_categories_company_name",
        ["CompanyId", "Name"],
    ),
    "Parts": (
        ["uq_parts_part_number"],
        "uq_parts_company_number",
        ["CompanyId", "PartNumber"],
    ),
    "Technicians": (
        ["uq_technicians_employee_number"],
        "uq_technicians_company_number",
        ["CompanyId", "EmployeeNumber"],
    ),
    "PurchaseOrders": (
        ["uq_purchase_orders_order_number"],
        "uq_purchase_orders_company_number",
        ["CompanyId", "OrderNumber"],
    ),
}
ZERO_COLUMNS = {
    "ReservedQuantity",
    "QuantityReturned",
    "OtherCost",
    "ExternalVendorCost",
    "TaxAmount",
    "DiscountAmount",
}


# Frozen lookup indexes for installations where the supply tables were absent.
SUPPLY_INDEXES = {
    "Vendors": [
        ("ix_Vendors_Archived", ["Archived"], False),
        ("ix_Vendors_CompanyId", ["CompanyId"], False),
        ("ix_Vendors_Id", ["Id"], False),
        ("ix_Vendors_Name", ["Name"], False),
        ("ix_Vendors_Status", ["Status"], False),
        ("ix_Vendors_TaxNumber", ["TaxNumber"], False),
        ("ix_Vendors_VendorType", ["VendorType"], False),
    ],
    "PartCategories": [
        ("ix_PartCategories_Archived", ["Archived"], False),
        ("ix_PartCategories_CompanyId", ["CompanyId"], False),
        ("ix_PartCategories_Id", ["Id"], False),
    ],
    "Parts": [
        ("ix_Parts_Archived", ["Archived"], False),
        ("ix_Parts_CategoryId", ["CategoryId"], False),
        ("ix_Parts_CompanyId", ["CompanyId"], False),
        ("ix_Parts_Id", ["Id"], False),
        ("ix_Parts_Name", ["Name"], False),
        ("ix_Parts_PartNumber", ["PartNumber"], False),
        ("ix_Parts_SupplierId", ["SupplierId"], False),
    ],
    "PartInventories": [
        ("ix_PartInventories_CompanyId", ["CompanyId"], False),
        ("ix_PartInventories_LocationId", ["LocationId"], False),
        ("ix_PartInventories_PartId", ["PartId"], False),
    ],
    "Technicians": [
        ("ix_Technicians_Archived", ["Archived"], False),
        ("ix_Technicians_CompanyId", ["CompanyId"], False),
        ("ix_Technicians_EmployeeNumber", ["EmployeeNumber"], False),
        ("ix_Technicians_FullName", ["FullName"], False),
        ("ix_Technicians_Id", ["Id"], False),
        ("ix_Technicians_Status", ["Status"], False),
    ],
    "PurchaseOrders": [
        ("ix_PurchaseOrders_Archived", ["Archived"], False),
        ("ix_PurchaseOrders_CompanyId", ["CompanyId"], False),
        ("ix_PurchaseOrders_Id", ["Id"], False),
        ("ix_PurchaseOrders_OrderNumber", ["OrderNumber"], False),
        ("ix_PurchaseOrders_Status", ["Status"], False),
        ("ix_PurchaseOrders_VendorId", ["VendorId"], False),
    ],
    "PurchaseOrderItems": [
        ("ix_PurchaseOrderItems_CompanyId", ["CompanyId"], False),
        ("ix_PurchaseOrderItems_PartId", ["PartId"], False),
        ("ix_PurchaseOrderItems_PurchaseOrderId", ["PurchaseOrderId"], False),
    ],
    "InventoryTransactions": [
        ("ix_InventoryTransactions_CompanyId", ["CompanyId"], False),
        ("ix_InventoryTransactions_PartId", ["PartId"], False),
        (
            "ix_InventoryTransactions_PurchaseOrderItemId",
            ["PurchaseOrderItemId"],
            False,
        ),
        ("ix_InventoryTransactions_TransactionType", ["TransactionType"], False),
        ("ix_InventoryTransactions_WorkOrderId", ["WorkOrderId"], False),
        ("ix_inventory_transactions_part_created", ["PartId", "CreatedAt"], False),
    ],
    "WorkOrderParts": [
        ("ix_WorkOrderParts_Archived", ["Archived"], False),
        ("ix_WorkOrderParts_CompanyId", ["CompanyId"], False),
        ("ix_WorkOrderParts_PartId", ["PartId"], False),
        ("ix_WorkOrderParts_WorkOrderId", ["WorkOrderId"], False),
    ],
    "WorkOrderTechnicians": [
        ("ix_WorkOrderTechnicians_CompanyId", ["CompanyId"], False),
        ("ix_WorkOrderTechnicians_TechnicianId", ["TechnicianId"], False),
        ("ix_WorkOrderTechnicians_WorkOrderId", ["WorkOrderId"], False),
    ],
    "LaborEntries": [
        ("ix_LaborEntries_Archived", ["Archived"], False),
        ("ix_LaborEntries_CompanyId", ["CompanyId"], False),
        ("ix_LaborEntries_TechnicianId", ["TechnicianId"], False),
        ("ix_LaborEntries_WorkOrderId", ["WorkOrderId"], False),
    ],
    "WorkOrderVendorCharges": [
        ("ix_WorkOrderVendorCharges_Archived", ["Archived"], False),
        ("ix_WorkOrderVendorCharges_CompanyId", ["CompanyId"], False),
        ("ix_WorkOrderVendorCharges_VendorId", ["VendorId"], False),
        ("ix_WorkOrderVendorCharges_WorkOrderId", ["WorkOrderId"], False),
    ],
}


def upgrade():
    bind = op.get_bind()
    # SQLite's legacy driver otherwise autocommits DDL before the first DML.
    if (
        bind.dialect.name == "sqlite"
        and not bind.connection.driver_connection.in_transaction
    ):
        bind.exec_driver_sql("BEGIN")
    existing = set(sa.inspect(bind).get_table_names())
    original = set(existing)
    # Older migration regression fixtures represent individual modules, not an
    # installable fleet schema. Do not invent their missing core business tables.
    if (
        not {"Users", "Locations", "WorkOrders", "VehicleServices", "Attachments"}
        <= existing
    ):
        return
    # Validate ambiguous ownership before any schema changes.
    if "PartCategories" in existing and "Parts" in existing:
        columns = {c["name"] for c in sa.inspect(bind).get_columns("Parts")}
        if "CompanyId" in columns:
            ambiguous = bind.execute(
                sa.text(
                    'SELECT "CategoryId" FROM "Parts" GROUP BY "CategoryId" HAVING COUNT(DISTINCT "CompanyId") > 1'
                )
            ).first()
            if ambiguous:
                raise RuntimeError(
                    "Shared legacy part category needs an explicit company mapping before upgrade: "
                    + str(ambiguous[0])
                )
    for name, factory in TABLES.items():
        target = factory()
        if name not in existing:
            # Reflection resolves foreign targets without referencing live ORM metadata.
            metadata = sa.MetaData()
            metadata.reflect(bind=bind, resolve_fks=False)
            for other_name, other_factory in TABLES.items():
                if other_name not in metadata.tables:
                    other_factory().to_metadata(metadata)
            metadata.tables[name].create(bind)
            existing.add(name)
            continue
        columns = {c["name"] for c in sa.inspect(bind).get_columns(name)}
        for column in target.columns:
            if column.name in columns:
                continue
            default = "0" if column.name in ZERO_COLUMNS else None
            if column.name == "IsActive":
                default = sa.true()
            # CompanyId must be derived from its parent before NOT NULL is applied.
            nullable = column.nullable or column.name == "CompanyId"
            op.add_column(
                name,
                sa.Column(
                    column.name, column.type, nullable=nullable, server_default=default
                ),
            )
        if "CompanyId" not in columns:
            if name == "PartCategories":
                bind.execute(
                    sa.text(
                        'UPDATE "PartCategories" SET "CompanyId" = COALESCE((SELECT MIN("Parts"."CompanyId") FROM "Parts" WHERE "Parts"."CategoryId" = "PartCategories"."Id"), 1)'
                    )
                )
            elif name in PARENTS:
                parent, key = PARENTS[name]
                bind.execute(
                    sa.text(
                        f'UPDATE "{name}" SET "CompanyId" = (SELECT "CompanyId" FROM "{parent}" WHERE "{parent}"."Id" = "{name}"."{key}")'
                    )
                )
            else:
                bind.execute(sa.text(f'UPDATE "{name}" SET "CompanyId" = 1'))
        if name in {"Vendors", "Technicians"} and "IsActive" not in columns:
            bind.execute(
                sa.text(
                    f"""UPDATE "{name}" SET "IsActive" = CASE WHEN "Status" = 'Inactive' OR "Archived" = true THEN false ELSE true END"""
                )
            )
        if name == "WorkOrderParts" and "QuantityReturned" not in columns:
            bind.execute(
                sa.text(
                    'UPDATE "WorkOrderParts" SET "QuantityReturned" = "Quantity" WHERE "Archived" = true'
                )
            )

    # Replace obsolete global uniqueness and add all missing constraints. Batch
    # recreation preserves rows, IDs, existing indexes, and foreign keys.
    for name, factory in TABLES.items():
        if name not in original:
            continue
        inspector = sa.inspect(bind)
        actual_columns = {c["name"]: c for c in inspector.get_columns(name)}
        constraints = {c["name"] for c in inspector.get_unique_constraints(name)}
        checks = {c["name"] for c in inspector.get_check_constraints(name)}
        fks = {
            tuple(c["constrained_columns"]) for c in inspector.get_foreign_keys(name)
        }
        target = factory()
        drops = UNIQUE_REPLACEMENTS.get(name, ([], None, []))[0]
        if name == "Parts":
            drops = drops + ["uq_parts_barcode"]
        with op.batch_alter_table(name) as batch:
            for obsolete in drops:
                if obsolete in constraints:
                    batch.drop_constraint(obsolete, type_="unique")
            for col in target.columns:
                if col.name == "CompanyId" and actual_columns[col.name]["nullable"]:
                    batch.alter_column(col.name, existing_type=col.type, nullable=False)
                for fk in col.foreign_keys:
                    if (col.name,) not in fks:
                        table, key = fk.target_fullname.split(".")
                        batch.create_foreign_key(
                            f"fk_{name.lower()}_{col.name.lower()}_restored",
                            table,
                            [col.name],
                            [key],
                            ondelete=fk.ondelete,
                        )
            for constraint in target.constraints:
                if (
                    isinstance(constraint, sa.UniqueConstraint)
                    and constraint.name
                    and constraint.name not in constraints
                ):
                    batch.create_unique_constraint(
                        constraint.name, [c.name for c in constraint.columns]
                    )
                if (
                    isinstance(constraint, sa.CheckConstraint)
                    and constraint.name not in checks
                ):
                    batch.create_check_constraint(
                        constraint.name, str(constraint.sqltext)
                    )

    for name in ("WorkOrders", "VehicleServices"):
        if name not in existing:
            continue
        columns = {c["name"] for c in sa.inspect(bind).get_columns(name)}
        additions = [("VendorId", sa.Integer(), True)]
        if name == "WorkOrders":
            additions += [
                (key, sa.Numeric(12, 2), False)
                for key in (
                    "ExternalVendorCost",
                    "TaxAmount",
                    "DiscountAmount",
                    "OtherCost",
                )
            ]
        fks = {
            tuple(c["constrained_columns"])
            for c in sa.inspect(bind).get_foreign_keys(name)
        }
        with op.batch_alter_table(name) as batch:
            for key, type_, nullable in additions:
                if key not in columns:
                    batch.add_column(
                        sa.Column(
                            key,
                            type_,
                            nullable=nullable,
                            server_default="0" if not nullable else None,
                        )
                    )
            if ("VendorId",) not in fks:
                batch.create_foreign_key(
                    f"fk_{name.lower()}_vendor_restored",
                    "Vendors",
                    ["VendorId"],
                    ["Id"],
                    ondelete="SET NULL",
                )

    for name in TABLES:
        indexes = {i["name"] for i in sa.inspect(bind).get_indexes(name)}
        key = f"ix_{name.lower()}_company_id"
        if key not in indexes:
            op.create_index(key, name, ["CompanyId"])
    for name, definitions in SUPPLY_INDEXES.items():
        existing_indexes = sa.inspect(bind).get_indexes(name)
        names = {index["name"] for index in existing_indexes}
        signatures = {
            (tuple(index["column_names"]), bool(index["unique"]))
            for index in existing_indexes
        }
        for index_name, columns, unique in definitions:
            if index_name not in names and (tuple(columns), unique) not in signatures:
                op.create_index(index_name, name, columns, unique=unique)

    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("LaborEntries")}
    if "uq_labor_active_clock" not in indexes:
        condition = sa.text(
            '"ClockIn" IS NOT NULL AND "ClockOut" IS NULL AND "Archived" = false'
        )
        op.create_index(
            "uq_labor_active_clock",
            "LaborEntries",
            ["CompanyId", "TechnicianId"],
            unique=True,
            sqlite_where=condition,
            postgresql_where=condition,
        )

    # Validate ownership along EVERY business relation, including tables which
    # already had CompanyId from the older, incomplete tenant migration.
    relations = {
        "Parts": [("PartCategories", "CategoryId"), ("Vendors", "SupplierId")],
        "PartInventories": [("Parts", "PartId"), ("Locations", "LocationId")],
        "PurchaseOrders": [("Vendors", "VendorId"), ("Locations", "StorageLocationId")],
        "PurchaseOrderItems": [
            ("PurchaseOrders", "PurchaseOrderId"),
            ("Parts", "PartId"),
        ],
        "InventoryTransactions": [
            ("Parts", "PartId"),
            ("Locations", "FromLocationId"),
            ("Locations", "ToLocationId"),
            ("WorkOrders", "WorkOrderId"),
            ("PurchaseOrderItems", "PurchaseOrderItemId"),
        ],
        "WorkOrderParts": [
            ("WorkOrders", "WorkOrderId"),
            ("Parts", "PartId"),
            ("Locations", "LocationId"),
            ("InventoryTransactions", "InventoryTransactionId"),
        ],
        "WorkOrderTechnicians": [
            ("WorkOrders", "WorkOrderId"),
            ("Technicians", "TechnicianId"),
        ],
        "LaborEntries": [
            ("WorkOrders", "WorkOrderId"),
            ("Technicians", "TechnicianId"),
        ],
        "WorkOrderVendorCharges": [
            ("WorkOrders", "WorkOrderId"),
            ("Vendors", "VendorId"),
        ],
    }
    for child, links in relations.items():
        for parent, key in links:
            invalid = bind.execute(
                sa.text(
                    f'SELECT c."Id" FROM "{child}" c LEFT JOIN "{parent}" p ON p."Id" = c."{key}" WHERE c."{key}" IS NOT NULL AND (p."Id" IS NULL OR c."CompanyId" <> p."CompanyId")'
                )
            ).first()
            if invalid:
                raise RuntimeError(f"Company mismatch: {child} #{invalid[0]} / {key}")
    if bind.dialect.name == "sqlite":
        issues = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if issues:
            raise RuntimeError(
                "Foreign-key violations after supply upgrade: " + str(issues[:5])
            )
    seed_permissions(bind)


def seed_permissions(bind):
    # Preserve historical purchasing.* permissions; add the current explicit codes.
    codes = {
        "parts.view": "Parts",
        "parts.manage": "Parts",
        "inventory.view": "Inventory",
        "inventory.manage": "Inventory",
        "vendors.view": "Vendors",
        "vendors.manage": "Vendors",
        "purchase_orders.view": "Purchasing",
        "purchase_orders.create": "Purchasing",
        "purchase_orders.approve": "Purchasing",
        "technicians.view": "Technicians",
        "technicians.manage": "Technicians",
        "labor.manage": "Maintenance",
        "maintenance.manage_costs": "Maintenance",
    }
    tables = set(sa.inspect(bind).get_table_names())
    if not {"Permissions", "Roles", "RolePermissions"} <= tables:
        return
    existing = set(bind.execute(sa.text('SELECT "Code" FROM "Permissions"')).scalars())
    for code, module in codes.items():
        if code not in existing:
            bind.execute(
                sa.text(
                    'INSERT INTO "Permissions" ("Code", "Name", "Module", "CreatedAt") VALUES (:code, :code, :module, CURRENT_TIMESTAMP)'
                ),
                {"code": code, "module": module},
            )
    grants = {
        "admin": set(codes),
        "fleet_manager": set(codes),
        "mechanic": {
            "parts.view",
            "inventory.view",
            "inventory.manage",
            "vendors.view",
            "technicians.view",
            "labor.manage",
        },
        "finance": {
            "parts.view",
            "inventory.view",
            "vendors.view",
            "purchase_orders.view",
            "purchase_orders.approve",
            "technicians.view",
            "maintenance.manage_costs",
        },
    }
    ids = dict(bind.execute(sa.text('SELECT "Code", "Id" FROM "Permissions"')).all())
    roles = dict(bind.execute(sa.text('SELECT "Code", "Id" FROM "Roles"')).all())
    existing_grants = set(
        bind.execute(
            sa.text('SELECT "RoleId", "PermissionId" FROM "RolePermissions"')
        ).all()
    )
    for role, permissions in grants.items():
        if role not in roles:
            continue
        for code in permissions:
            pair = (roles[role], ids[code])
            if pair not in existing_grants:
                bind.execute(
                    sa.text(
                        'INSERT INTO "RolePermissions" ("RoleId", "PermissionId") VALUES (:role, :permission)'
                    ),
                    {"role": pair[0], "permission": pair[1]},
                )


def downgrade():
    if not {
        "Users",
        "Locations",
        "WorkOrders",
        "VehicleServices",
        "Attachments",
    } <= set(sa.inspect(op.get_bind()).get_table_names()):
        return
    raise RuntimeError(
        "Supply restoration is data-preserving and forward-only. Restore a verified backup to roll back."
    )
