from pathlib import Path
import sqlite3

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import Base
from app.models import (
    Company,
    User,
    Vehicle,
    WorkOrder,
    Location,
    Vendor,
    Part,
    LaborEntry,
)
from tests.test_fuel_migration import alembic_config

TABLES = [
    "Vendors",
    "PartCategories",
    "Parts",
    "PartInventories",
    "Technicians",
    "PurchaseOrders",
    "PurchaseOrderItems",
    "InventoryTransactions",
    "WorkOrderParts",
    "WorkOrderTechnicians",
    "LaborEntries",
    "WorkOrderVendorCharges",
]


def legacy_fixture(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(
        engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in TABLES]
    )
    with Session(engine) as db:
        db.add_all(
            [
                Company(id=1, name="Legacy", slug="legacy"),
                Company(id=2, name="Second", slug="second"),
            ]
        )
        db.flush()
        db.add(
            User(
                id=1,
                company_id=1,
                email="test@example.com",
                full_name="Admin",
                hashed_password="unused",
                role="admin",
            )
        )
        db.add(Location(id=1, company_id=1, code="MAIN", name="Main"))
        db.add(
            Vehicle(
                id=1,
                company_id=1,
                brand="Ford",
                model="Transit",
                fuel_type="Diesel",
                vehicle_location="Depot",
                license_plate="01-123-AA",
                registration_country="XK",
                license_plate_normalized="01123AA",
            )
        )
        db.flush()
        db.add(
            WorkOrder(
                id=1,
                company_id=1,
                vehicle_id=1,
                title="Legacy work",
                parts_cost=20,
                labor_cost=30,
                total_cost=55,
                external_vendor_cost=5,
            )
        )
        db.commit()
    engine.dispose()
    with sqlite3.connect(path) as c:
        c.executescript(
            (Path(__file__).parent / "fixtures/legacy_supply_schema.sql").read_text()
        )
        inserts = {
            "Vendors": {
                "Id": 1,
                "CompanyId": 1,
                "Name": "Legacy supplier",
                "VendorType": "Workshop",
                "SupportedServices": "[]",
                "Status": "Active",
                "Archived": 0,
                "CreatedAt": "2026-08-01",
                "UpdatedAt": "2026-08-01",
            },
            "PartCategories": {
                "Id": 1,
                "Name": "Filters",
                "IsActive": 1,
                "Archived": 0,
                "CreatedAt": "2026-08-01",
                "UpdatedAt": "2026-08-01",
            },
            "Parts": {
                "Id": 1,
                "CompanyId": 1,
                "PartNumber": "OLD-1",
                "Name": "Filter",
                "CategoryId": 1,
                "Unit": "piece",
                "UnitCost": 10,
                "SupplierId": 1,
                "MinimumStock": 2,
                "IsActive": 1,
                "Archived": 0,
                "CreatedAt": "2026-08-01",
                "UpdatedAt": "2026-08-01",
            },
            "PartInventories": {
                "Id": 1,
                "PartId": 1,
                "LocationId": 1,
                "QuantityOnHand": 8,
                "UpdatedAt": "2026-08-01",
            },
            "Technicians": {
                "Id": 1,
                "CompanyId": 1,
                "EmployeeNumber": "EMP-1",
                "FullName": "Technician",
                "HourlyRate": 30,
                "Status": "Active",
                "Archived": 0,
                "CreatedAt": "2026-08-01",
                "UpdatedAt": "2026-08-01",
            },
            "PurchaseOrders": {
                "Id": 1,
                "CompanyId": 1,
                "OrderNumber": "OLD-PO",
                "VendorId": 1,
                "StorageLocationId": 1,
                "Status": "Partially Received",
                "Subtotal": 100,
                "TaxAmount": 0,
                "DiscountAmount": 0,
                "TotalAmount": 100,
                "Archived": 0,
                "CreatedAt": "2026-08-01",
                "UpdatedAt": "2026-08-01",
            },
            "PurchaseOrderItems": {
                "Id": 1,
                "CompanyId": 1,
                "PurchaseOrderId": 1,
                "PartId": 1,
                "QuantityOrdered": 10,
                "QuantityReceived": 4,
                "UnitCost": 10,
                "LineTotal": 100,
            },
            "InventoryTransactions": {
                "Id": 1,
                "CompanyId": 1,
                "PartId": 1,
                "TransactionType": "Issue to Work Order",
                "Quantity": 2,
                "UnitCost": 10,
                "FromLocationId": 1,
                "WorkOrderId": 1,
                "PerformedBy": 1,
                "CreatedAt": "2026-08-01",
            },
            "WorkOrderParts": {
                "Id": 1,
                "CompanyId": 1,
                "WorkOrderId": 1,
                "PartId": 1,
                "LocationId": 1,
                "InventoryTransactionId": 1,
                "Quantity": 2,
                "UnitCost": 10,
                "TotalCost": 20,
                "Archived": 0,
                "CreatedAt": "2026-08-01",
            },
            "WorkOrderTechnicians": {
                "Id": 1,
                "WorkOrderId": 1,
                "TechnicianId": 1,
                "EstimatedHours": 2,
                "CreatedAt": "2026-08-01",
            },
            "LaborEntries": {
                "Id": 1,
                "WorkOrderId": 1,
                "TechnicianId": 1,
                "ActualHours": 1,
                "HourlyRate": 30,
                "LaborCost": 30,
                "Archived": 0,
                "CreatedAt": "2026-08-01",
                "UpdatedAt": "2026-08-01",
            },
            "WorkOrderVendorCharges": {
                "Id": 1,
                "WorkOrderId": 1,
                "VendorId": 1,
                "Description": "Diagnostic",
                "Amount": 5,
                "Archived": 0,
                "CreatedAt": "2026-08-01",
            },
        }
        for name, values in inserts.items():
            cols = ",".join('"' + k + '"' for k in values)
            c.execute(
                f'INSERT INTO "{name}" ({cols}) VALUES ({",".join("?" for _ in values)})',
                list(values.values()),
            )
        c.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        c.execute("INSERT INTO alembic_version VALUES ('20260812_0016')")
        c.commit()
    return inserts


