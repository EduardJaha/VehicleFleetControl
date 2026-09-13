from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.authorization import seed_authorization_defaults
from app.db.session import Base, TenantSession, set_tenant_context
from app.models import (
    AccidentClaim,
    Company,
    Department,
    Driver,
    Inspection,
    Location,
    Role,
    User,
    UserRole,
    Vehicle,
    VehicleAccident,
    VehicleAssignment,
    VehicleFuel,
    VehicleOperatingCost,
    VehicleReservation,
    VehicleService,
    WorkOrder,
)
from app.services.dashboard import build_dashboard_overview, resolve_dashboard_period


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


def user(db: Session, role="admin", email="admin@example.com") -> User:
    row = User(email=email, full_name=email.split("@")[0], hashed_password="unused", role=role)
    db.add(row)
    db.commit()
    return row


def vehicle(db: Session, plate: str, *, status=0, location=None, **values) -> Vehicle:
    row = Vehicle(
        brand="Test", model="Fleet", fuel_type="Diesel", vehicle_location=location.name if location else "Prishtina",
        location_id=location.id if location else None, license_plate=plate, registration_country="XK",
        license_plate_normalized=plate.replace("-", ""), status=status, **values,
    )
    db.add(row)
    db.commit()
    return row


def test_periods_and_invalid_custom_range():
    now = datetime(2026, 8, 23, 14, 30)
    assert resolve_dashboard_period("today", now=now).start.date() == date(2026, 8, 23)
    assert resolve_dashboard_period("last_7_days", now=now).start.date() == date(2026, 8, 17)
    assert resolve_dashboard_period("this_month", now=now).start.date() == date(2026, 8, 1)
    assert resolve_dashboard_period("last_month", now=now).start.date() == date(2026, 7, 1)
    assert resolve_dashboard_period("this_quarter", now=now).start.date() == date(2026, 7, 1)
    assert resolve_dashboard_period("this_year", now=now).start.date() == date(2026, 1, 1)
    custom = resolve_dashboard_period("custom", from_date=date(2026, 8, 2), to_date=date(2026, 8, 4), now=now)
    assert custom.end.date() == date(2026, 8, 5)
    with pytest.raises(HTTPException):
        resolve_dashboard_period("custom", from_date=date(2026, 8, 5), to_date=date(2026, 8, 4), now=now)


def test_operational_overview_aggregates_exceptions_costs_and_deduplicates_maintenance(db: Session):
    now = datetime(2026, 8, 23, 14, 30)
    admin = user(db)
    available = vehicle(
        db, "01-101-AA", acquisition_date=date(2015, 1, 1), purchase_price=Decimal("10000"),
        residual_value=Decimal("500"), expected_service_years=5, ownership_type="Owned", depreciation_method="Straight Line",
    )
    in_use = vehicle(db, "01-102-AA", status=4)
    in_service = vehicle(db, "01-103-AA", status=1)
    vehicle(db, "01-104-AA", status=2)
    archived = vehicle(db, "01-105-AA")
    archived.archived = True

    driver = Driver(
        full_name="Driver One", employee_number="E1", license_number="L1", license_category="B",
        license_expiry_date=now - timedelta(days=1), assigned_vehicle_id=in_use.id,
    )
    db.add(driver)
    db.flush()
    reservation = VehicleReservation(
        vehicle_id=in_use.id, reserved_by="Driver One", reservation_type="Business",
        start_date=now - timedelta(hours=6), end_date=now - timedelta(hours=2), status=1,
    )
    db.add(reservation)
    db.flush()
    assignment = VehicleAssignment(
        vehicle_id=in_use.id, driver_id=driver.id, reservation_id=reservation.id,
        start_datetime=now - timedelta(hours=6), start_odometer_km=1000, status="Active",
    )
    critical = WorkOrder(
        vehicle_id=in_service.id, title="Brake repair", priority="Critical", status="In Progress", source="Inspection",
        created_at=now - timedelta(days=6), expected_completion_date=now - timedelta(days=4), total_cost=Decimal("100"),
    )
    linked = WorkOrder(
        vehicle_id=available.id, title="Linked service", priority="Medium", status="Completed", source="Manual",
        created_at=now - timedelta(days=3), actual_completion_date=now - timedelta(days=2), total_cost=Decimal("100"),
    )
    unlinked = WorkOrder(
        vehicle_id=available.id, title="Unlinked service", priority="Medium", status="Completed", source="Manual",
        created_at=now - timedelta(days=3), actual_completion_date=now - timedelta(days=2), total_cost=Decimal("50"),
    )
    db.add_all([assignment, critical, linked, unlinked])
    db.flush()
    db.add_all([
        VehicleService(
            vehicle_id=available.id, work_order_id=linked.id, service_type="Service", service_date=now - timedelta(days=2),
            status="Completed", source="Work Order", cost=Decimal("100"),
        ),
        VehicleService(
            vehicle_id=in_service.id, service_type="Oil", service_date=now - timedelta(days=50), status="Completed",
            source="Manual", next_service_date=now - timedelta(days=2), cost=Decimal("0"),
        ),
        Inspection(vehicle_id=in_service.id, driver_id=driver.id, inspection_type="Daily", inspection_date=now, overall_status="Failed"),
        VehicleFuel(
            vehicle_id=available.id, refuel_date=now, quantity=Decimal("10"), unit="L", unit_cost=Decimal("2"),
            total_cost=Decimal("20"), fuel_type="Diesel", location="P", station_name="S", odometer_km=100,
        ),
        VehicleFuel(
            vehicle_id=available.id, refuel_date=now, quantity=Decimal("20"), unit="KWH", unit_cost=Decimal("0.5"),
            total_cost=Decimal("10"), fuel_type="Electric", location="P", station_name="S", odometer_km=200,
        ),
        VehicleOperatingCost(vehicle_id=available.id, category="Insurance", cost_date=now.date(), amount=Decimal("30")),
    ])
    accident = VehicleAccident(
        vehicle_id=in_service.id, driver_id=driver.id, accident_date=now, location="P", severity="Critical",
        status="Claim Opened", vehicle_available_after_accident=False, actual_damage_cost=Decimal("200"),
    )
    db.add(accident)
    db.flush()
    db.add(AccidentClaim(
        accident_id=accident.id, insurance_company="I", policy_number="P", claim_number="C",
        claim_status="Open", claim_opened_date=now, settlement_amount=Decimal("50"), deductible=Decimal("20"),
    ))
    db.commit()

    result = build_dashboard_overview(db, admin, period="this_month", now=now)

    assert result["fleet"] == {
        "total": 4, "operational": 3, "available": 1, "in_use": 1, "in_service": 1,
        "unavailable": 1, "availability_percentage": 25.0,
    }
    assert result["usage"]["active_count"] == 1
    assert result["usage"]["overdue_returns"] == 1
    assert result["maintenance"]["critical_work_orders"] == 1
    assert result["maintenance"]["overdue_work_orders"] == 1
    assert result["maintenance"]["overdue_reminders"] == 1
    assert result["maintenance"]["failed_inspections"] == 1
    assert {item["type"] for item in result["attention"]}.issuperset({
        "return_overdue", "work_order_overdue", "service_overdue", "inspection_failed",
        "driver_license_expired", "accident_critical",
    })
    assert result["attention"][0]["priority"] == "Critical"
    assert len(result["attention"]) <= 10
    assert result["reservations"]["approved_today"] == 1
    assert result["costs"]["fuel"] == 20.0
    assert result["costs"]["charging"] == 10.0
    assert result["costs"]["maintenance"] == 150.0
    assert result["costs"]["accidents"] == 150.0
    assert result["costs"]["other"] == 30.0
    assert result["safety"]["open_claims"] == 1
    assert result["safety"]["unrecovered_cost"] == 150.0
    assert result["fleet_health"] is not None


