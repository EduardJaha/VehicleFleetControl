from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session, joinedload

from app.core.security import require_roles
from app.db.session import get_db
from app.models import Driver, User, Vehicle, VehicleFuel, VehiclePaper, VehicleReservation, VehicleService, WorkOrder
from app.schemas import UserRole
from app.utils.dates import format_date, parse_date
from app.utils.domain import parse_vehicle_status, reservation_status_name, status_name
from app.services.audit import record_audit

router = APIRouter(dependencies=[Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.finance))])


def money(value: str | Decimal | int | float | None) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def date_or_none(value: str | None, name: str):
    return parse_date(value, name) if value else None


def in_date_range(value: datetime | None, from_date: datetime | None, to_date: datetime | None) -> bool:
    if value is None:
        return False
    if from_date and value < from_date:
        return False
    if to_date and value > to_date:
        return False
    return True


def filtered_vehicles(db: Session, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None) -> list[Vehicle]:
    query = db.query(Vehicle).options(joinedload(Vehicle.assigned_drivers)).filter(Vehicle.archived.is_(False))
    if license_plate:
        query = query.filter(Vehicle.license_plate.ilike(f"%{license_plate.strip().upper()}%"))
    if vehicle_status:
        query = query.filter(Vehicle.status == parse_vehicle_status(vehicle_status))
    if department or driver_id:
        query = query.join(Vehicle.assigned_drivers)
        if department:
            query = query.filter(Driver.department.ilike(f"%{department.strip()}%"))
        if driver_id:
            query = query.filter(Driver.id == driver_id)
    return query.all()


def report_response(kpis: dict, rows: list[dict]) -> dict:
    return {"kpis": kpis, "rows": rows}


def fleet_summary_report(db: Session, **filters) -> dict:
    vehicles = filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"))
    rows = [
        {
            "license_plate": vehicle.license_plate,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "status": status_name(vehicle.status),
            "location": vehicle.vehicle_location,
            "odometer_km": vehicle.odometer_km or 0,
        }
        for vehicle in vehicles
    ]
    return report_response(
        {
            "total_vehicles": len(vehicles),
            "active_vehicles": sum(1 for vehicle in vehicles if vehicle.status == 0),
            "vehicles_in_service": sum(1 for vehicle in vehicles if vehicle.status == 1),
            "sold_or_out_of_use": sum(1 for vehicle in vehicles if vehicle.status in {2, 3}),
            "open_work_orders": db.query(WorkOrder).filter(WorkOrder.status.notin_(["Completed", "Cancelled"])).count(),
        },
        rows,
    )


def fuel_costs_report(db: Session, **filters) -> dict:
    from_date = date_or_none(filters.get("from_date"), "from_date")
    to_date = date_or_none(filters.get("to_date"), "to_date")
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"))}
    records = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle)).filter(VehicleFuel.archived.is_(False)).order_by(VehicleFuel.refuel_date.desc()).all()
    rows = []
    total = Decimal("0")
    liters = Decimal("0")
    for record in records:
        if record.vehicle_id not in vehicle_ids or not in_date_range(record.refuel_date, from_date, to_date):
            continue
        row_total = money(record.total_cost)
        row_liters = money(record.liters)
        total += row_total
        liters += row_liters
        rows.append({
            "license_plate": record.vehicle.license_plate,
            "date": format_date(record.refuel_date),
            "fuel_type": record.fuel_type,
            "liters": float(row_liters),
            "cost_per_liter": float(money(record.cost_per_liter)),
            "total_cost": float(row_total),
            "station": record.station_name,
            "odometer_km": record.odometer_km,
        })
    return report_response({"total_fuel_cost": float(total), "total_liters": float(liters), "record_count": len(rows)}, rows)


def service_costs_report(db: Session, **filters) -> dict:
    from_date = date_or_none(filters.get("from_date"), "from_date")
    to_date = date_or_none(filters.get("to_date"), "to_date")
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"))}
    records = db.query(VehicleService).options(joinedload(VehicleService.vehicle)).filter(VehicleService.archived.is_(False)).order_by(VehicleService.service_date.desc()).all()
    rows = []
    total = Decimal("0")
    for record in records:
        if record.vehicle_id not in vehicle_ids or not in_date_range(record.service_date, from_date, to_date):
            continue
        row_cost = money(record.cost)
        total += row_cost
        rows.append({
            "license_plate": record.vehicle.license_plate,
            "date": format_date(record.service_date),
            "service_type": record.service_type,
            "workshop": record.workshop,
            "odometer_km": record.odometer_km,
            "cost": float(row_cost),
            "description": record.description,
        })
    return report_response({"total_service_cost": float(total), "service_count": len(rows)}, rows)


