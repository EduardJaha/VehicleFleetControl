from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session, joinedload

from app.core.security import require_roles
from app.db.session import get_db
from app.models import (
    Driver, User, Vehicle, VehicleAccident, VehicleAssignment, VehicleFuel,
    VehiclePaper, VehicleReservation, VehicleService, WorkOrder,
)
from app.schemas import EnergyUnit, UserRole
from app.utils.dates import format_date, parse_date
from app.utils.domain import normalize_plate, parse_vehicle_status, reservation_status_name, status_name
from app.services.license_plates import RegistrationCountry, registration_country_name
from app.services.audit import record_audit
from app.services.document_compliance import compliance_dashboard
from app.core.i18n import request_language

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


def filtered_vehicles(
    db: Session,
    license_plate: str | None = None,
    vehicle_status: str | None = None,
    department: str | None = None,
    driver_id: int | None = None,
    registration_country: str | None = None,
) -> list[Vehicle]:
    query = db.query(Vehicle).options(joinedload(Vehicle.assigned_drivers)).filter(Vehicle.archived.is_(False))
    if license_plate:
        query = query.filter(Vehicle.license_plate_normalized.ilike(f"%{normalize_plate(license_plate)}%"))
    if registration_country:
        try:
            country = RegistrationCountry(registration_country.strip().upper())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Only Albania and Kosovo are currently supported.") from exc
        query = query.filter(Vehicle.registration_country == country.value)
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


def registration_fields(vehicle: Vehicle) -> dict:
    return {
        "registration_country": vehicle.registration_country,
        "registration_country_name": registration_country_name(vehicle.registration_country),
    }


def fleet_summary_report(db: Session, **filters) -> dict:
    vehicles = filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"), filters.get("registration_country"))
    rows = [
        {
            **registration_fields(vehicle),
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
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"), filters.get("registration_country"))}
    records = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle)).filter(VehicleFuel.archived.is_(False)).order_by(VehicleFuel.refuel_date.desc()).all()
    rows = []
    total = Decimal("0")
    total_liters = Decimal("0")
    total_kwh = Decimal("0")
    liquid_record_count = 0
    charging_session_count = 0
    for record in records:
        if record.vehicle_id not in vehicle_ids or not in_date_range(record.refuel_date, from_date, to_date):
            continue
        row_total = money(record.total_cost)
        row_quantity = money(record.quantity)
        total += row_total
        if record.unit == EnergyUnit.kilowatt_hour.value:
            total_kwh += row_quantity
            charging_session_count += 1
        else:
            total_liters += row_quantity
            liquid_record_count += 1
        rows.append({
            **registration_fields(record.vehicle),
            "license_plate": record.vehicle.license_plate,
            "vehicle": f"{record.vehicle.brand} {record.vehicle.model}",
            "date": format_date(record.refuel_date),
            "fuel_or_energy_type": record.fuel_type,
            "quantity": float(row_quantity),
            "unit": record.unit,
            "unit_price": float(money(record.unit_cost)),
            "total_cost": float(row_total),
            "location": record.location,
            "station_or_provider": record.station_name,
            "odometer_km": record.odometer_km,
        })
    return report_response({
        "total_fuel_cost": float(total),
        "total_fuel_and_charging_cost": float(total),
        "total_liters": float(total_liters),
        "total_kwh": float(total_kwh),
        "liquid_fuel_record_count": liquid_record_count,
        "charging_session_count": charging_session_count,
        "record_count": len(rows),
    }, rows)


