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
            )).scalar_one() == "20260719_0006"

        with pytest.raises(RuntimeError, match="Cannot downgrade.*KWH"):
            command.downgrade(config, "20260718_0004")
    finally:
        get_settings.cache_clear()
        engine.dispose()