def work_orders_report(db: Session, **filters) -> dict:
    from_date = date_or_none(filters.get("from_date"), "from_date")
    to_date = date_or_none(filters.get("to_date"), "to_date")
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"))}
    records = db.query(WorkOrder).options(
        joinedload(WorkOrder.vehicle), joinedload(WorkOrder.driver), joinedload(WorkOrder.linked_service)
    ).filter(WorkOrder.archived.is_(False)).order_by(WorkOrder.created_at.desc()).all()
    rows = []
    total = Decimal("0")
    status_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    for record in records:
        report_date = record.expected_completion_date or record.created_at
        if record.vehicle_id not in vehicle_ids or not in_date_range(report_date, from_date, to_date):
            continue
        row_total = money(record.total_cost)
        counted_cost = Decimal("0") if record.linked_service else row_total
        total += counted_cost
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        priority_counts[record.priority] = priority_counts.get(record.priority, 0) + 1
        rows.append({
            "id": record.id,
            "license_plate": record.vehicle.license_plate,
            "driver": record.driver.full_name if record.driver else None,
            "title": record.title,
            "priority": record.priority,
            "status": record.status,
            "workshop": record.workshop,
            "expected_completion_date": format_date(record.expected_completion_date),
            "actual_completion_date": format_date(record.actual_completion_date),
            "total_cost": float(row_total),
            "cost_basis": "Actual cost recorded on linked Service" if record.linked_service else (
                "Actual completed cost" if record.status == "Completed" else "Planned or estimated cost"
            ),
            "linked_service_id": record.linked_service.id if record.linked_service else None,
            "counted_work_order_cost": float(counted_cost),
        })
    kpis = {"total_work_order_cost": float(total), "work_order_count": len(rows)}
    kpis.update({f"status_{key.lower().replace(' ', '_')}": value for key, value in status_counts.items()})
    kpis.update({f"priority_{key.lower()}": value for key, value in priority_counts.items()})
    return report_response(kpis, rows)


def vehicle_costs_report(db: Session, **filters) -> dict:
    vehicles = filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"))
    fuel = fuel_costs_report(db, **filters)["rows"]
    services = service_costs_report(db, **filters)["rows"]
    work_orders = work_orders_report(db, **filters)["rows"]
    by_plate: dict[str, dict] = {}
    for vehicle in vehicles:
        by_plate[vehicle.license_plate] = {
            "license_plate": vehicle.license_plate,
            "brand": vehicle.brand,
            "model": vehicle.model,
            "odometer_km": vehicle.odometer_km or 0,
            "fuel_cost": 0.0,
            "service_cost": 0.0,
            "work_order_cost": 0.0,
            "total_cost": 0.0,
            "cost_per_km": None,
        }
    for row in fuel:
        by_plate[row["license_plate"]]["fuel_cost"] += float(row["total_cost"] or 0)
    for row in services:
        by_plate[row["license_plate"]]["service_cost"] += float(row["cost"] or 0)
    for row in work_orders:
        by_plate[row["license_plate"]]["work_order_cost"] += float(row["counted_work_order_cost"] or 0)
    for row in by_plate.values():
        row["total_cost"] = row["fuel_cost"] + row["service_cost"] + row["work_order_cost"]
        if row["odometer_km"]:
            row["cost_per_km"] = round(row["total_cost"] / row["odometer_km"], 4)
    rows = sorted(by_plate.values(), key=lambda item: item["total_cost"], reverse=True)
    return report_response({"total_vehicle_cost": float(sum(row["total_cost"] for row in rows)), "vehicle_count": len(rows)}, rows)


