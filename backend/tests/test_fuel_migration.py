from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.core.config import get_settings


def alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("prepend_sys_path", str(backend_dir))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def create_legacy_database(path: Path) -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(sa.text(
            'CREATE TABLE "Vehicles" ('
            '"Id" INTEGER PRIMARY KEY, "LicensePlate" VARCHAR NOT NULL)'
        ))
        connection.execute(sa.text(
            'CREATE TABLE "VehicleFuels" ('
            '"Id" INTEGER PRIMARY KEY, "VehicleId" INTEGER NOT NULL, '
            '"RefuelDate" DATETIME NOT NULL, "Liters" NUMERIC(12, 3) NOT NULL, '
            '"CostPerLiter" NUMERIC(12, 3) NOT NULL, '
            '"TotalCost" NUMERIC(12, 2) NOT NULL, "FuelType" VARCHAR NOT NULL, '
            '"Location" VARCHAR NOT NULL, "StationName" VARCHAR NOT NULL, '
            '"BillFilePath" VARCHAR, "OdometerKm" INTEGER NOT NULL, '
            '"Archived" BOOLEAN NOT NULL DEFAULT 0, "ArchivedAt" DATETIME, '
            '"ArchivedBy" INTEGER)'
        ))
        connection.execute(sa.text(
            'CREATE TABLE "AuditLogs" ('
            '"Id" INTEGER PRIMARY KEY, "Username" VARCHAR, "Action" VARCHAR NOT NULL, '
            '"EntityType" VARCHAR NOT NULL, "EntityId" INTEGER, "OldValues" JSON, '
            '"NewValues" JSON, "Description" TEXT, "CreatedAt" DATETIME NOT NULL)'
        ))
        connection.execute(sa.text(
            'CREATE TABLE "alembic_version" (version_num VARCHAR(32) NOT NULL)'
        ))
        connection.execute(sa.text(
            'INSERT INTO "alembic_version" (version_num) VALUES (\'20260718_0004\')'
        ))
        connection.execute(sa.text(
            'INSERT INTO "Vehicles" ("Id", "LicensePlate") VALUES '
            '(1, \'01-301-AA\'), (2, \'01-302-AA\')'
        ))
        connection.execute(sa.text(
            'INSERT INTO "VehicleFuels" '
            '("Id", "VehicleId", "RefuelDate", "Liters", "CostPerLiter", '
            '"TotalCost", "FuelType", "Location", "StationName", "OdometerKm") '
            "VALUES "
            "(11, 1, '2026-07-01', 45.5, 1.35, 61.43, 'Diesel', "
            "'Prishtina', 'Fuel Station', 10000), "
            "(12, 2, '2026-07-02', 62.4, 0.18, 11.23, 'Electric', "
            "'Tirana', 'Legacy Charger', 20000)"
        ))
    return engine