def service_costs_report(db: Session, **filters) -> dict:
    from_date = date_or_none(filters.get("from_date"), "from_date")
    to_date = date_or_none(filters.get("to_date"), "to_date")
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"), filters.get("registration_country"))}
    records = db.query(VehicleService).options(joinedload(VehicleService.vehicle)).filter(VehicleService.archived.is_(False)).order_by(VehicleService.service_date.desc()).all()
    rows = []
    total = Decimal("0")
    for record in records:
        if record.vehicle_id not in vehicle_ids or not in_date_range(record.service_date, from_date, to_date):
            continue
        row_cost = money(record.cost)
        total += row_cost
        rows.append({
            **registration_fields(record.vehicle),
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
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"), filters.get("registration_country"))}
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
            **registration_fields(record.vehicle),
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
    vehicles = filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"), filters.get("registration_country"))
    fuel = fuel_costs_report(db, **filters)["rows"]
    services = service_costs_report(db, **filters)["rows"]
    work_orders = work_orders_report(db, **filters)["rows"]
    by_plate: dict[str, dict] = {}
    for vehicle in vehicles:
        by_plate[vehicle.license_plate] = {
            **registration_fields(vehicle),
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
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"), filters.get("registration_country"))}
    records = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle)).filter(VehicleReservation.archived.is_(False)).order_by(VehicleReservation.start_date.desc()).all()
    rows = []
    counts: dict[str, int] = {}
    for record in records:
        if record.vehicle_id not in vehicle_ids or not in_date_range(record.start_date, from_date, to_date):
            continue
        status = reservation_status_name(record.status)
        counts[status] = counts.get(status, 0) + 1
        rows.append({
            **registration_fields(record.vehicle),
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
    vehicle_ids = {vehicle.id for vehicle in filtered_vehicles(db, filters.get("license_plate"), filters.get("vehicle_status"), filters.get("department"), filters.get("driver_id"), filters.get("registration_country"))}
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
            **registration_fields(record.vehicle),
            "license_plate": record.vehicle.license_plate,
            "document_type": record.document_type,
            "issue_date": format_date(record.issue_date),
            "expiry_date": format_date(record.expiry_date),
            "status": state,
        })
    return report_response({"document_count": len(rows), "upcoming_expiries": upcoming, "overdue_expiries": overdue}, rows)


def document_compliance_report(db: Session, **filters) -> dict:
    dashboard = compliance_dashboard(db)
    rows = dashboard["items"]
    if filters.get("registration_country"):
        rows = [row for row in rows if row["country"] == filters["registration_country"].strip().upper()]
    if filters.get("department"):
        term = filters["department"].strip().casefold()
        rows = [row for row in rows if term in (row["department"] or "").casefold()]
    if filters.get("driver_id"):
        rows = [
            row for row in rows
            if row["owner_type"] == "Driver" and row["owner_id"] == filters["driver_id"]
        ]
    if filters.get("license_plate"):
        term = normalize_plate(filters["license_plate"])
        rows = [
            row for row in rows
            if row["owner_type"] != "Vehicle" or term in normalize_plate(row["owner_name"])
        ]
    compliant = sum(1 for row in rows if row["status"] in {"Valid", "Expiring Soon"})
    return report_response(
        {
            "requirement_count": len(rows),
            "compliant_count": compliant,
            "missing_required": sum(1 for row in rows if row["status"] == "Missing"),
            "expired_documents": sum(1 for row in rows if row["status"] == "Expired"),
            "renewal_in_progress": sum(1 for row in rows if row["status"] == "Renewal In Progress"),
            "compliance_rate": round(compliant / len(rows) * 100, 2) if rows else 100.0,
        },
        rows,
    )


def accidents_report(db: Session, **filters) -> dict:
    from_date = date_or_none(filters.get("from_date"), "from_date")
    to_date = date_or_none(filters.get("to_date"), "to_date")
    vehicles = filtered_vehicles(
        db, filters.get("license_plate"), filters.get("vehicle_status"),
        filters.get("department"), filters.get("driver_id"), filters.get("registration_country"),
    )
    vehicle_ids = {vehicle.id for vehicle in vehicles}
    query = db.query(VehicleAccident).options(
        joinedload(VehicleAccident.vehicle),
        joinedload(VehicleAccident.driver),
        joinedload(VehicleAccident.claim),
    ).filter(VehicleAccident.archived.is_(False))
    accidents = [
        row for row in query.order_by(VehicleAccident.accident_date.desc()).all()
        if row.vehicle_id in vehicle_ids and in_date_range(row.accident_date, from_date, to_date)
    ]

    assignment_query = db.query(VehicleAssignment).filter(
        VehicleAssignment.archived.is_(False),
        VehicleAssignment.vehicle_id.in_(vehicle_ids or {-1}),
        VehicleAssignment.end_odometer_km.is_not(None),
    )
    if from_date:
        assignment_query = assignment_query.filter(VehicleAssignment.start_datetime >= from_date)
    if to_date:
        assignment_query = assignment_query.filter(VehicleAssignment.start_datetime <= to_date)
    distance = sum(
        max(0, (row.end_odometer_km or row.start_odometer_km) - row.start_odometer_km)
        for row in assignment_query.all()
    )

    actual_cost = sum((money(row.actual_damage_cost) for row in accidents), Decimal("0"))
    claim_cost = sum(
        (money(row.claim.settlement_amount) for row in accidents if row.claim), Decimal("0")
    )
    unrecovered = sum(
        (
            max(Decimal("0"), money(row.actual_damage_cost) - money(row.claim.settlement_amount if row.claim else None))
            for row in accidents
        ),
        Decimal("0"),
    )
    resolved = [
        (row.resolved_at - row.accident_date).total_seconds() / 86400
        for row in accidents if row.resolved_at
    ]
    fault_counts: dict[str, int] = {}
    driver_counts: dict[str, int] = {}
    vehicle_counts: dict[str, int] = {}
    rows = []
    for row in accidents:
        fault = row.fault_determination or "Undetermined"
        driver = row.driver.full_name if row.driver else "Unassigned"
        plate = row.vehicle.license_plate
        fault_counts[fault] = fault_counts.get(fault, 0) + 1
        driver_counts[driver] = driver_counts.get(driver, 0) + 1
        vehicle_counts[plate] = vehicle_counts.get(plate, 0) + 1
        settlement = money(row.claim.settlement_amount if row.claim else None)
        damage = money(row.actual_damage_cost)
        rows.append({
            "accident_id": row.id,
            "date": format_date(row.accident_date),
            "driver": driver,
            "license_plate": plate,
            "vehicle": f"{row.vehicle.brand} {row.vehicle.model}",
            "severity": row.severity,
            "status": row.status,
            "fault_determination": fault,
            "actual_damage_cost": float(damage),
            "claim_cost": float(settlement),
            "unrecovered_cost": float(max(Decimal("0"), damage - settlement)),
            "resolution_days": (
                round((row.resolved_at - row.accident_date).total_seconds() / 86400, 2)
                if row.resolved_at else None
            ),
        })
    data = report_response(
        {
            "total_accidents": len(accidents),
            "distance_km": distance,
            "accident_rate_per_100000_km": round(len(accidents) / distance * 100000, 2) if distance else 0,
            "actual_damage_cost": float(actual_cost),
            "claim_cost": float(claim_cost),
            "unrecovered_cost": float(unrecovered),
            "average_resolution_days": round(sum(resolved) / len(resolved), 2) if resolved else 0,
            "fault_distribution": ", ".join(f"{name}: {count}" for name, count in sorted(fault_counts.items())),
        },
        rows,
    )
    data["by_driver"] = [{"driver": name, "accidents": count} for name, count in sorted(driver_counts.items())]
    data["by_vehicle"] = [{"license_plate": name, "accidents": count} for name, count in sorted(vehicle_counts.items())]
    data["fault_distribution"] = [{"fault": name, "accidents": count} for name, count in sorted(fault_counts.items())]
    return data


REPORTS: dict[str, Callable[..., dict]] = {
    "fleet-summary": fleet_summary_report,
    "fuel-costs": fuel_costs_report,
    "service-costs": service_costs_report,
    "vehicle-costs": vehicle_costs_report,
    "reservations": reservations_report,
    "document-expiry": document_expiry_report,
    "document-compliance": document_compliance_report,
    "work-orders": work_orders_report,
    "accidents": accidents_report,
}


EXCEL_TEXT = {
    "en": {
        "kpis": "KPIs", "metric": "Metric", "value": "Value", "rows": "Rows", "no_rows": "No rows",
        "generated": "Generated", "filters": "Filters",
        "reports": {"fleet-summary": "Fleet Summary", "fuel-costs": "Fuel Costs", "service-costs": "Service Costs", "vehicle-costs": "Vehicle Costs", "reservations": "Reservations", "document-expiry": "Document Expiry", "document-compliance": "Document Compliance", "work-orders": "Work Orders", "accidents": "Accident and Claim Costs"},
    },
    "sq": {
        "kpis": "Treguesit", "metric": "Treguesi", "value": "Vlera", "rows": "Rreshtat", "no_rows": "Nuk ka rreshta",
        "generated": "Gjeneruar", "filters": "Filtrat",
        "reports": {"fleet-summary": "Përmbledhja e Flotës", "fuel-costs": "Kostot e Karburantit", "service-costs": "Kostot e Servisimit", "vehicle-costs": "Kostot e Automjeteve", "reservations": "Rezervimet", "document-expiry": "Skadimi i Dokumenteve", "document-compliance": "Pajtueshmëria e Dokumenteve", "work-orders": "Urdhrat e Punës", "accidents": "Kostot e Aksidenteve dhe Dëmeve"},
    },
}

EXCEL_HEADINGS_SQ = {
    "registration_country": "Shteti i Regjistrimit", "registration_country_name": "Shteti i Regjistrimit",
    "license_plate": "Targa", "brand": "Marka", "model": "Modeli", "status": "Statusi", "location": "Lokacioni",
    "odometer_km": "Kilometrazhi (km)", "vehicle": "Automjeti", "date": "Data", "fuel_or_energy_type": "Lloji i Karburantit ose Energjisë",
    "quantity": "Sasia", "unit": "Njësia", "unit_price": "Çmimi për Njësi", "total_cost": "Kostoja Totale",
    "station_or_provider": "Stacioni ose Ofruesi", "service_type": "Lloji i Servisimit", "workshop": "Servisi",
    "cost": "Kostoja", "description": "Përshkrimi", "driver": "Shoferi", "title": "Titulli", "priority": "Prioriteti",
    "expected_completion_date": "Data e Pritshme e Përfundimit", "actual_completion_date": "Data Faktike e Përfundimit",
    "reserved_by": "Rezervuar nga", "type": "Lloji", "start_date": "Data e Fillimit", "end_date": "Data e Përfundimit",
    "notes": "Shënime", "document_type": "Lloji i Dokumentit", "issue_date": "Data e Lëshimit", "expiry_date": "Data e Skadimit",
    "owner_type": "Lloji i Pronarit", "owner_id": "ID e Pronarit", "owner_name": "Pronari",
    "requirement_id": "ID e Kërkesës", "document_id": "ID e Dokumentit", "version_id": "ID e Versionit",
    "warning_days": "Ditët e Paralajmërimit", "file_path": "Skedari", "country": "Shteti",
}

EXCEL_VALUES_SQ = {
    "Active": "Aktiv", "In Service": "Në servis", "Sold": "Shitur", "Out of Use": "Jashtë përdorimit",
    "Open": "Hapur", "Assigned": "Caktuar", "In Progress": "Në proces", "Waiting for Parts": "Në pritje të pjesëve",
    "Completed": "Përfunduar", "Cancelled": "Anuluar", "Pending": "Në pritje", "Approved": "Miratuar", "Rejected": "Refuzuar",
    "Low": "I ulët", "Medium": "Mesatar", "High": "I lartë", "Critical": "Kritik", "Overdue": "Me afat të kaluar",
    "Upcoming": "Në vazhdim", "Valid": "I vlefshëm", "General Service": "Servis i përgjithshëm", "Oil Change": "Ndërrim vaji",
    "Tire Change/Control": "Ndërrim/Kontroll gomash", "Part Change": "Ndërrim pjese", "Maintenance": "Mirëmbajtje",
    "Registration": "Regjistrim", "Insurance": "Sigurim", "Technical Control": "Kontroll teknik", "Albania": "Shqipëria", "Kosovo": "Kosova",
    "Missing": "Mungon", "Expiring Soon": "Skadon së shpejti", "Expired": "I skaduar",
    "Renewal In Progress": "Rinovim në proces", "Archived": "I arkivuar", "Vehicle": "Automjet", "Driver": "Shofer",
}


def build_excel(report_name: str, data: dict, language: str = "en") -> BytesIO:
    text = EXCEL_TEXT.get(language, EXCEL_TEXT["en"])
    workbook = Workbook()
    summary = workbook.active
    summary.title = text["kpis"]
    summary.append([text["reports"].get(report_name, report_name)])
    summary.append([text["generated"], datetime.utcnow()])
    summary.append([])
    summary.append([text["metric"], text["value"]])
    for key, value in data["kpis"].items():
        summary.append([excel_heading(key, language), value])
    active_filters = {key: value for key, value in data.get("filters", {}).items() if value not in {None, ""}}
    if active_filters:
        summary.append([])
        summary.append([text["filters"]])
        for key, value in active_filters.items():
            summary.append([excel_heading(key, language), localize_excel_value(value, language)])

    rows_sheet = workbook.create_sheet(text["rows"])
    rows = data["rows"]
    if rows:
        headers = list(rows[0].keys())
        rows_sheet.append([excel_heading(header, language) for header in headers])
        for row in rows:
            rows_sheet.append([localize_excel_value(row.get(header), language) for header in headers])
    else:
        rows_sheet.append([text["no_rows"]])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def excel_heading(value: str, language: str = "en") -> str:
    if language == "sq" and value in EXCEL_HEADINGS_SQ:
        return EXCEL_HEADINGS_SQ[value]
    overrides = {
        "license_plate": "Licence Plate",
        "fuel_or_energy_type": "Fuel or Energy Type",
        "quantity": "Quantity",
        "unit": "Unit",
        "unit_price": "Unit Price",
        "total_cost": "Total Cost",
        "station_or_provider": "Station or Provider",
        "odometer_km": "Odometer KM",
    }
    return overrides.get(
        value,
        value.replace("_", " ").title().replace("Km", "KM"),
    )


def localize_excel_value(value, language: str):
    if language == "sq" and isinstance(value, str):
        return EXCEL_VALUES_SQ.get(value, value)
    return value


def excel_response(report_name: str, data: dict, language: str = "en") -> StreamingResponse:
    output = build_excel(report_name, data, language)
    filename = f"{report_name}-{'sq' if language == 'sq' else 'en'}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def report_filters(
    from_date: str | None = None,
    to_date: str | None = None,
    license_plate: str | None = None,
    vehicle_status: str | None = None,
    department: str | None = None,
    driver_id: int | None = None,
    registration_country: str | None = None,
) -> dict:
    return {
        "from_date": from_date,
        "to_date": to_date,
        "license_plate": license_plate,
        "vehicle_status": vehicle_status,
        "department": department,
        "driver_id": driver_id,
        "registration_country": registration_country,
    }