def reservations_report(db: Session, **filters) -> dict:
    from_date = date_or_none(filters.get("from_date"), "from_date")
    to_date = date_or_none(filters.get("to_date"), "to_date")
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"))}
    records = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle)).filter(VehicleReservation.archived.is_(False)).order_by(VehicleReservation.start_date.desc()).all()
    rows = []
    counts: dict[str, int] = {}
    for record in records:
        if record.vehicle_id not in vehicle_ids or not in_date_range(record.start_date, from_date, to_date):
            continue
        status = reservation_status_name(record.status)
        counts[status] = counts.get(status, 0) + 1
        rows.append({
            "license_plate": record.vehicle.license_plate,
            "reserved_by": record.reserved_by,
            "type": record.reservation_type,
            "start_date": format_date(record.start_date),
            "end_date": format_date(record.end_date),
            "status": status,
            "notes": record.notes,
        })
    kpis = {"reservation_count": len(rows)}
    kpis.update({f"reservations_{key.lower()}": value for key, value in counts.items()})
    return report_response(kpis, rows)


def document_expiry_report(db: Session, **filters) -> dict:
    today = datetime.utcnow()
    upcoming_cutoff = today + timedelta(days=30)
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"))}
    records = db.query(VehiclePaper).options(joinedload(VehiclePaper.vehicle)).filter(VehiclePaper.archived.is_(False)).order_by(VehiclePaper.expiry_date.asc()).all()
    rows = []
    overdue = 0
    upcoming = 0
    for record in records:
        if record.vehicle_id not in vehicle_ids:
            continue
        state = "Valid"
        if record.expiry_date < today:
            state = "Overdue"
            overdue += 1
        elif record.expiry_date <= upcoming_cutoff:
            state = "Upcoming"
            upcoming += 1
        rows.append({
            "license_plate": record.vehicle.license_plate,
            "document_type": record.document_type,
            "issue_date": format_date(record.issue_date),
            "expiry_date": format_date(record.expiry_date),
            "status": state,
        })
    return report_response({"document_count": len(rows), "upcoming_expiries": upcoming, "overdue_expiries": overdue}, rows)


REPORTS: dict[str, Callable[..., dict]] = {
    "fleet-summary": fleet_summary_report,
    "fuel-costs": fuel_costs_report,
    "service-costs": service_costs_report,
    "vehicle-costs": vehicle_costs_report,
    "reservations": reservations_report,
    "document-expiry": document_expiry_report,
    "work-orders": work_orders_report,
}


def build_excel(report_name: str, data: dict) -> BytesIO:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "KPIs"
    summary.append(["Metric", "Value"])
    for key, value in data["kpis"].items():
        summary.append([key, value])

    rows_sheet = workbook.create_sheet("Rows")
    rows = data["rows"]
    if rows:
        headers = list(rows[0].keys())
        rows_sheet.append(headers)
        for row in rows:
            rows_sheet.append([row.get(header) for header in headers])
    else:
        rows_sheet.append(["No rows"])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def excel_response(report_name: str, data: dict) -> StreamingResponse:
    output = build_excel(report_name, data)
    filename = f"{report_name}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def report_filters(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None) -> dict:
    return {
        "from_date": from_date,
        "to_date": to_date,
        "license_plate": license_plate,
        "vehicle_status": vehicle_status,
        "department": department,
        "driver_id": driver_id,
    }


@router.get("/fleet-summary")
def fleet_summary(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, db: Session = Depends(get_db)):
    return fleet_summary_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id))


@router.get("/fuel-costs")
def fuel_costs(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, db: Session = Depends(get_db)):
    return fuel_costs_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id))


@router.get("/service-costs")
def service_costs(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, db: Session = Depends(get_db)):
    return service_costs_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id))


@router.get("/vehicle-costs")
def vehicle_costs(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, db: Session = Depends(get_db)):
    return vehicle_costs_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id))


@router.get("/reservations")
def reservations(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, db: Session = Depends(get_db)):
    return reservations_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id))


@router.get("/document-expiry")
def document_expiry(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, db: Session = Depends(get_db)):
    return document_expiry_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id))


@router.get("/work-orders")
def work_orders(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, db: Session = Depends(get_db)):
    return work_orders_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id))


@router.get("/{report_name}/export")
def export_report(
    report_name: str, from_date: str | None = None, to_date: str | None = None,
    license_plate: str | None = None, vehicle_status: str | None = None,
    department: str | None = None, driver_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.finance)),
):
    report = REPORTS.get(report_name)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    data = report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id))
    record_audit(
        db, action="Report exported", entity_type="Report", entity_id=None, user=current_user,
        new_values={"report_name": report_name}, description=f"Report '{report_name}' exported.",
    )
    db.commit()
    return excel_response(report_name, data)
