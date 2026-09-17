"""consolidate country registration requirements into Registration

Revision ID: 20260727_0011
Revises: 20260727_0010
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa

revision = "20260727_0011"
down_revision = "20260727_0010"
branch_labels = None
depends_on = None

COUNTRY_TYPES = (
    "Kosovo registration documentation",
    "Albania registration documentation",
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"DocumentRequirements", "VehiclePapers"}.issubset(tables):
        return

    # Fresh bootstrap metadata already has tenant FKs before revision 0016.
    if "Companies" in tables:
        bind.execute(sa.text(
            'INSERT INTO "Companies" ("Id", "Name", "Slug", "IsActive", "CreatedAt", "UpdatedAt") '
            "SELECT 1, 'Default Company', 'default-company', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            'WHERE NOT EXISTS (SELECT 1 FROM "Companies" WHERE "Id" = 1)'
        ))

    canonical_id = bind.execute(sa.text(
        """
        SELECT "Id"
        FROM "DocumentRequirements"
        WHERE LOWER("DocumentType") = 'registration'
          AND "AppliesToDriver" = false
          AND "AppliesToCountry" IS NULL
          AND "AppliesToVehicleCategory" IS NULL
        ORDER BY "IsActive" DESC, "Id"
        LIMIT 1
        """
    )).scalar_one_or_none()
    if canonical_id is None:
        bind.execute(sa.text(
            """
            INSERT INTO "DocumentRequirements"
                ("DocumentType", "AppliesToDriver", "Required", "ValidityMonths",
                 "WarningDays", "IsActive", "CreatedAt", "UpdatedAt")
            VALUES
                ('Registration', false, true, 12, 30, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ))
        canonical_id = bind.execute(sa.text(
            """
            SELECT "Id"
            FROM "DocumentRequirements"
            WHERE LOWER("DocumentType") = 'registration'
              AND "AppliesToDriver" = false
              AND "AppliesToCountry" IS NULL
              AND "AppliesToVehicleCategory" IS NULL
            ORDER BY "Id"
            LIMIT 1
            """
        )).scalar_one()

    # Relink rather than delete: existing Document IDs, files, versions,
    # uploader details, verification history, and dates remain unchanged.
    bind.execute(
        sa.text(
            """
            UPDATE "VehiclePapers"
            SET "RequirementId" = :canonical_id,
                "DocumentType" = 'Registration',
                "UpdatedAt" = CURRENT_TIMESTAMP
            WHERE "RequirementId" IN (
                SELECT "Id"
                FROM "DocumentRequirements"
                WHERE "DocumentType" IN (
                    'Kosovo registration documentation',
                    'Albania registration documentation'
                )
            )
               OR "DocumentType" IN (
                    'Kosovo registration documentation',
                    'Albania registration documentation'
               )
            """
        ),
        {"canonical_id": canonical_id},
    )
    bind.execute(sa.text(
        """
        UPDATE "DocumentRequirements"
        SET "IsActive" = false,
            "UpdatedAt" = CURRENT_TIMESTAMP
        WHERE "DocumentType" IN (
            'Kosovo registration documentation',
            'Albania registration documentation'
        )
        """
    ))
    bind.execute(
        sa.text(
            """
            UPDATE "DocumentRequirements"
            SET "IsActive" = true,
                "UpdatedAt" = CURRENT_TIMESTAMP
            WHERE "Id" = :canonical_id
            """
        ),
        {"canonical_id": canonical_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "DocumentRequirements" not in sa.inspect(bind).get_table_names():
        return
    bind.execute(sa.text(
        """
        UPDATE "DocumentRequirements"
        SET "IsActive" = true,
            "UpdatedAt" = CURRENT_TIMESTAMP
        WHERE "DocumentType" IN (
            'Kosovo registration documentation',
            'Albania registration documentation'
        )
        """
    ))
