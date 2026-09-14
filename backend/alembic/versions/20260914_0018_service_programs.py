"""Reusable preventive maintenance programs; manual reminders remain untouched."""
from alembic import op
import sqlalchemy as sa

revision = "20260914_0018"
down_revision = "20260913_0017"
branch_labels = None
depends_on = None

def upgrade():
    # The historical bootstrap revision creates current metadata on empty DBs.
    # Preserve that upgrade path as well as genuine pre-program databases.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'ServicePrograms' not in existing:
        op.create_table('ServicePrograms',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('Name', sa.String(length=150), nullable=False),
        sa.Column('Description', sa.Text(), nullable=True),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('Archived', sa.Boolean(), nullable=False),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.Column('UpdatedAt', sa.DateTime(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('Id'),
        sa.UniqueConstraint('CompanyId', 'Name', name='uq_service_program_name')
        )
        op.create_index(op.f('ix_ServicePrograms_CompanyId'), 'ServicePrograms', ['CompanyId'], unique=False)
    if 'ServiceProgramTasks' not in existing:
        op.create_table('ServiceProgramTasks',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('ProgramId', sa.Integer(), nullable=False),
        sa.Column('ServiceType', sa.String(length=100), nullable=False),
        sa.Column('Title', sa.String(length=150), nullable=False),
        sa.Column('Description', sa.Text(), nullable=True),
        sa.Column('KmInterval', sa.Integer(), nullable=True),
        sa.Column('MonthInterval', sa.Integer(), nullable=True),
        sa.Column('WhicheverOccursFirst', sa.Boolean(), nullable=False),
        sa.Column('WarningKm', sa.Integer(), nullable=True),
        sa.Column('WarningDays', sa.Integer(), nullable=True),
        sa.Column('Priority', sa.String(length=50), nullable=False),
        sa.Column('AutoCreateWorkOrder', sa.Boolean(), nullable=False),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('DisplayOrder', sa.Integer(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.CheckConstraint('"KmInterval" IS NOT NULL OR "MonthInterval" IS NOT NULL', name='ck_program_task_interval'),
        sa.CheckConstraint('"KmInterval" IS NULL OR "KmInterval" > 0', name='ck_program_task_km'),
        sa.CheckConstraint('"MonthInterval" IS NULL OR "MonthInterval" > 0', name='ck_program_task_month'),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['ProgramId'], ['ServicePrograms.Id'], ),
        sa.PrimaryKeyConstraint('Id'),
        sa.UniqueConstraint('CompanyId', 'ProgramId', 'ServiceType', name='uq_program_task_type')
        )
        op.create_index(op.f('ix_ServiceProgramTasks_CompanyId'), 'ServiceProgramTasks', ['CompanyId'], unique=False)
        op.create_index(op.f('ix_ServiceProgramTasks_ProgramId'), 'ServiceProgramTasks', ['ProgramId'], unique=False)
    if 'ServiceProgramRules' not in existing:
        op.create_table('ServiceProgramRules',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('ProgramId', sa.Integer(), nullable=False),
        sa.Column('TargetType', sa.String(length=30), nullable=False),
        sa.Column('TargetValue', sa.String(length=255), nullable=False),
        sa.Column('Model', sa.String(length=150), nullable=True),
        sa.Column('EffectiveFrom', sa.Date(), nullable=False),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('AssignedBy', sa.Integer(), nullable=True),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['AssignedBy'], ['Users.Id'], ),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['ProgramId'], ['ServicePrograms.Id'], ),
        sa.PrimaryKeyConstraint('Id')
        )
        op.create_index(op.f('ix_ServiceProgramRules_CompanyId'), 'ServiceProgramRules', ['CompanyId'], unique=False)
        op.create_index(op.f('ix_ServiceProgramRules_ProgramId'), 'ServiceProgramRules', ['ProgramId'], unique=False)
    if 'VehicleServicePrograms' not in existing:
        op.create_table('VehicleServicePrograms',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('VehicleId', sa.Integer(), nullable=False),
        sa.Column('ProgramId', sa.Integer(), nullable=False),
        sa.Column('RuleId', sa.Integer(), nullable=False),
        sa.Column('AssignedAt', sa.DateTime(), nullable=False),
        sa.Column('AssignedBy', sa.Integer(), nullable=True),
        sa.Column('EffectiveFrom', sa.Date(), nullable=False),
        sa.Column('BaselineOdometerKm', sa.Integer(), nullable=True),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['AssignedBy'], ['Users.Id'], ),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['ProgramId'], ['ServicePrograms.Id'], ),
        sa.ForeignKeyConstraint(['RuleId'], ['ServiceProgramRules.Id'], ),
        sa.ForeignKeyConstraint(['VehicleId'], ['Vehicles.Id'], ),
        sa.PrimaryKeyConstraint('Id')
        )
        op.create_index(op.f('ix_VehicleServicePrograms_CompanyId'), 'VehicleServicePrograms', ['CompanyId'], unique=False)
        op.create_index(op.f('ix_VehicleServicePrograms_VehicleId'), 'VehicleServicePrograms', ['VehicleId'], unique=False)
        op.create_index('uq_vehicle_active_program', 'VehicleServicePrograms', ['CompanyId', 'VehicleId'], unique=True, sqlite_where=sa.text('"IsActive" = 1'), postgresql_where=sa.text('"IsActive" = true'))
    if 'ServiceProgramReminders' not in existing:
        op.create_table('ServiceProgramReminders',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('VehicleId', sa.Integer(), nullable=False),
        sa.Column('AssignmentId', sa.Integer(), nullable=False),
        sa.Column('TaskId', sa.Integer(), nullable=False),
        sa.Column('BasisServiceId', sa.Integer(), nullable=True),
        sa.Column('DueDate', sa.Date(), nullable=True),
        sa.Column('DueOdometerKm', sa.Integer(), nullable=True),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('Resolution', sa.String(length=30), nullable=True),
        sa.Column('ResolvedAt', sa.DateTime(), nullable=True),
        sa.Column('WorkOrderId', sa.Integer(), nullable=True),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['AssignmentId'], ['VehicleServicePrograms.Id'], ),
        sa.ForeignKeyConstraint(['BasisServiceId'], ['VehicleServices.Id'], ),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['TaskId'], ['ServiceProgramTasks.Id'], ),
        sa.ForeignKeyConstraint(['VehicleId'], ['Vehicles.Id'], ),
        sa.ForeignKeyConstraint(['WorkOrderId'], ['WorkOrders.Id'], ),
        sa.PrimaryKeyConstraint('Id'),
        sa.UniqueConstraint('WorkOrderId', name='uq_program_reminder_work_order')
        )
        op.create_index(op.f('ix_ServiceProgramReminders_CompanyId'), 'ServiceProgramReminders', ['CompanyId'], unique=False)
        op.create_index(op.f('ix_ServiceProgramReminders_VehicleId'), 'ServiceProgramReminders', ['VehicleId'], unique=False)
        op.create_index('uq_program_active_reminder', 'ServiceProgramReminders', ['CompanyId', 'AssignmentId', 'TaskId'], unique=True, sqlite_where=sa.text('"IsActive" = 1'), postgresql_where=sa.text('"IsActive" = true'))

def downgrade():
    op.drop_table("ServiceProgramReminders")
    op.drop_table("VehicleServicePrograms")
    op.drop_table("ServiceProgramRules")
    op.drop_table("ServiceProgramTasks")
    op.drop_table("ServicePrograms")
