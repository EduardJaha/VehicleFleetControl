"""Report unresolved or duplicate Vehicle registration data.

Run from ``backend``:
    python -m app.scripts.audit_vehicle_registration
"""

from collections import defaultdict

from sqlalchemy import inspect, text

from app.db.session import engine
from app.services.license_plates import detect_registration_country, normalize_license_plate


def main() -> int:
    if "Vehicles" not in inspect(engine).get_table_names():
        print("Vehicles table does not exist.")
        return 1
    unresolved: list[tuple[int, str]] = []
    grouped: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    with engine.connect() as connection:
        rows = connection.execute(text(
            'SELECT "Id", "LicensePlate" FROM "Vehicles" ORDER BY "Id"'
        )).all()
    for vehicle_id, plate in rows:
        country = detect_registration_country(plate or "")
        if country is None:
            unresolved.append((vehicle_id, plate))
            continue
        grouped[(country.value, normalize_license_plate(country, plate))].append((vehicle_id, plate))

    duplicates = {key: values for key, values in grouped.items() if len(values) > 1}
    print(f"Vehicles inspected: {len(rows)}")
    print(f"Unresolved plates: {len(unresolved)}")
    for vehicle_id, plate in unresolved:
        print(f"  Vehicle Id={vehicle_id}: {plate!r}")
    print(f"Normalized duplicate groups: {len(duplicates)}")
    for (country, normalized), values in duplicates.items():
        print(f"  {country}/{normalized}: {values}")
    return 1 if unresolved or duplicates else 0


if __name__ == "__main__":
    raise SystemExit(main())
