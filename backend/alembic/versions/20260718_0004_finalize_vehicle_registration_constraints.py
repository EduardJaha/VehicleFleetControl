"""Finalize Vehicle registration constraints after remediation.

Revision ID: 20260718_0004
Revises: 20260718_0003
Create Date: 2026-07-18
"""

from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.services.license_plates import (
    detect_registration_country,
    normalize_license_plate,
    validate_license_plate,
)

revision: str = "20260718_0004"
down_revision: Union[str, None] = "20260718_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMPOSITE_UNIQUE = "uq_vehicles_registration_country_license_plate_normalized"
LEGACY_UNIQUE = "uq_vehicles_license_plate"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "Vehicles" not in inspector.get_table_names():
        return

    rows = bind.execute(sa.text(
        'SELECT "Id", "LicensePlate" FROM "Vehicles" ORDER BY "Id"'
    )).all()
    unresolved: list[str] = []
    detected: list[tuple[int, str, str, str, str]] = []
    grouped: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)

    for vehicle_id, original_plate in rows:
        country = detect_registration_country(original_plate or "")
        if country is None:
            unresolved.append(f"Vehicle Id={vehicle_id}, LicensePlate={original_plate!r}")
            continue
        normalized = normalize_license_plate(country, original_plate)
        formatted = validate_license_plate(country, original_plate)
        detected.append((vehicle_id, original_plate, country.value, normalized, formatted))
        grouped[(country.value, normalized)].append((vehicle_id, original_plate))

    duplicate_keys = {key for key, matches in grouped.items() if len(matches) > 1}
    duplicates = [
        f"{country}/{normalized}: "
        + ", ".join(f"Id={vehicle_id} ({plate!r})" for vehicle_id, plate in matches)
        for (country, normalized), matches in grouped.items()
        if (country, normalized) in duplicate_keys
    ]

    for vehicle_id, original_plate, country, normalized, formatted in detected:
        display_plate = original_plate if (country, normalized) in duplicate_keys else formatted
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

    if unresolved or duplicates:
        details = "\n".join(f"- {item}" for item in [*unresolved, *duplicates])
        raise RuntimeError(
            "Vehicle registration migration requires remediation:\n"
            f"{details}\n"
            "Correct the listed Vehicles' LicensePlate values so each is a supported, "
            "unique Albania or Kosovo plate. Run "
            "'python -m app.scripts.audit_vehicle_registration', then rerun "
            "'alembic upgrade head'. Original plate values were preserved."
        )

    unique_constraints = {
        constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("Vehicles")
    }
    columns = {
        column["name"]: column for column in sa.inspect(bind).get_columns("Vehicles")
    }
    with op.batch_alter_table("Vehicles") as batch:
        if LEGACY_UNIQUE in unique_constraints:
            batch.drop_constraint(LEGACY_UNIQUE, type_="unique")
        if COMPOSITE_UNIQUE not in unique_constraints:
            batch.create_unique_constraint(
                COMPOSITE_UNIQUE,
                ["RegistrationCountry", "LicensePlateNormalized"],
            )
        if columns["RegistrationCountry"]["nullable"]:
            batch.alter_column(
                "RegistrationCountry",
                existing_type=sa.String(2),
                nullable=False,
            )
        if columns["LicensePlateNormalized"]["nullable"]:
            batch.alter_column(
                "LicensePlateNormalized",
                existing_type=sa.String(7),
                nullable=False,
            )


def downgrade() -> None:
    # Revision 0003 owns the columns and indexes. Downgrading this finalizer
    # only relaxes nullability so unresolved historical records remain safe.
    bind = op.get_bind()
    if "Vehicles" not in sa.inspect(bind).get_table_names():
        return
    with op.batch_alter_table("Vehicles") as batch:
        batch.alter_column(
            "RegistrationCountry",
            existing_type=sa.String(2),
            nullable=True,
        )
        batch.alter_column(
            "LicensePlateNormalized",
            existing_type=sa.String(7),
            nullable=True,
        )
