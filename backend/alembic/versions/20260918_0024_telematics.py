"""Provider-neutral telematics foundation (frozen schema)."""
from alembic import op
import sqlalchemy as sa

revision = "20260918_0024"
down_revision = "20260917_0023"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    # Historical domain-only fixtures may omit Vehicles, as earlier migrations permit.
    columns = {c["name"] for c in sa.inspect(bind).get_columns("Vehicles")} if "Vehicles" in existing else set()
    if "Vehicles" in existing and "TelematicsOdometerAt" not in columns:
        op.add_column("Vehicles", sa.Column("TelematicsOdometerAt", sa.DateTime()))
    if "Vehicles" in existing and "OdometerManualOverride" not in columns:
        op.add_column("Vehicles", sa.Column("OdometerManualOverride", sa.Boolean(), nullable=False, server_default="0"))
    if 'IntegrationConnections' not in existing:
        op.create_table('IntegrationConnections',
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('Status', sa.String(length=30), nullable=False),
            sa.Column('CredentialsReference', sa.String(length=200), nullable=True),
            sa.Column('LastSyncAt', sa.DateTime(), nullable=True),
            sa.Column('LastError', sa.String(length=100), nullable=True),
            sa.Column('Settings', sa.JSON(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.CheckConstraint('"Status" IN (\'NotConfigured\', \'Ready\', \'Disabled\')', name='ck_telematics_connection_status'),
        )
        op.create_index('ix_IntegrationConnections_CompanyId', 'IntegrationConnections', ['CompanyId'], unique=False)
    if 'ExternalVehicleMappings' not in existing:
        op.create_table('ExternalVehicleMappings',
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('ExternalVehicleId', sa.String(length=200), nullable=False),
            sa.Column('Vin', sa.String(length=50), nullable=True),
            sa.Column('ExternalDeviceId', sa.String(length=200), nullable=True),
            sa.Column('OdometerSyncEnabled', sa.Boolean(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalDeviceId', name='uq_telematics_device'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalVehicleId', name='uq_telematics_external_vehicle'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'VehicleId', name='uq_telematics_internal_vehicle'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'Vin', name='uq_telematics_vin'),
        )
        op.create_index('ix_ExternalVehicleMappings_CompanyId', 'ExternalVehicleMappings', ['CompanyId'], unique=False)
    if 'VehicleLocationEvents' not in existing:
        op.create_table('VehicleLocationEvents',
            sa.Column('Latitude', sa.Numeric(precision=10, scale=7), nullable=False),
            sa.Column('Longitude', sa.Numeric(precision=10, scale=7), nullable=False),
            sa.Column('SpeedKph', sa.Numeric(precision=9, scale=3), nullable=True),
            sa.Column('Heading', sa.Numeric(precision=7, scale=3), nullable=True),
            sa.Column('Ignition', sa.Boolean(), nullable=True),
            sa.Column('Idling', sa.Boolean(), nullable=True),
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('ExternalEventId', sa.String(length=200), nullable=False),
            sa.Column('PayloadHash', sa.String(length=64), nullable=False),
            sa.Column('OccurredAt', sa.DateTime(), nullable=False),
            sa.Column('ReceivedAt', sa.DateTime(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.CheckConstraint('"Latitude" BETWEEN -90 AND 90 AND "Longitude" BETWEEN -180 AND 180', name='ck_telematics_coordinates'),
            sa.CheckConstraint('"SpeedKph" >= 0 AND "Heading" >= 0 AND "Heading" < 360', name='ck_telematics_motion'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalEventId', name='uq_VehicleLocationEvents_event'),
        )
        op.create_index('ix_VehicleLocationEvents_CompanyId', 'VehicleLocationEvents', ['CompanyId'], unique=False)
        op.create_index('ix_VehicleLocationEvents_vehicle_time', 'VehicleLocationEvents', ['CompanyId', 'VehicleId', 'OccurredAt'], unique=False)
    if 'TelematicsTrips' not in existing:
        op.create_table('TelematicsTrips',
            sa.Column('EndedAt', sa.DateTime(), nullable=False),
            sa.Column('DistanceKm', sa.Numeric(precision=14, scale=3), nullable=False),
            sa.Column('IdleSeconds', sa.Integer(), nullable=False),
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('ExternalEventId', sa.String(length=200), nullable=False),
            sa.Column('PayloadHash', sa.String(length=64), nullable=False),
            sa.Column('OccurredAt', sa.DateTime(), nullable=False),
            sa.Column('ReceivedAt', sa.DateTime(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.CheckConstraint('"EndedAt" >= "OccurredAt"', name='ck_telematics_trip_time'),
            sa.CheckConstraint('"DistanceKm" >= 0 AND "IdleSeconds" >= 0', name='ck_telematics_trip_values'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalEventId', name='uq_TelematicsTrips_event'),
        )
        op.create_index('ix_TelematicsTrips_CompanyId', 'TelematicsTrips', ['CompanyId'], unique=False)
        op.create_index('ix_TelematicsTrips_vehicle_time', 'TelematicsTrips', ['CompanyId', 'VehicleId', 'OccurredAt'], unique=False)
    if 'OdometerEvents' not in existing:
        op.create_table('OdometerEvents',
            sa.Column('OdometerKm', sa.Numeric(precision=14, scale=3), nullable=False),
            sa.Column('Confidence', sa.Numeric(precision=5, scale=4), nullable=False),
            sa.Column('SyncResult', sa.String(length=40), nullable=False),
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('ExternalEventId', sa.String(length=200), nullable=False),
            sa.Column('PayloadHash', sa.String(length=64), nullable=False),
            sa.Column('OccurredAt', sa.DateTime(), nullable=False),
            sa.Column('ReceivedAt', sa.DateTime(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.CheckConstraint('"OdometerKm" >= 0 AND "Confidence" BETWEEN 0 AND 1', name='ck_telematics_odometer'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalEventId', name='uq_OdometerEvents_event'),
        )
        op.create_index('ix_OdometerEvents_CompanyId', 'OdometerEvents', ['CompanyId'], unique=False)
        op.create_index('ix_OdometerEvents_vehicle_time', 'OdometerEvents', ['CompanyId', 'VehicleId', 'OccurredAt'], unique=False)
    if 'EngineHourEvents' not in existing:
        op.create_table('EngineHourEvents',
            sa.Column('EngineHours', sa.Numeric(precision=14, scale=3), nullable=False),
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('ExternalEventId', sa.String(length=200), nullable=False),
            sa.Column('PayloadHash', sa.String(length=64), nullable=False),
            sa.Column('OccurredAt', sa.DateTime(), nullable=False),
            sa.Column('ReceivedAt', sa.DateTime(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.CheckConstraint('"EngineHours" >= 0', name='ck_telematics_engine_hours'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalEventId', name='uq_EngineHourEvents_event'),
        )
        op.create_index('ix_EngineHourEvents_CompanyId', 'EngineHourEvents', ['CompanyId'], unique=False)
        op.create_index('ix_EngineHourEvents_vehicle_time', 'EngineHourEvents', ['CompanyId', 'VehicleId', 'OccurredAt'], unique=False)
    if 'FuelLevelEvents' not in existing:
        op.create_table('FuelLevelEvents',
            sa.Column('FuelPercent', sa.Numeric(precision=6, scale=3), nullable=False),
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('ExternalEventId', sa.String(length=200), nullable=False),
            sa.Column('PayloadHash', sa.String(length=64), nullable=False),
            sa.Column('OccurredAt', sa.DateTime(), nullable=False),
            sa.Column('ReceivedAt', sa.DateTime(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.CheckConstraint('"FuelPercent" BETWEEN 0 AND 100', name='ck_telematics_fuel'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalEventId', name='uq_FuelLevelEvents_event'),
        )
        op.create_index('ix_FuelLevelEvents_CompanyId', 'FuelLevelEvents', ['CompanyId'], unique=False)
        op.create_index('ix_FuelLevelEvents_vehicle_time', 'FuelLevelEvents', ['CompanyId', 'VehicleId', 'OccurredAt'], unique=False)
    if 'BatteryLevelEvents' not in existing:
        op.create_table('BatteryLevelEvents',
            sa.Column('SocPercent', sa.Numeric(precision=6, scale=3), nullable=False),
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('ExternalEventId', sa.String(length=200), nullable=False),
            sa.Column('PayloadHash', sa.String(length=64), nullable=False),
            sa.Column('OccurredAt', sa.DateTime(), nullable=False),
            sa.Column('ReceivedAt', sa.DateTime(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.CheckConstraint('"SocPercent" BETWEEN 0 AND 100', name='ck_telematics_battery'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalEventId', name='uq_BatteryLevelEvents_event'),
        )
        op.create_index('ix_BatteryLevelEvents_CompanyId', 'BatteryLevelEvents', ['CompanyId'], unique=False)
        op.create_index('ix_BatteryLevelEvents_vehicle_time', 'BatteryLevelEvents', ['CompanyId', 'VehicleId', 'OccurredAt'], unique=False)
    if 'DiagnosticCodeEvents' not in existing:
        op.create_table('DiagnosticCodeEvents',
            sa.Column('Code', sa.String(length=50), nullable=False),
            sa.Column('Active', sa.Boolean(), nullable=False),
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('ExternalEventId', sa.String(length=200), nullable=False),
            sa.Column('PayloadHash', sa.String(length=64), nullable=False),
            sa.Column('OccurredAt', sa.DateTime(), nullable=False),
            sa.Column('ReceivedAt', sa.DateTime(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalEventId', name='uq_DiagnosticCodeEvents_event'),
        )
        op.create_index('ix_DiagnosticCodeEvents_CompanyId', 'DiagnosticCodeEvents', ['CompanyId'], unique=False)
        op.create_index('ix_DiagnosticCodeEvents_vehicle_time', 'DiagnosticCodeEvents', ['CompanyId', 'VehicleId', 'OccurredAt'], unique=False)
    if 'DriverBehaviorEvents' not in existing:
        op.create_table('DriverBehaviorEvents',
            sa.Column('Behavior', sa.String(length=50), nullable=False),
            sa.Column('DurationSeconds', sa.Integer(), nullable=True),
            sa.Column('Id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('ConnectionId', sa.Integer(), sa.ForeignKey('IntegrationConnections.Id'), nullable=False),
            sa.Column('VehicleId', sa.Integer(), sa.ForeignKey('Vehicles.Id'), nullable=False),
            sa.Column('Provider', sa.String(length=50), nullable=False),
            sa.Column('ExternalEventId', sa.String(length=200), nullable=False),
            sa.Column('PayloadHash', sa.String(length=64), nullable=False),
            sa.Column('OccurredAt', sa.DateTime(), nullable=False),
            sa.Column('ReceivedAt', sa.DateTime(), nullable=False),
            sa.Column('CompanyId', sa.Integer(), sa.ForeignKey('Companies.Id', ondelete='RESTRICT'), nullable=False, server_default='1'),
            sa.CheckConstraint('"DurationSeconds" >= 0', name='ck_telematics_behavior'),
            sa.UniqueConstraint('CompanyId', 'ConnectionId', 'ExternalEventId', name='uq_DriverBehaviorEvents_event'),
        )
        op.create_index('ix_DriverBehaviorEvents_CompanyId', 'DriverBehaviorEvents', ['CompanyId'], unique=False)
        op.create_index('ix_DriverBehaviorEvents_vehicle_time', 'DriverBehaviorEvents', ['CompanyId', 'VehicleId', 'OccurredAt'], unique=False)


def downgrade():
    op.drop_table('DriverBehaviorEvents')
    op.drop_table('DiagnosticCodeEvents')
    op.drop_table('BatteryLevelEvents')
    op.drop_table('FuelLevelEvents')
    op.drop_table('EngineHourEvents')
    op.drop_table('OdometerEvents')
    op.drop_table('TelematicsTrips')
    op.drop_table('VehicleLocationEvents')
    op.drop_table('ExternalVehicleMappings')
    op.drop_table('IntegrationConnections')
    op.drop_column("Vehicles", "OdometerManualOverride")
    op.drop_column("Vehicles", "TelematicsOdometerAt")
