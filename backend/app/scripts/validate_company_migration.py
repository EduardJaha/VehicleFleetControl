"""Validate that multi-company backfill is complete before enforcing NOT NULL."""

from sqlalchemy import inspect, text

from app.db.session import SessionLocal

TENANT_TABLES = (
    "CompanySettings", "CompanyUsers", "Users", "Locations", "Departments", "CostCenters", "UserRoles", "Suppliers",
    "Vehicles", "Drivers", "VehicleAssignments", "VehicleConditionRecords", "Inspections",
    "InspectionItems", "WorkOrders", "DocumentRequirements", "VehiclePapers",
    "DocumentVersions", "VehicleServices", "ServiceBills", "VehicleFuels",
    "VehicleOperatingCosts", "VehicleAccidents", "AccidentClaims", "AccidentParties",
    "AccidentInjuries", "AccidentFiles", "VehicleReservations", "AuditLogs", "ImportJobs",
    "ImportRowResults", "Notifications", "Attachments", "Vendors", "Parts", "Technicians",
    "InventoryTransactions", "PurchaseOrders", "PurchaseOrderItems", "WorkOrderParts", "WorkOrderLabor",
)


def validate() -> dict[str, int]:
    db = SessionLocal()
    try:
        inspector = inspect(db.bind)
        tables = set(inspector.get_table_names())
        failures: dict[str, int] = {}
        for table in TENANT_TABLES:
            if table not in tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table)}
            if "CompanyId" not in columns:
                failures[table] = -1
                continue
            count = db.execute(text(f'SELECT COUNT(*) FROM "{table}" WHERE "CompanyId" IS NULL')).scalar_one()
            if count:
                failures[table] = count
        if failures:
            raise RuntimeError(f"Company migration validation failed (-1 means missing column): {failures}")
        return {table: 0 for table in TENANT_TABLES if table in tables}
    finally:
        db.close()


if __name__ == "__main__":
    checked = validate()
    print(f"Company migration validation passed for {len(checked)} table(s).")
