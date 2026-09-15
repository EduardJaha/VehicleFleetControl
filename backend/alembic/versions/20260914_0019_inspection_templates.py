"""Inspection templates and nullable historical snapshot columns; no result backfill."""
from alembic import op
import sqlalchemy as sa

revision = "20260914_0019"
down_revision = "20260914_0018"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if 'InspectionTemplates' not in existing:
        op.create_table('InspectionTemplates',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('Code', sa.String(length=80), nullable=False),
        sa.Column('Name', sa.String(length=150), nullable=False),
        sa.Column('Description', sa.Text(), nullable=True),
        sa.Column('InspectionType', sa.String(length=50), nullable=False),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('Archived', sa.Boolean(), nullable=False),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.Column('UpdatedAt', sa.DateTime(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('Id'),
        sa.UniqueConstraint('CompanyId', 'Code', name='uq_inspection_template_code')
        )
    if 'InspectionTemplates' not in existing:
        op.create_index(op.f('ix_InspectionTemplates_CompanyId'), 'InspectionTemplates', ['CompanyId'], unique=False)
    if 'InspectionSchedules' not in existing:
        op.create_table('InspectionSchedules',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('TemplateId', sa.Integer(), nullable=False),
        sa.Column('Frequency', sa.String(length=30), nullable=False),
        sa.Column('StartDate', sa.Date(), nullable=False),
        sa.Column('IntervalDays', sa.Integer(), nullable=True),
        sa.Column('IntervalKm', sa.Integer(), nullable=True),
        sa.Column('BaselineOdometerKm', sa.Integer(), nullable=True),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.Column('UpdatedAt', sa.DateTime(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.CheckConstraint('"IntervalDays" IS NULL OR "IntervalDays" > 0', name='ck_inspection_schedule_days'),
        sa.CheckConstraint('"IntervalKm" IS NULL OR "IntervalKm" > 0', name='ck_inspection_schedule_km'),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['TemplateId'], ['InspectionTemplates.Id'], ),
        sa.PrimaryKeyConstraint('Id')
        )
    if 'InspectionSchedules' not in existing:
        op.create_index(op.f('ix_InspectionSchedules_CompanyId'), 'InspectionSchedules', ['CompanyId'], unique=False)
    if 'InspectionSchedules' not in existing:
        op.create_index(op.f('ix_InspectionSchedules_TemplateId'), 'InspectionSchedules', ['TemplateId'], unique=False)
    if 'InspectionTemplateAssignments' not in existing:
        op.create_table('InspectionTemplateAssignments',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('TemplateId', sa.Integer(), nullable=False),
        sa.Column('TargetType', sa.String(length=30), nullable=False),
        sa.Column('TargetValue', sa.String(length=255), nullable=False),
        sa.Column('Model', sa.String(length=150), nullable=True),
        sa.Column('Priority', sa.Integer(), nullable=False),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['TemplateId'], ['InspectionTemplates.Id'], ),
        sa.PrimaryKeyConstraint('Id')
        )
    if 'InspectionTemplateAssignments' not in existing:
        op.create_index(op.f('ix_InspectionTemplateAssignments_CompanyId'), 'InspectionTemplateAssignments', ['CompanyId'], unique=False)
    if 'InspectionTemplateAssignments' not in existing:
        op.create_index(op.f('ix_InspectionTemplateAssignments_TemplateId'), 'InspectionTemplateAssignments', ['TemplateId'], unique=False)
    if 'InspectionTemplateItems' not in existing:
        op.create_table('InspectionTemplateItems',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('TemplateId', sa.Integer(), nullable=False),
        sa.Column('Code', sa.String(length=80), nullable=False),
        sa.Column('Name', sa.String(length=150), nullable=False),
        sa.Column('Description', sa.Text(), nullable=True),
        sa.Column('Category', sa.String(length=50), nullable=False),
        sa.Column('DisplayOrder', sa.Integer(), nullable=False),
        sa.Column('Required', sa.Boolean(), nullable=False),
        sa.Column('Critical', sa.Boolean(), nullable=False),
        sa.Column('PhotoRequiredOnFailure', sa.Boolean(), nullable=False),
        sa.Column('CommentRequiredOnFailure', sa.Boolean(), nullable=False),
        sa.Column('CreateWorkOrderOnFailure', sa.Boolean(), nullable=False),
        sa.Column('MarkVehicleUnavailableOnFailure', sa.Boolean(), nullable=False),
        sa.Column('GenerateNotificationOnFailure', sa.Boolean(), nullable=False),
        sa.Column('IsActive', sa.Boolean(), nullable=False),
        sa.Column('CompanyId', sa.Integer(), server_default='1', nullable=False),
        sa.ForeignKeyConstraint(['CompanyId'], ['Companies.Id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['TemplateId'], ['InspectionTemplates.Id'], ),
        sa.PrimaryKeyConstraint('Id'),
        sa.UniqueConstraint('CompanyId', 'TemplateId', 'Code', name='uq_inspection_template_item_code')
        )
    if 'InspectionTemplateItems' not in existing:
        op.create_index(op.f('ix_InspectionTemplateItems_CompanyId'), 'InspectionTemplateItems', ['CompanyId'], unique=False)
    if 'InspectionTemplateItems' not in existing:
        op.create_index(op.f('ix_InspectionTemplateItems_TemplateId'), 'InspectionTemplateItems', ['TemplateId'], unique=False)
    if 'InspectionItems' in existing and 'TemplateItemId' not in {c["name"] for c in sa.inspect(bind).get_columns('InspectionItems')}:
        op.add_column('InspectionItems', sa.Column('TemplateItemId', sa.Integer(), nullable=True))
    if 'InspectionItems' in existing and 'ItemSnapshot' not in {c["name"] for c in sa.inspect(bind).get_columns('InspectionItems')}:
        op.add_column('InspectionItems', sa.Column('ItemSnapshot', sa.JSON(), nullable=True))
    if 'InspectionItems' in existing and 'PhotoAttachmentIds' not in {c["name"] for c in sa.inspect(bind).get_columns('InspectionItems')}:
        op.add_column('InspectionItems', sa.Column('PhotoAttachmentIds', sa.JSON(), nullable=True))
    if 'Inspections' in existing and 'TemplateId' not in {c["name"] for c in sa.inspect(bind).get_columns('Inspections')}:
        op.add_column('Inspections', sa.Column('TemplateId', sa.Integer(), nullable=True))
    if 'Inspections' in existing and 'TemplateSnapshot' not in {c["name"] for c in sa.inspect(bind).get_columns('Inspections')}:
        op.add_column('Inspections', sa.Column('TemplateSnapshot', sa.JSON(), nullable=True))
    if 'Inspections' in existing and 'ScheduleId' not in {c["name"] for c in sa.inspect(bind).get_columns('Inspections')}:
        op.add_column('Inspections', sa.Column('ScheduleId', sa.Integer(), nullable=True))
    if 'Inspections' in existing and 'OccurrenceKey' not in {c["name"] for c in sa.inspect(bind).get_columns('Inspections')}:
        op.add_column('Inspections', sa.Column('OccurrenceKey', sa.String(length=200), nullable=True))
    if 'Inspections' in existing and 'CompletedAt' not in {c["name"] for c in sa.inspect(bind).get_columns('Inspections')}:
        op.add_column('Inspections', sa.Column('CompletedAt', sa.DateTime(), nullable=True))
    if 'Inspections' in existing and 'OdometerKm' not in {c["name"] for c in sa.inspect(bind).get_columns('Inspections')}:
        op.add_column('Inspections', sa.Column('OdometerKm', sa.Integer(), nullable=True))
    if 'WorkOrders' in existing and 'InspectionItemId' not in {c["name"] for c in sa.inspect(bind).get_columns('WorkOrders')}:
        op.add_column('WorkOrders', sa.Column('InspectionItemId', sa.Integer(), nullable=True))
    if 'Inspections' in existing and 'CreatedByUserId' not in {c["name"] for c in sa.inspect(bind).get_columns('Inspections')}:
        op.add_column('Inspections', sa.Column('CreatedByUserId', sa.Integer(), nullable=True))
    if {'Inspections', 'Users'} <= existing and not any(c.get('constrained_columns') == ['CreatedByUserId'] for c in sa.inspect(bind).get_foreign_keys('Inspections')):
        with op.batch_alter_table('Inspections') as batch:
            batch.create_foreign_key('fk_inspections_createdbyuserid', 'Users', ['CreatedByUserId'], ['Id'], ondelete='SET NULL')
    if 'Inspections' in existing and not any(c.get('name') == 'uq_inspection_occurrence' for c in sa.inspect(bind).get_unique_constraints('Inspections')):
        with op.batch_alter_table('Inspections') as batch:
            batch.create_unique_constraint('uq_inspection_occurrence', ['CompanyId', 'OccurrenceKey'])
    if 'Inspections' in existing and not any(c.get('constrained_columns') == ['ScheduleId'] for c in sa.inspect(bind).get_foreign_keys('Inspections')):
        with op.batch_alter_table('Inspections') as batch:
            batch.create_foreign_key('fk_inspections_scheduleid', 'InspectionSchedules', ['ScheduleId'], ['Id'])
    if 'Inspections' in existing and not any(c.get('constrained_columns') == ['TemplateId'] for c in sa.inspect(bind).get_foreign_keys('Inspections')):
        with op.batch_alter_table('Inspections') as batch:
            batch.create_foreign_key('fk_inspections_templateid', 'InspectionTemplates', ['TemplateId'], ['Id'])
    if 'WorkOrders' in existing and not any(c.get('column_names') == ['InspectionItemId'] for c in sa.inspect(bind).get_unique_constraints('WorkOrders')):
        with op.batch_alter_table('WorkOrders') as batch:
            batch.create_unique_constraint('uq_work_order_inspection_item', ['InspectionItemId'])
    if {'WorkOrders', 'InspectionItems'} <= existing and not any(c.get('constrained_columns') == ['InspectionItemId'] for c in sa.inspect(bind).get_foreign_keys('WorkOrders')):
        with op.batch_alter_table('WorkOrders') as batch:
            batch.create_foreign_key('fk_workorders_inspectionitemid', 'InspectionItems', ['InspectionItemId'], ['Id'], ondelete='RESTRICT')

    # Add only this permission to existing system roles; preserve custom grants.
    if {"Permissions", "Roles", "RolePermissions"} <= existing:
        code = "inspection_templates.manage"
        permission_id = bind.execute(sa.text('SELECT "Id" FROM "Permissions" WHERE "Code" = :code'), {"code": code}).scalar()
        if permission_id is None:
            bind.execute(sa.text('INSERT INTO "Permissions" ("Code", "Name", "Module", "CreatedAt") VALUES (:code, :code, :module, CURRENT_TIMESTAMP)'), {"code": code, "module": "Inspections"})
            permission_id = bind.execute(sa.text('SELECT "Id" FROM "Permissions" WHERE "Code" = :code'), {"code": code}).scalar_one()
        roles = bind.execute(sa.text('SELECT "Id" FROM "Roles" WHERE "Code" IN (:admin, :manager) AND "IsSystem" = :system'), {"admin": "admin", "manager": "fleet_manager", "system": True}).scalars()
        for role_id in roles:
            params = {"role": role_id, "permission": permission_id}
            if bind.execute(sa.text('SELECT "Id" FROM "RolePermissions" WHERE "RoleId" = :role AND "PermissionId" = :permission'), params).first() is None:
                bind.execute(sa.text('INSERT INTO "RolePermissions" ("RoleId", "PermissionId") VALUES (:role, :permission)'), params)


def downgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    columns = {
        "WorkOrders": ["InspectionItemId"],
        "InspectionItems": ["PhotoAttachmentIds", "ItemSnapshot", "TemplateItemId"],
        "Inspections": ["CreatedByUserId", "OdometerKm", "CompletedAt", "OccurrenceKey", "ScheduleId", "TemplateSnapshot", "TemplateId"],
    }
    constraints = {"fk_inspections_createdbyuserid", "uq_work_order_inspection_item", "fk_workorders_inspectionitemid", "uq_inspection_occurrence", "fk_inspections_templateid", "fk_inspections_scheduleid"}
    for table, names in columns.items():
        if table not in existing:
            continue
        inspector = sa.inspect(bind)
        with op.batch_alter_table(table) as batch:
            for constraint in inspector.get_unique_constraints(table):
                if constraint["name"] in constraints:
                    batch.drop_constraint(constraint["name"], type_="unique")
            for constraint in inspector.get_foreign_keys(table):
                if constraint["name"] in constraints:
                    batch.drop_constraint(constraint["name"], type_="foreignkey")
            for name in names:
                if name in {c["name"] for c in inspector.get_columns(table)}:
                    batch.drop_column(name)
    for table in ["InspectionSchedules", "InspectionTemplateAssignments", "InspectionTemplateItems", "InspectionTemplates"]:
        if table in existing:
            op.drop_table(table)
    if {"Permissions", "RolePermissions"} <= existing:
        bind.execute(sa.text('DELETE FROM "RolePermissions" WHERE "PermissionId" IN (SELECT "Id" FROM "Permissions" WHERE "Code" = :code)'), {"code": "inspection_templates.manage"})
        bind.execute(sa.text('DELETE FROM "Permissions" WHERE "Code" = :code'), {"code": "inspection_templates.manage"})
