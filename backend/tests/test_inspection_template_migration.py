import sqlite3
from alembic import command
from sqlalchemy import create_engine, inspect
from app.core.config import get_settings
from app.db.session import Base
from tests.test_fuel_migration import alembic_config

TABLES = {'InspectionTemplates', 'InspectionTemplateItems', 'InspectionTemplateAssignments', 'InspectionSchedules'}


def test_migration_upgrades_real_old_schema_without_rewriting_results(tmp_path, monkeypatch):
    path = tmp_path / 'inspection-migration.db'
    url = f'sqlite:///{path}'
    monkeypatch.setenv('DATABASE_URL', url); get_settings.cache_clear()
    try:
        config = alembic_config(url)
        # Also exercises the existing bootstrap that creates current metadata.
        command.upgrade(config, 'head')
        command.downgrade(config, '20260914_0018')
        with sqlite3.connect(path) as db:
            db.execute('''INSERT INTO Inspections (Id, VehicleId, InspectionType, InspectionDate, OverallStatus, Notes, Archived, CreatedAt, UpdatedAt, CompanyId)
                VALUES (7, 1, 'Daily', '2020-01-01', 'Failed', 'Original inspection', 0, '2020-01-01', '2020-01-01', 1)''')
            db.execute('''INSERT INTO InspectionItems (Id, InspectionId, ItemName, Status, Comment, CompanyId)
                VALUES (9, 7, 'Historic label', 'Fail', 'Original evidence', 1)''')
            columns = {table: [row[1] for row in db.execute(f'PRAGMA table_info({table})')] for table in ['Inspections','InspectionItems']}
            old = {table: db.execute(f'SELECT * FROM {table}').fetchall() for table in columns}
        engine = create_engine(url)
        assert not TABLES.intersection(inspect(engine).get_table_names())
        command.upgrade(config, 'head')
        for table in TABLES | {"Inspections", "InspectionItems", "WorkOrders"}:
            assert {c['name'] for c in inspect(engine).get_columns(table)} == set(Base.metadata.tables[table].c.keys())
        with sqlite3.connect(path) as db:
            for table, fields in columns.items():
                fields = ', '.join(f'"{field}"' for field in fields)
                assert db.execute(f'SELECT {fields} FROM {table}').fetchall() == old[table]
            assert db.execute('SELECT TemplateId, TemplateSnapshot, CompletedAt FROM Inspections').fetchone() == (None,None,None)
            assert db.execute('SELECT ItemSnapshot FROM InspectionItems').fetchone() == (None,)
            grants = db.execute('''SELECT r.Code FROM Roles r JOIN RolePermissions rp ON rp.RoleId=r.Id
                JOIN Permissions p ON p.Id=rp.PermissionId WHERE p.Code='inspection_templates.manage' ''').fetchall()
            assert set(grants) == {('admin',), ('fleet_manager',)}
        command.downgrade(config, '20260914_0018')
        command.upgrade(config, 'head')
        engine.dispose()
    finally:
        get_settings.cache_clear()
