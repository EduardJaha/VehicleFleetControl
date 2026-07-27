"""add rule-driven Document Compliance and immutable version history

Revision ID: 20260727_0010
Revises: 20260724_0009
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa

revision = "20260727_0010"
down_revision = "20260724_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "Vehicles" in tables:
        vehicle_columns = {column["name"] for column in inspector.get_columns("Vehicles")}
        if "VehicleCategory" not in vehicle_columns:
            op.add_column("Vehicles", sa.Column("VehicleCategory", sa.String(length=100), nullable=True))
            op.create_index("ix_vehicles_vehicle_category", "Vehicles", ["VehicleCategory"])

    # Some supported data-repair tests deliberately migrate a narrow legacy
    # schema containing only Fuel-related tables. A compliance migration must
    # leave that database usable instead of assuming unrelated modules exist.
    compliance_dependencies = {"VehiclePapers", "Drivers", "Attachments", "Users"}
    if not compliance_dependencies.issubset(tables):
        return

    op.create_table(
        "DocumentRequirements",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("DocumentType", sa.String(length=150), nullable=False),
        sa.Column("AppliesToVehicleCategory", sa.String(length=100), nullable=True),
        sa.Column("AppliesToCountry", sa.String(length=2), nullable=True),
        sa.Column("AppliesToDriver", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("Required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ValidityMonths", sa.Integer(), nullable=True),
        sa.Column("WarningDays", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("IsActive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint('"WarningDays" >= 0', name="ck_document_requirements_warning_days"),
        sa.CheckConstraint(
            '"ValidityMonths" IS NULL OR "ValidityMonths" > 0',
            name="ck_document_requirements_validity_months",
        ),
    )
    op.create_index(
        "ix_document_requirements_scope",
        "DocumentRequirements",
        ["AppliesToDriver", "AppliesToCountry", "AppliesToVehicleCategory"],
    )
    op.create_index("ix_document_requirements_active", "DocumentRequirements", ["IsActive"])

    with op.batch_alter_table("VehiclePapers") as batch:
        batch.alter_column("VehicleId", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("DriverId", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("RequirementId", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("DocumentNumber", sa.String(length=150), nullable=True))
        batch.add_column(sa.Column("IssuingAuthority", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("RenewalStatus", sa.String(length=50), nullable=False, server_default="None"))
        batch.add_column(sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
        batch.add_column(sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
        batch.create_foreign_key("fk_vehicle_papers_driver", "Drivers", ["DriverId"], ["Id"], ondelete="RESTRICT")
        batch.create_foreign_key(
            "fk_vehicle_papers_requirement",
            "DocumentRequirements",
            ["RequirementId"],
            ["Id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_vehicle_papers_exactly_one_owner",
            '("VehicleId" IS NOT NULL AND "DriverId" IS NULL) OR '
            '("VehicleId" IS NULL AND "DriverId" IS NOT NULL)',
        )
    op.create_index("ix_vehicle_papers_driver_id", "VehiclePapers", ["DriverId"])
    op.create_index("ix_vehicle_papers_requirement_id", "VehiclePapers", ["RequirementId"])

    op.create_table(
        "DocumentVersions",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("DocumentId", sa.Integer(), sa.ForeignKey("VehiclePapers.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("VersionNumber", sa.Integer(), nullable=False),
        sa.Column("AttachmentId", sa.Integer(), sa.ForeignKey("Attachments.Id", ondelete="RESTRICT"), nullable=True),
        sa.Column("FilePath", sa.String(length=500), nullable=False),
        sa.Column("DocumentNumber", sa.String(length=150), nullable=True),
        sa.Column("IssuingAuthority", sa.String(length=255), nullable=True),
        sa.Column("IssueDate", sa.DateTime(), nullable=False),
        sa.Column("ExpiryDate", sa.DateTime(), nullable=False),
        sa.Column("UploadedBy", sa.Integer(), sa.ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True),
        sa.Column("UploadedAt", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("VerifiedBy", sa.Integer(), sa.ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True),
        sa.Column("VerifiedAt", sa.DateTime(), nullable=True),
        sa.Column("RejectionReason", sa.Text(), nullable=True),
        sa.Column("RenewalStatus", sa.String(length=50), nullable=False, server_default="None"),
        sa.Column("IsCurrent", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("Archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ArchivedAt", sa.DateTime(), nullable=True),
        sa.Column("ArchivedBy", sa.Integer(), sa.ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("DocumentId", "VersionNumber", name="uq_document_versions_number"),
    )
    op.create_index("ix_document_versions_document_id", "DocumentVersions", ["DocumentId"])
    op.create_index("ix_document_versions_expiry_date", "DocumentVersions", ["ExpiryDate"])
    op.create_index(
        "uq_document_versions_current",
        "DocumentVersions",
        ["DocumentId"],
        unique=True,
        sqlite_where=sa.text('"IsCurrent" = 1'),
        postgresql_where=sa.text('"IsCurrent" = true'),
    )

    # Every historical VehiclePaper becomes version 1. The file and uploader
    # are linked when an authenticated Attachment already exists; legacy paths
    # remain untouched and downloadable through their existing secure route.
    op.execute(sa.text(
        """
        INSERT INTO "DocumentVersions"
            ("DocumentId", "VersionNumber", "AttachmentId", "FilePath",
             "IssueDate", "ExpiryDate", "UploadedBy", "UploadedAt",
             "RenewalStatus", "IsCurrent", "Archived")
        SELECT p."Id", 1,
               (SELECT MIN(a."Id") FROM "Attachments" a
                WHERE a."EntityType" = 'VehiclePaper' AND a."EntityId" = p."Id"),
               p."FilePath", p."IssueDate", p."ExpiryDate",
               (SELECT a."UploadedBy" FROM "Attachments" a
                WHERE a."EntityType" = 'VehiclePaper' AND a."EntityId" = p."Id"
                ORDER BY a."Id" LIMIT 1),
               COALESCE(p."CreatedAt", CURRENT_TIMESTAMP),
               'Approved', 1, p."Archived"
        FROM "VehiclePapers" p
        """
    ))

    requirements = [
        ("Registration", None, None, False, True, 12, 30),
        ("Insurance", None, None, False, True, 12, 30),
        ("Kosovo registration documentation", None, "XK", False, True, 12, 30),
        ("Albania registration documentation", None, "AL", False, True, 12, 30),
        ("Driving Licence", None, None, True, True, None, 30),
        ("Lease Agreement", "Leased", None, False, True, None, 30),
    ]
    for document_type, category, country, driver, required, validity, warning in requirements:
        bind.execute(
            sa.text(
                """
                INSERT INTO "DocumentRequirements"
                    ("DocumentType", "AppliesToVehicleCategory", "AppliesToCountry",
                     "AppliesToDriver", "Required", "ValidityMonths", "WarningDays",
                     "IsActive", "CreatedAt", "UpdatedAt")
                VALUES
                    (:document_type, :category, :country, :driver, :required,
                     :validity, :warning, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {
                "document_type": document_type,
                "category": category,
                "country": country,
                "driver": driver,
                "required": required,
                "validity": validity,
                "warning": warning,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "DocumentVersions" not in tables:
        if "Vehicles" in tables:
            columns = {column["name"] for column in inspector.get_columns("Vehicles")}
            if "VehicleCategory" in columns:
                indexes = {index["name"] for index in inspector.get_indexes("Vehicles")}
                if "ix_vehicles_vehicle_category" in indexes:
                    op.drop_index("ix_vehicles_vehicle_category", table_name="Vehicles")
                op.drop_column("Vehicles", "VehicleCategory")
        return

    op.drop_index("uq_document_versions_current", table_name="DocumentVersions")
    op.drop_index("ix_document_versions_expiry_date", table_name="DocumentVersions")
    op.drop_index("ix_document_versions_document_id", table_name="DocumentVersions")
    op.drop_table("DocumentVersions")
    op.drop_index("ix_vehicle_papers_requirement_id", table_name="VehiclePapers")
    op.drop_index("ix_vehicle_papers_driver_id", table_name="VehiclePapers")
    with op.batch_alter_table("VehiclePapers") as batch:
        batch.drop_constraint("ck_vehicle_papers_exactly_one_owner", type_="check")
        batch.drop_constraint("fk_vehicle_papers_requirement", type_="foreignkey")
        batch.drop_constraint("fk_vehicle_papers_driver", type_="foreignkey")
        batch.drop_column("UpdatedAt")
        batch.drop_column("CreatedAt")
        batch.drop_column("RenewalStatus")
        batch.drop_column("IssuingAuthority")
        batch.drop_column("DocumentNumber")
        batch.drop_column("RequirementId")
        batch.drop_column("DriverId")
        batch.alter_column("VehicleId", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ix_document_requirements_active", table_name="DocumentRequirements")
    op.drop_index("ix_document_requirements_scope", table_name="DocumentRequirements")
    op.drop_table("DocumentRequirements")
    op.drop_index("ix_vehicles_vehicle_category", table_name="Vehicles")
    op.drop_column("Vehicles", "VehicleCategory")