def create_pre_consolidation_document_database(path: Path) -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(sa.text(
            'CREATE TABLE "DocumentRequirements" ('
            '"Id" INTEGER PRIMARY KEY, "DocumentType" VARCHAR NOT NULL, '
            '"AppliesToVehicleCategory" VARCHAR, "AppliesToCountry" VARCHAR, '
            '"AppliesToDriver" BOOLEAN NOT NULL, "IsActive" BOOLEAN NOT NULL, '
            '"UpdatedAt" DATETIME NOT NULL)'
        ))
        connection.execute(sa.text(
            'CREATE TABLE "VehiclePapers" ('
            '"Id" INTEGER PRIMARY KEY, "DocumentType" VARCHAR NOT NULL, '
            '"RequirementId" INTEGER, "FilePath" VARCHAR NOT NULL, '
            '"UpdatedAt" DATETIME NOT NULL)'
        ))
        connection.execute(sa.text(
            'CREATE TABLE "DocumentVersions" ('
            '"Id" INTEGER PRIMARY KEY, "DocumentId" INTEGER NOT NULL, '
            '"FilePath" VARCHAR NOT NULL)'
        ))
        connection.execute(sa.text(
            'CREATE TABLE "alembic_version" (version_num VARCHAR(32) NOT NULL)'
        ))
        connection.execute(sa.text(
            'INSERT INTO "alembic_version" (version_num) VALUES (\'20260727_0010\')'
        ))
        connection.execute(sa.text(
            'INSERT INTO "DocumentRequirements" '
            '("Id", "DocumentType", "AppliesToCountry", "AppliesToDriver", "IsActive", "UpdatedAt") '
            "VALUES "
            "(1, 'Registration', NULL, 0, 1, CURRENT_TIMESTAMP), "
            "(2, 'Kosovo registration documentation', 'XK', 0, 1, CURRENT_TIMESTAMP), "
            "(3, 'Albania registration documentation', 'AL', 0, 1, CURRENT_TIMESTAMP)"
        ))
        connection.execute(sa.text(
            'INSERT INTO "VehiclePapers" '
            '("Id", "DocumentType", "RequirementId", "FilePath", "UpdatedAt") '
            "VALUES (10, 'Kosovo registration documentation', 2, "
            "'uploads/documents/registration.pdf', CURRENT_TIMESTAMP)"
        ))
        connection.execute(sa.text(
            'INSERT INTO "DocumentVersions" ("Id", "DocumentId", "FilePath") '
            "VALUES (20, 10, 'uploads/documents/registration-v1.pdf')"
        ))
    return engine