@router.get("/fleet-summary")
def fleet_summary(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return fleet_summary_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/fuel-costs")
def fuel_costs(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return fuel_costs_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/service-costs")
def service_costs(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return service_costs_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/vehicle-costs")
def vehicle_costs(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return vehicle_costs_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/reservations")
def reservations(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return reservations_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/document-expiry")
def document_expiry(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return document_expiry_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/document-compliance")
def document_compliance(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return document_compliance_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/work-orders")
def work_orders(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return work_orders_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/accidents")
def accidents(from_date: str | None = None, to_date: str | None = None, license_plate: str | None = None, vehicle_status: str | None = None, department: str | None = None, driver_id: int | None = None, registration_country: str | None = None, db: Session = Depends(get_db)):
    return accidents_report(db, **report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country))


@router.get("/{report_name}/export")
def export_report(
    request: Request,
    report_name: str, from_date: str | None = None, to_date: str | None = None,
    license_plate: str | None = None, vehicle_status: str | None = None,
    department: str | None = None, driver_id: int | None = None,
    registration_country: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.finance)),
):
    report = REPORTS.get(report_name)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    filters = report_filters(from_date, to_date, license_plate, vehicle_status, department, driver_id, registration_country)
    data = report(db, **filters)
    data["filters"] = filters
    record_audit(
        db, action="Report exported", entity_type="Report", entity_id=None, user=current_user,
        new_values={"report_name": report_name}, description=f"Report '{report_name}' exported.",
    )
    db.commit()
    return excel_response(report_name, data, request_language(request))
