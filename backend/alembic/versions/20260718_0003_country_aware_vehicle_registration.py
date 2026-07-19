"""Add country-aware Vehicle registration plates.

Revision ID: 20260718_0003
Revises: 20260718_0002
Create Date: 2026-07-18
"""

from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.session import Base
from app.services.license_plates import (
    detect_registration_country,
    normalize_license_plate,
    validate_license_plate,
)

revision: str = "20260718_0003"
down_revision: Union[str, None] = "20260718_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COUNTRY_INDEX = "ix_vehicles_registration_country"
NORMALIZED_INDEX = "ix_vehicles_license_plate_normalized"
COMPOSITE_INDEX = "ix_vehicles_registration_country_license_plate_normalized"
COMPOSITE_UNIQUE = "uq_vehicles_registration_country_license_plate_normalized"
LEGACY_UNIQUE = "uq_vehicles_license_plate"


def _log_problem(title: str, rows: list[str]) -> None:
    print(f"\n[vehicle-registration migration] {title}")
    for row in rows:
        print(f"  - {row}")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "Vehicles" not in inspector.get_table_names():
        Base.metadata.create_all(bind=bind)
        return

    columns = {column["name"] for column in inspector.get_columns("Vehicles")}
    with op.batch_alter_table("Vehicles") as batch:
        if "RegistrationCountry" not in columns:
            batch.add_column(sa.Column("RegistrationCountry", sa.String(2), nullable=True))
        if "LicensePlateNormalized" not in columns:
            batch.add_column(sa.Column("LicensePlateNormalized", sa.String(7), nullable=True))

    rows = bind.execute(sa.text(
        'SELECT "Id", "LicensePlate" FROM "Vehicles" ORDER BY "Id"'
    )).all()
    unresolved: list[str] = []
    normalized_rows: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    detected: list[tuple[int, str, str, str, str]] = []

    for vehicle_id, original_plate in rows:
        country = detect_registration_country(original_plate or "")
        if country is None:
            unresolved.append(f"Vehicle Id={vehicle_id}, LicensePlate={original_plate!r}")
            continue
        normalized = normalize_license_plate(country, original_plate)
        formatted = validate_license_plate(country, original_plate)
        normalized_rows[(country.value, normalized)].append((vehicle_id, original_plate))
        detected.append((vehicle_id, original_plate, country.value, normalized, formatted))

    duplicate_keys = {
        key for key, matches in normalized_rows.items() if len(matches) > 1
    }
    duplicates = [
        f"{country}/{normalized}: "
        + ", ".join(f"Id={vehicle_id} ({plate!r})" for vehicle_id, plate in matches)
        for (country, normalized), matches in normalized_rows.items()
        if (country, normalized) in duplicate_keys
    ]

    for vehicle_id, original_plate, country, normalized, formatted in detected:
        # Keep conflicting legacy display strings unchanged so the old unique
        # constraint cannot abort before the duplicate report is emitted.
        display_plate = (
            original_plate
            if (country, normalized) in duplicate_keys
            else formatted
        )
        bind.execute(sa.text(
            'UPDATE "Vehicles" SET "RegistrationCountry" = :country, '
            '"LicensePlateNormalized" = :normalized, "LicensePlate" = :formatted '
            'WHERE "Id" = :vehicle_id'
        ), {
            "country": country,
            "normalized": normalized,
            "formatted": display_plate,
            "vehicle_id": vehicle_id,
        })
        if "AuditLogs" in inspector.get_table_names():
            bind.execute(sa.text(
                'INSERT INTO "AuditLogs" '
                '("Username", "Action", "EntityType", "EntityId", "NewValues", "Description", "CreatedAt") '
                "VALUES ('System', 'Vehicle registration country backfilled', 'Vehicle', :vehicle_id, "
                ":new_values, :description, CURRENT_TIMESTAMP)"
            ), {
                "vehicle_id": vehicle_id,
                "new_values": f'{{"registration_country":"{country}","license_plate":"{display_plate}"}}',
                "description": f"Registration country backfilled for Vehicle {vehicle_id}.",
            })

    if unresolved:
        _log_problem(
            "Unidentified plates were preserved. Run "
            "`python -m app.scripts.audit_vehicle_registration` after correcting them:",
            unresolved,
        )
    if duplicates:
        _log_problem(
            "Normalized duplicate plates must be resolved before database uniqueness can be enabled:",
            duplicates,
        )

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("Vehicles")}
    if COUNTRY_INDEX not in indexes:
        op.create_index(COUNTRY_INDEX, "Vehicles", ["RegistrationCountry"])
    if NORMALIZED_INDEX not in indexes:
        op.create_index(NORMALIZED_INDEX, "Vehicles", ["LicensePlateNormalized"])
    if COMPOSITE_INDEX not in indexes:
        op.create_index(
            COMPOSITE_INDEX,
            "Vehicles",
            ["RegistrationCountry", "LicensePlateNormalized"],
        )

    if unresolved or duplicates:
        return

    unique_constraints = {
        constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("Vehicles")
    }
    with op.batch_alter_table("Vehicles") as batch:
        if LEGACY_UNIQUE in unique_constraints:
            batch.drop_constraint(LEGACY_UNIQUE, type_="unique")
        if COMPOSITE_UNIQUE not in unique_constraints:
            batch.create_unique_constraint(
                COMPOSITE_UNIQUE,
                ["RegistrationCountry", "LicensePlateNormalized"],
            )
        batch.alter_column(
            "RegistrationCountry",
            existing_type=sa.String(2),
            nullable=False,
        )
        batch.alter_column(
            "LicensePlateNormalized",
            existing_type=sa.String(7),
            nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "Vehicles" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("Vehicles")}
    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("Vehicles")
    }
    for name in (COMPOSITE_INDEX, NORMALIZED_INDEX, COUNTRY_INDEX):
        if name in indexes:
            op.drop_index(name, table_name="Vehicles")
    with op.batch_alter_table("Vehicles") as batch:
        if COMPOSITE_UNIQUE in unique_constraints:
            batch.drop_constraint(COMPOSITE_UNIQUE, type_="unique")
        if LEGACY_UNIQUE not in unique_constraints:
            batch.create_unique_constraint(LEGACY_UNIQUE, ["LicensePlate"])
        batch.drop_column("LicensePlateNormalized")
        batch.drop_column("RegistrationCountry")
