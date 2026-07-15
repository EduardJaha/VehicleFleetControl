"""Small additive schema migrations for installations created before Maintenance v2.

The project does not use Alembic yet.  These migrations are intentionally limited
to nullable/defaulted columns so existing local SQLite data remains valid.
"""

from sqlalchemy import Engine, inspect, text


MAINTENANCE_COLUMNS: dict[str, dict[str, str]] = {
    "Inspections": {
        "Inspector": "VARCHAR(150)",
        "Archived": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "WorkOrders": {
        "ReminderServiceId": "INTEGER REFERENCES \"VehicleServices\"(\"Id\") ON DELETE SET NULL",
        "Source": "VARCHAR(50) NOT NULL DEFAULT 'Manual'",
        "CompletedOdometerKm": "INTEGER",
        "CompletionNotes": "TEXT",
        "CompletedBy": "VARCHAR(150)",
        "CreatedBy": "VARCHAR(150)",
        "Archived": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "VehicleServices": {
        "WorkOrderId": "INTEGER REFERENCES \"WorkOrders\"(\"Id\") ON DELETE SET NULL",
        "LaborCost": "VARCHAR",
        "PartsCost": "VARCHAR",
        "Source": "VARCHAR(50) NOT NULL DEFAULT 'Manual'",
        "Status": "VARCHAR(50) NOT NULL DEFAULT 'Completed'",
        "ReminderStatus": "VARCHAR(50)",
        "Archived": "BOOLEAN NOT NULL DEFAULT 0",
        "CreatedAt": "DATETIME",
        "UpdatedAt": "DATETIME",
    },
}


def run_additive_migrations(engine: Engine) -> None:
    """Add Maintenance relationship columns without rewriting existing tables."""
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in MAINTENANCE_COLUMNS.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in columns.items():
                if column_name not in existing:
                    connection.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'))

        # Backfill timestamps for historical Services. ServiceDate is the most
        # accurate available timestamp for legacy rows.
        connection.execute(text(
            'UPDATE "VehicleServices" SET "CreatedAt" = COALESCE("CreatedAt", "ServiceDate"), '
            '"UpdatedAt" = COALESCE("UpdatedAt", "ServiceDate")'
        ))

        if engine.dialect.name == "sqlite":
            connection.execute(text(
                'CREATE UNIQUE INDEX IF NOT EXISTS "uq_vehicle_services_work_order" '
                'ON "VehicleServices" ("WorkOrderId") WHERE "WorkOrderId" IS NOT NULL'
            ))
            connection.execute(text(
                'CREATE INDEX IF NOT EXISTS "ix_work_orders_reminder_service" '
                'ON "WorkOrders" ("ReminderServiceId")'
            ))
