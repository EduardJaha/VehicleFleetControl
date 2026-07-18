"""Deprecated pre-Alembic additive migrations.

Kept only as historical transition code and for the legacy catalog migration
test. FastAPI startup no longer invokes these functions; use ``alembic upgrade
head`` for every managed database.
"""

from sqlalchemy import Engine, inspect, text
from app.utils.vehicle_catalog import clean_catalog_name, normalize_catalog_name


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
    """Apply additive migrations without rewriting existing SQLite tables."""
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

    run_vehicle_catalog_migration(engine)


def run_vehicle_catalog_migration(engine: Engine) -> None:
    """Add catalog references and backfill them from legacy Brand/Model strings.

    The legacy display columns are deliberately retained as compatibility
    snapshots. This keeps reports and older integrations working while every
    existing Vehicle gains catalog identifiers.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    required_tables = {"Vehicles", "VehicleBrands", "VehicleModels"}
    if not required_tables.issubset(table_names):
        return

    vehicle_columns = {column["name"] for column in inspector.get_columns("Vehicles")}
    with engine.begin() as connection:
        if "BrandId" not in vehicle_columns:
            connection.execute(text(
                'ALTER TABLE "Vehicles" ADD COLUMN "BrandId" '
                'INTEGER REFERENCES "VehicleBrands"("Id") ON DELETE RESTRICT'
            ))
        if "ModelId" not in vehicle_columns:
            connection.execute(text(
                'ALTER TABLE "Vehicles" ADD COLUMN "ModelId" '
                'INTEGER REFERENCES "VehicleModels"("Id") ON DELETE RESTRICT'
            ))

        rows = connection.execute(text(
            'SELECT "Id", "Brand", "Model", "BrandId", "ModelId" '
            'FROM "Vehicles" ORDER BY "Id"'
        )).mappings().all()

        for row in rows:
            if row["BrandId"] is not None and row["ModelId"] is not None:
                continue

            brand_name = clean_catalog_name(row["Brand"] or "") or "Unknown"
            brand_key = normalize_catalog_name(brand_name)
            brand_id = connection.execute(
                text('SELECT "Id" FROM "VehicleBrands" WHERE "NormalizedName" = :key'),
                {"key": brand_key},
            ).scalar_one_or_none()
            if brand_id is None:
                connection.execute(text(
                    'INSERT INTO "VehicleBrands" '
                    '("Name", "NormalizedName", "IsActive", "CreatedAt", "UpdatedAt") '
                    'VALUES (:name, :key, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'
                ), {"name": brand_name, "key": brand_key})
                brand_id = connection.execute(
                    text('SELECT "Id" FROM "VehicleBrands" WHERE "NormalizedName" = :key'),
                    {"key": brand_key},
                ).scalar_one()

            model_name = clean_catalog_name(row["Model"] or "") or "Unknown"
            model_key = normalize_catalog_name(model_name)
            model_id = connection.execute(text(
                'SELECT "Id" FROM "VehicleModels" '
                'WHERE "BrandId" = :brand_id AND "NormalizedName" = :key'
            ), {"brand_id": brand_id, "key": model_key}).scalar_one_or_none()
            if model_id is None:
                connection.execute(text(
                    'INSERT INTO "VehicleModels" '
                    '("BrandId", "Name", "NormalizedName", "IsActive", "CreatedAt", "UpdatedAt") '
                    'VALUES (:brand_id, :name, :key, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'
                ), {"brand_id": brand_id, "name": model_name, "key": model_key})
                model_id = connection.execute(text(
                    'SELECT "Id" FROM "VehicleModels" '
                    'WHERE "BrandId" = :brand_id AND "NormalizedName" = :key'
                ), {"brand_id": brand_id, "key": model_key}).scalar_one()

            connection.execute(text(
                'UPDATE "Vehicles" SET "BrandId" = :brand_id, "ModelId" = :model_id '
                'WHERE "Id" = :vehicle_id'
            ), {"brand_id": brand_id, "model_id": model_id, "vehicle_id": row["Id"]})

        connection.execute(text(
            'CREATE INDEX IF NOT EXISTS "ix_vehicles_brand_id" ON "Vehicles" ("BrandId")'
        ))
        connection.execute(text(
            'CREATE INDEX IF NOT EXISTS "ix_vehicles_model_id" ON "Vehicles" ("ModelId")'
        ))
