import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.reports import build_excel, tco_report
from app.core.authorization import require_permission
from app.db.session import Base
from app.models import User, Vehicle, VehicleFuel, VehicleService, WorkOrder
from app.schemas import VehicleCreate
from app.services.tco import (
    allocate_maintenance, calculate_book_value, calculate_depreciation,
    detect_energy_anomalies, efficiency_metrics,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def vehicle(db: Session, *, fuel_type="Diesel", **values) -> Vehicle:
    row = Vehicle(
        brand="Test", model="Lifecycle", fuel_type=fuel_type, vehicle_location="Prishtina",
        license_plate=f"01-{100 + db.query(Vehicle).count():03d}-AA", registration_country="XK",
        license_plate_normalized=f"01{100 + db.query(Vehicle).count():03d}AA", status=0,
        ownership_type="Owned", depreciation_method="Straight Line", **values,
    )
    db.add(row); db.commit()
    return row


def fuel(db: Session, row: Vehicle, *, at: datetime, odometer: int, quantity: str, unit="L", unit_cost="2"):
    record = VehicleFuel(
        vehicle_id=row.id, refuel_date=at, quantity=Decimal(quantity), unit=unit,
        unit_cost=Decimal(unit_cost), total_cost=(Decimal(quantity) * Decimal(unit_cost)).quantize(Decimal(".01")),
        fuel_type="Electric" if unit == "KWH" else row.fuel_type, location="Test", station_name="Provider",
        odometer_km=odometer,
    )
    db.add(record); db.commit()
    return record


def test_decimal_allocation_and_straight_line_depreciation_are_exact(db: Session):
    allocation = allocate_maintenance(Decimal("100.10"), Decimal("30.03"), Decimal("40.04"))
    assert allocation == {
        "labor_cost": Decimal("30.03"), "parts_cost": Decimal("40.04"),
        "maintenance_cost": Decimal("30.03"),
    }
    row = vehicle(
        db, acquisition_date=date(2020, 1, 1), purchase_price=Decimal("10000.00"),
        residual_value=Decimal("2000.00"), expected_service_years=5,
    )
    assert calculate_depreciation(row, date(2020, 1, 1), date(2021, 1, 1)) == Decimal("1600.00")
    assert calculate_book_value(row, date(2025, 1, 1)) == Decimal("2000.00")
    row.sale_date = date(2022, 1, 1)
    row.sale_price = Decimal("6500.00")
    assert calculate_depreciation(row, date(2020, 1, 1), date(2023, 1, 1)) == Decimal("3500.00")


def test_tco_deduplicates_linked_work_order_and_service_costs(db: Session):
    row = vehicle(db)
    linked = WorkOrder(
        vehicle_id=row.id, title="Linked", status="Completed", priority="Medium", source="Manual",
        total_cost=Decimal("100"), labor_cost=Decimal("30"), parts_cost=Decimal("40"),
        created_at=datetime(2026, 1, 1), actual_completion_date=datetime(2026, 1, 2),
    )
    unlinked = WorkOrder(
        vehicle_id=row.id, title="Unlinked", status="Completed", priority="Medium", source="Manual",
        total_cost=Decimal("50"), labor_cost=Decimal("20"), parts_cost=Decimal("10"),
        created_at=datetime(2026, 2, 1), actual_completion_date=datetime(2026, 2, 2),
    )
    db.add_all([linked, unlinked]); db.flush()
    db.add(VehicleService(
        vehicle_id=row.id, work_order_id=linked.id, service_type="Maintenance", service_date=datetime(2026, 1, 2),
        status="Completed", source="Work Order", cost=Decimal("100"), labor_cost=Decimal("30"), parts_cost=Decimal("40"),
    )); db.commit()
    report = tco_report(db, from_date="01-01-2026", to_date="31-12-2026")
    result = report["rows"][0]
    assert result["labor_cost"] == 50.0
    assert result["parts_cost"] == 50.0
    assert result["maintenance_cost"] == 50.0
    assert result["total_cost"] == 150.0
    assert report["methodology"]["linked_cost_deduplication"].startswith("Linked Service")


def test_liquid_and_ev_efficiency_and_insufficient_history(db: Session):
    diesel = vehicle(db)
    first = fuel(db, diesel, at=datetime(2026, 1, 1), odometer=1000, quantity="10")
    second = fuel(db, diesel, at=datetime(2026, 1, 10), odometer=1100, quantity="8")
    metrics = efficiency_metrics([first, second])
    assert metrics["liters_per_100_km"] == Decimal("8.00")
    assert metrics["distance_between_refuels_km"] == Decimal("100.0")
    assert metrics["energy_cost_per_km"] == Decimal("0.1600")

    electric = vehicle(db, fuel_type="Electric")
    ev_first = fuel(db, electric, at=datetime(2026, 1, 1), odometer=2000, quantity="40", unit="KWH", unit_cost="0.2")
    ev_second = fuel(db, electric, at=datetime(2026, 1, 5), odometer=2200, quantity="50", unit="KWH", unit_cost="0.2")
    ev_metrics = efficiency_metrics([ev_first, ev_second])
    assert ev_metrics["kwh_per_100_km"] == Decimal("25.00")
    assert ev_metrics["charging_cost_by_provider"] == {"Provider": Decimal("18.00")}
    assert efficiency_metrics([first])["insufficient_odometer_history"] is True
    assert efficiency_metrics([first])["distance_km"] is None


def test_energy_anomaly_rules_cover_capacity_consumption_price_interval_and_odometer(db: Session):
    row = vehicle(db, fuel_tank_capacity_l=Decimal("50"))
    records = [
        fuel(db, row, at=datetime(2026, 1, 1, 8), odometer=1000, quantity="10", unit_cost="1"),
        fuel(db, row, at=datetime(2026, 1, 2, 8), odometer=1100, quantity="10", unit_cost="1"),
        fuel(db, row, at=datetime(2026, 1, 3, 8), odometer=1200, quantity="10", unit_cost="1"),
        fuel(db, row, at=datetime(2026, 1, 4, 8), odometer=1300, quantity="10", unit_cost="1"),
        fuel(db, row, at=datetime(2026, 1, 4, 9), odometer=1250, quantity="60", unit_cost="3"),
    ]
    anomaly_types = {item["type"] for item in detect_energy_anomalies(row, records)}
    assert {"lower_odometer", "quantity_above_tank_capacity", "large_unit_price_deviation", "repeated_fueling_short_interval"}.issubset(anomaly_types)

    ev = vehicle(db, fuel_type="Electric", battery_capacity_kwh=Decimal("60"))
    ev_records = [
        fuel(db, ev, at=datetime(2026, 2, 1), odometer=1000, quantity="10", unit="KWH"),
        fuel(db, ev, at=datetime(2026, 2, 2), odometer=1050, quantity="80", unit="KWH"),
    ]
    ev_types = {item["type"] for item in detect_energy_anomalies(ev, ev_records)}
    assert "unusually_high_ev_charging_quantity" in ev_types
    assert "unusually_high_consumption" in ev_types


def test_lifecycle_validation_permissions_export_and_translations(db: Session):
    with pytest.raises(ValueError):
        VehicleCreate(
            brand_id=1, model_id=1, fuel_type="Diesel", vehicle_location="P", registration_country="XK",
            license_plate="01-101-AA", lease_start="2026-12-01", lease_end="2026-01-01",
        )
    finance = User(email="finance@example.com", full_name="Finance", hashed_password="x", role="finance")
    viewer = User(email="viewer@example.com", full_name="Viewer", hashed_password="x", role="viewer")
    db.add_all([finance, viewer]); db.commit()
    assert require_permission("reports.view")(db, finance) is finance
    with pytest.raises(HTTPException) as denied:
        require_permission("reports.view")(db, viewer)
    assert denied.value.status_code == 403

    row = vehicle(db)
    data = tco_report(db)
    workbook = load_workbook(BytesIO(build_excel("tco", data).getvalue()))
    assert workbook["KPIs"]["A1"].value == "Vehicle Lifecycle and TCO"
    assert "Recommendation Reasons" in [cell.value for cell in workbook["Rows"][1]]

    root = Path(__file__).resolve().parents[2]
    for language in ("en", "sq"):
        modules = json.loads((root / "frontend" / "src" / "i18n" / "locales" / language / "modules.json").read_text())
        assert modules["reports"]["tco"]
        assert modules["tco"]["status"]["Replace Soon"]
        assert modules["vehicles"]["acquisitionDate"]