def test_migration_preserves_values_and_marks_electric_rows_for_review(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "legacy-fuel.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_legacy_database(database_path)
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = alembic_config(database_url)
    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            rows = connection.execute(sa.text(
                'SELECT "Id", "Liters", "CostPerLiter", "Quantity", '
                '"EnergyUnit", "UnitCost", "UnitReviewRequired" '
                'FROM "VehicleFuels" ORDER BY "Id"'
            )).mappings().all()
            assert len(rows) == 2
            assert rows[0]["Quantity"] == 45.5
            assert rows[0]["EnergyUnit"] == "L"
            assert rows[0]["UnitCost"] == 1.35
            assert not rows[0]["UnitReviewRequired"]
            assert rows[1]["Quantity"] == 62.4
            assert rows[1]["EnergyUnit"] == "KWH"
            assert rows[1]["UnitCost"] == 0.18
            assert rows[1]["UnitReviewRequired"]
            assert rows[1]["Liters"] == 62.4
            assert rows[1]["CostPerLiter"] == 0.18

            audit = connection.execute(sa.text(
                'SELECT "Action", "EntityId" FROM "AuditLogs"'
            )).mappings().one()
            assert audit["Action"] == "Historical Electric record migrated to kWh"
            assert audit["EntityId"] == 12
            assert connection.execute(sa.text(
                'SELECT version_num FROM alembic_version'
                    )).scalar_one() == "20260803_0014"

        with pytest.raises(RuntimeError, match="Cannot downgrade.*KWH"):
            command.downgrade(config, "20260718_0004")
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_registration_consolidation_relinks_documents_without_losing_versions(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "registration-consolidation.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_pre_consolidation_document_database(database_path)
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_config(database_url), "head")
        with engine.connect() as connection:
            active = connection.execute(sa.text(
                'SELECT "DocumentType" FROM "DocumentRequirements" '
                'WHERE "IsActive" = 1 ORDER BY "Id"'
            )).scalars().all()
            assert active == ["Registration"]
            paper = connection.execute(sa.text(
                'SELECT "DocumentType", "RequirementId", "FilePath" '
                'FROM "VehiclePapers" WHERE "Id" = 10'
            )).mappings().one()
            assert paper == {
                "DocumentType": "Registration",
                "RequirementId": 1,
                "FilePath": "uploads/documents/registration.pdf",
            }
            version = connection.execute(sa.text(
                'SELECT "Id", "DocumentId", "FilePath" '
                'FROM "DocumentVersions" WHERE "Id" = 20'
            )).mappings().one()
            assert version == {
                "Id": 20,
                "DocumentId": 10,
                "FilePath": "uploads/documents/registration-v1.pdf",
            }
            assert connection.execute(sa.text(
                'SELECT version_num FROM alembic_version'
            )).scalar_one() == "20260803_0014"
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_accident_workflow_migration_preserves_legacy_accidents_and_files(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy-accidents.db"
    database_url = f"sqlite:///{database_path}"
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        for statement in (
            'CREATE TABLE "Users" ("Id" INTEGER PRIMARY KEY)',
            'CREATE TABLE "Vehicles" ("Id" INTEGER PRIMARY KEY)',
            'CREATE TABLE "Drivers" ("Id" INTEGER PRIMARY KEY)',
            'CREATE TABLE "VehicleAssignments" ("Id" INTEGER PRIMARY KEY)',
            'CREATE TABLE "VehicleReservations" ("Id" INTEGER PRIMARY KEY)',
            'CREATE TABLE "VehiclePapers" ("Id" INTEGER PRIMARY KEY)',
            'CREATE TABLE "WorkOrders" ("Id" INTEGER PRIMARY KEY)',
            'CREATE TABLE "VehicleAccidents" ('
            '"Id" INTEGER PRIMARY KEY, "VehicleId" INTEGER NOT NULL, '
            '"VehicleAssignmentId" INTEGER, "AccidentDate" DATETIME NOT NULL, '
            '"Location" VARCHAR NOT NULL, "Description" TEXT, '
            '"Archived" BOOLEAN NOT NULL DEFAULT 0, "ArchivedAt" DATETIME, "ArchivedBy" INTEGER, '
            'FOREIGN KEY("VehicleId") REFERENCES "Vehicles"("Id"), '
            'FOREIGN KEY("VehicleAssignmentId") REFERENCES "VehicleAssignments"("Id"), '
            'FOREIGN KEY("ArchivedBy") REFERENCES "Users"("Id"))',
            'CREATE TABLE "AccidentFiles" ('
            '"Id" INTEGER PRIMARY KEY, "VehicleAccidentId" INTEGER NOT NULL, "FilePath" VARCHAR NOT NULL, '
            'FOREIGN KEY("VehicleAccidentId") REFERENCES "VehicleAccidents"("Id"))',
            'CREATE INDEX "ix_vehicleaccidents_vehicle_assignment_id" '
            'ON "VehicleAccidents" ("VehicleAssignmentId")',
            'CREATE TABLE "alembic_version" (version_num VARCHAR(32) NOT NULL)',
            'INSERT INTO "alembic_version" (version_num) VALUES (\'20260727_0011\')',
            'INSERT INTO "Vehicles" ("Id") VALUES (7)',
            'INSERT INTO "VehicleAccidents" '
            '("Id", "VehicleId", "AccidentDate", "Location", "Description", "Archived") '
            "VALUES (42, 7, '2026-07-01 08:30:00', 'Legacy road', 'Preserve me', 0)",
            'INSERT INTO "AccidentFiles" ("Id", "VehicleAccidentId", "FilePath") '
            "VALUES (91, 42, 'uploads/accidents/legacy.jpg')",
        ):
            connection.execute(sa.text(statement))
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_config(database_url), "head")
        with engine.connect() as connection:
            accident = connection.execute(sa.text(
                'SELECT "Id", "VehicleId", "AccidentDate", "Location", "Description", '
                '"Severity", "Status", "VehicleAvailableAfterAccident" '
                'FROM "VehicleAccidents" WHERE "Id" = 42'
            )).mappings().one()
            assert accident["Description"] == "Preserve me"
            assert accident["Severity"] == "Minor"
            assert accident["Status"] == "Reported"
            assert accident["VehicleAvailableAfterAccident"]
            file_row = connection.execute(sa.text(
                'SELECT "Id", "VehicleAccidentId", "FilePath" FROM "AccidentFiles" WHERE "Id" = 91'
            )).mappings().one()
            assert file_row["VehicleAccidentId"] == 42
            assert file_row["FilePath"] == "uploads/accidents/legacy.jpg"
            assert connection.execute(sa.text(
                'SELECT version_num FROM alembic_version'
            )).scalar_one() == "20260803_0014"
    finally:
        engine.dispose()
        get_settings.cache_clear()