def test_financial_data_is_omitted_without_cost_permissions(db: Session):
    viewer = user(db, role="viewer", email="viewer@example.com")
    vehicle(db, "01-201-AA")
    result = build_dashboard_overview(db, viewer, now=datetime(2026, 8, 23))
    assert result["can_view_costs"] is False
    assert result["costs"] is None
    assert result["fleet_health"] is None
    assert result["safety"]["damage_cost"] is None


def test_location_department_cost_center_and_own_record_scopes(db: Session):
    scoped = user(db, role="viewer", email="scoped@example.com")
    seed_authorization_defaults(db)
    location_a, location_b = Location(code="A", name="A"), Location(code="B", name="B")
    department_a, department_b = Department(code="A", name="A"), Department(code="B", name="B")
    db.add_all([location_a, location_b, department_a, department_b])
    db.flush()
    first = vehicle(db, "01-301-AA", location=location_a)
    second = vehicle(db, "01-302-AA", location=location_b)
    driver = Driver(
        full_name="Scoped Driver", employee_number="E3", department="A", department_id=department_a.id,
        license_number="L3", license_category="B", license_expiry_date=datetime(2030, 1, 1),
        assigned_vehicle_id=first.id, user_id=scoped.id,
    )
    db.add(driver)
    db.flush()
    viewer_role = db.query(Role).filter(Role.code == "viewer").one()
    assignment = db.query(UserRole).filter(UserRole.user_id == scoped.id, UserRole.role_id == viewer_role.id).one()
    assignment.location_id = location_a.id
    assignment.department_id = department_a.id
    assignment.own_records_only = True
    db.commit()

    result = build_dashboard_overview(db, scoped, location_id=location_a.id, department_id=department_a.id)
    assert result["fleet"]["total"] == 1
    assert result["fleet"]["available"] == 1
    assert {row["id"] for row in result["filter_options"]["locations"]} == {location_a.id}
    with pytest.raises(HTTPException) as denied:
        build_dashboard_overview(db, scoped, location_id=location_b.id)
    assert denied.value.status_code == 403
    assert second.id not in {first.id}


def test_tenant_session_excludes_other_company_from_dashboard():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    seed = Session(engine)
    seed.add_all([Company(id=1, name="A", slug="a"), Company(id=2, name="B", slug="b")])
    admin = User(company_id=1, email="a@example.com", full_name="A", hashed_password="x", role="admin")
    seed.add(admin)
    seed.add_all([
        Vehicle(company_id=1, brand="A", model="A", fuel_type="D", vehicle_location="A", license_plate="01-401-AA", registration_country="XK", license_plate_normalized="01401AA"),
        Vehicle(company_id=2, brand="B", model="B", fuel_type="D", vehicle_location="B", license_plate="01-402-AA", registration_country="XK", license_plate_normalized="01402AA"),
    ])
    seed.commit()
    admin_id = admin.id
    seed.close()
    db = TenantSession(bind=engine)
    set_tenant_context(db, 1)
    result = build_dashboard_overview(db, db.get(User, admin_id), now=datetime(2026, 8, 23))
    assert result["fleet"]["total"] == 1
    db.close()
    engine.dispose()