def migrate(path, monkeypatch):
    url = f"sqlite:///{path}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_config(url), "head")
    finally:
        get_settings.cache_clear()


def test_populated_legacy_supply_preserves_every_row_and_maps_all_columns(
    tmp_path, monkeypatch
):
    path = tmp_path / "legacy.db"
    inserts = legacy_fixture(path)
    migrate(path, monkeypatch)
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as c:
        assert not c.exec_driver_sql("PRAGMA foreign_key_check").all()
        for name, original in inserts.items():
            row = c.execute(text(f'SELECT * FROM "{name}"')).mappings().one()
            for key, value in original.items():
                assert row[key] == value, (name, key)
            assert row["CompanyId"] == 1
            actual = {col["name"] for col in inspect(c).get_columns(name)}
            assert {col.name for col in Base.metadata.tables[name].columns} == actual
        assert (
            c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "20260913_0017"
        )
    with Session(engine) as db:
        assert db.get(Part, 1).unit_cost == 10
        assert db.get(LaborEntry, 1).actual_hours == 1
        db.add(Vendor(company_id=2, name="Legacy supplier", vendor_type="Workshop"))
        db.commit()
    migrate(path, monkeypatch)  # repeat is a no-op
    engine.dispose()


def test_fresh_install_has_complete_supply_schema(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    migrate(path, monkeypatch)
    with create_engine(f"sqlite:///{path}").connect() as c:
        assert set(TABLES) <= set(inspect(c).get_table_names())
        assert not c.exec_driver_sql("PRAGMA foreign_key_check").all()
        for name in TABLES:
            assert "CompanyId" in {x["name"] for x in inspect(c).get_columns(name)}


def test_ambiguous_tenant_links_abort_without_changing_migration_or_rows(
    tmp_path, monkeypatch
):
    path = tmp_path / "invalid.db"
    legacy_fixture(path)
    with sqlite3.connect(path) as c:
        c.execute('UPDATE "Parts" SET "CompanyId"=2')
        c.commit()
    with pytest.raises(RuntimeError, match="Company mismatch"):
        migrate(path, monkeypatch)
    with sqlite3.connect(path) as c:
        assert (
            c.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "20260812_0016"
        )
        assert "Manufacturer" not in {
            r[1] for r in c.execute('PRAGMA table_info("Parts")')
        }
        assert c.execute('SELECT "CompanyId" FROM "Parts"').fetchone()[0] == 2
        assert (
            c.execute('SELECT count(*) FROM "InventoryTransactions"').fetchone()[0] == 1
        )


def test_complete_install_without_supply_tables_creates_only_missing_tables(
    tmp_path, monkeypatch
):
    path = tmp_path / "without-supply.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(
        engine,
        tables=[t for t in Base.metadata.tables.values() if t.name not in TABLES],
    )
    with engine.begin() as c:
        c.execute(
            text(
                'INSERT INTO "Companies" ("Id", "Name", "Slug", "IsActive", "CreatedAt", "UpdatedAt") VALUES (1, \'Legacy\', \'legacy\', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'
            )
        )
        c.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        )
        c.execute(text("INSERT INTO alembic_version VALUES ('20260812_0016')"))
    engine.dispose()
    migrate(path, monkeypatch)
    with create_engine(f"sqlite:///{path}").connect() as c:
        assert set(TABLES) <= set(inspect(c).get_table_names())
        assert not c.exec_driver_sql("PRAGMA foreign_key_check").all()
        assert (
            c.execute(text('SELECT "Name" FROM "Companies"')).scalar_one() == "Legacy"
        )
        assert any(
            i["column_names"] == ["PartNumber"] for i in inspect(c).get_indexes("Parts")
        )
