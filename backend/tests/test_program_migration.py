import sqlite3
from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings
from app.db.session import Base
from tests.test_fuel_migration import alembic_config

PROGRAM_TABLES = {"ServicePrograms", "ServiceProgramTasks", "ServiceProgramRules", "VehicleServicePrograms", "ServiceProgramReminders"}


def test_program_migration_preserves_manual_history_and_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "program-migration.db"
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values() if t.name not in PROGRAM_TABLES])
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)')
        db.execute("INSERT INTO alembic_version VALUES ('20260913_0017')")
        db.execute('''INSERT INTO VehicleServices (Id, VehicleId, ServiceType, ServiceDate, NextServiceOdometerKm, Source, Status, ReminderStatus, Archived, CreatedAt, UpdatedAt, CompanyId)
                      VALUES (1, 1, 'Oil Change', '2026-01-01', 20000, 'Manual', 'Completed', 'Upcoming', 0, '2026-01-01', '2026-01-01', 1)''')
        original = db.execute('SELECT * FROM VehicleServices').fetchall()
    monkeypatch.setenv("DATABASE_URL", url); get_settings.cache_clear()
    try:
        config = alembic_config(url)
        command.upgrade(config, "head")
        assert PROGRAM_TABLES <= set(inspect(engine).get_table_names())
        for name in PROGRAM_TABLES:
            assert {c["name"] for c in inspect(engine).get_columns(name)} == {c.name for c in Base.metadata.tables[name].columns}
        command.downgrade(config, "20260913_0017")
        assert not PROGRAM_TABLES.intersection(inspect(engine).get_table_names())
        command.upgrade(config, "head")
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT * FROM VehicleServices').fetchall() == original
            assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == "20260914_0019"
    finally:
        get_settings.cache_clear(); engine.dispose()


def test_empty_database_can_upgrade_to_program_head(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    monkeypatch.setenv("DATABASE_URL", url); get_settings.cache_clear()
    try:
        command.upgrade(alembic_config(url), "head")
        engine = create_engine(url)
        assert PROGRAM_TABLES <= set(inspect(engine).get_table_names())
        engine.dispose()
    finally:
        get_settings.cache_clear()
