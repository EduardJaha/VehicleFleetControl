"""List historical Electric Fuel records whose migrated kWh unit needs review."""

from app.db.session import SessionLocal
from app.models import Vehicle, VehicleFuel


def review_rows(db):
    return (
        db.query(VehicleFuel, Vehicle)
        .join(Vehicle, Vehicle.id == VehicleFuel.vehicle_id)
        .filter(
            VehicleFuel.unit == "KWH",
            VehicleFuel.unit_review_required.is_(True),
        )
        .order_by(VehicleFuel.id)
        .all()
    )


def main() -> None:
    with SessionLocal() as db:
        rows = review_rows(db)
        if not rows:
            print("No migrated Electric Fuel records require unit review.")
            return
        print("Migrated Electric Fuel records requiring kWh review:")
        for fuel, vehicle in rows:
            print(
                f"- Fuel Id={fuel.id}, Vehicle Id={vehicle.id}, "
                f"Licence Plate={vehicle.license_plate}, "
                f"Old Value={fuel.liters}, Quantity={fuel.quantity}, Unit={fuel.unit}"
            )
        print(f"Total requiring review: {len(rows)}")


if __name__ == "__main__":
    main()
