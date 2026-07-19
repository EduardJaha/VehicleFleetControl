"""Validate legacy text-backed numeric values before the Alembic conversion."""

from decimal import Decimal, InvalidOperation

from sqlalchemy import inspect, text

from app.db.session import engine

FIELDS = {
    "WorkOrders": ("LaborCost", "PartsCost", "TotalCost"),
    "VehicleServices": ("Cost", "LaborCost", "PartsCost"),
    "VehicleFuels": ("Quantity", "UnitCost", "TotalCost", "Liters", "CostPerLiter"),
}


def invalid_values() -> list[str]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    invalid: list[str] = []
    with engine.connect() as connection:
        for table, fields in FIELDS.items():
            if table not in tables:
                continue
            columns = {item["name"] for item in inspector.get_columns(table)}
            for field in fields:
                if field not in columns:
                    continue
                rows = connection.execute(
                    text(f'SELECT "Id", "{field}" FROM "{table}" WHERE "{field}" IS NOT NULL')
                ).all()
                for row_id, raw in rows:
                    if str(raw).strip() == "":
                        continue
                    try:
                        value = Decimal(str(raw))
                    except (InvalidOperation, ValueError):
                        invalid.append(f"{table}.Id={row_id} {field}={raw!r}")
                        continue
                    if not value.is_finite():
                        invalid.append(f"{table}.Id={row_id} {field}={raw!r}")
    return invalid


def main() -> None:
    invalid = invalid_values()
    if invalid:
        print("Invalid numeric values found; migration was not run:")
        for item in invalid:
            print(f"- {item}")
        raise SystemExit(1)
    print("Numeric migration validation passed.")


if __name__ == "__main__":
    main()
