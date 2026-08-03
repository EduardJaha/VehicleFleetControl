import csv
import io
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Driver, User, Vehicle, VehicleAssignment, VehicleService, WorkOrder
from app.schemas import BulkActionOut, BulkActionRequest, UserRole
from app.services.audit import record_audit
from app.services.vehicle_assignments import ACTIVE_ASSIGNMENT_STATUSES

router = APIRouter(dependencies=[Depends(get_current_user)])
BULK_ROLES = (UserRole.admin, UserRole.fleet_manager)
VEHICLE_STATUSES = {0, 1, 2, 3, 4}
DRIVER_STATUSES = {"Active", "Suspended", "Left Company"}
ACTIONS = {"archive", "restore", "change_status", "change_location", "change_department", "assign_service_program", "create_work_orders"}


def selected_rows(db: Session, entity_type: str, ids: list[int]):
    model = Vehicle if entity_type == "Vehicles" else Driver if entity_type == "Drivers" else None
    if model is None:
        raise HTTPException(status_code=422, detail="Bulk actions currently support Vehicles and Drivers.")
    rows = db.query(model).filter(model.id.in_(ids)).order_by(model.id).all()
    found = {row.id for row in rows}
    missing = sorted(set(ids) - found)
    if missing:
        raise HTTPException(status_code=404, detail=f"Selected records were not found: {', '.join(map(str, missing))}.")
    return rows


def ensure_can_archive(db: Session, entity_type: str, ids: list[int]) -> None:
    field = VehicleAssignment.vehicle_id if entity_type == "Vehicles" else VehicleAssignment.driver_id
    conflict = db.query(VehicleAssignment).filter(
        field.in_(ids),
        VehicleAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        VehicleAssignment.archived.is_(False),
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Complete or cancel active Vehicle Assignments before bulk archiving.")


@router.post("", response_model=BulkActionOut)
def apply_bulk_action(
    payload: BulkActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*BULK_ROLES)),
):
    if payload.action not in ACTIONS:
        raise HTTPException(status_code=422, detail="Unsupported bulk action.")
    rows = selected_rows(db, payload.entity_type, payload.ids)
    if payload.action == "restore" and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can restore archived records.")
    if payload.action not in {"archive", "restore"} and any(row.archived for row in rows):
        raise HTTPException(status_code=409, detail="Restore archived records before applying other bulk changes.")
    now = datetime.utcnow()
    created_ids: list[int] = []
    if payload.action == "archive":
        ensure_can_archive(db, payload.entity_type, payload.ids)
        for row in rows:
            row.archived, row.archived_at, row.archived_by = True, now, current_user.id
    elif payload.action == "restore":
        for row in rows:
            row.archived, row.archived_at, row.archived_by = False, None, None
    elif payload.action == "change_status":
        if payload.entity_type == "Vehicles":
            try:
                status = int(payload.value)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="Vehicle status must be 0 through 4.") from exc
            if status not in VEHICLE_STATUSES:
                raise HTTPException(status_code=422, detail="Vehicle status must be 0 through 4.")
        else:
            status = str(payload.value or "")
            if status not in DRIVER_STATUSES:
                raise HTTPException(status_code=422, detail="Driver status is invalid.")
        for row in rows:
            row.status = status
    elif payload.action == "change_location":
        if payload.entity_type != "Vehicles":
            raise HTTPException(status_code=422, detail="Change Location only applies to Vehicles.")
        value = str(payload.value or "").strip()
        if not value or len(value) > 255:
            raise HTTPException(status_code=422, detail="Enter a location of at most 255 characters.")
        for row in rows:
            row.vehicle_location = value
    elif payload.action == "change_department":
        if payload.entity_type != "Drivers":
            raise HTTPException(status_code=422, detail="Change Department only applies to Drivers.")
        value = str(payload.value or "").strip()
        if not value or len(value) > 100:
            raise HTTPException(status_code=422, detail="Enter a department of at most 100 characters.")
        for row in rows:
            row.department = value
            row.updated_at = now
    elif payload.action == "create_work_orders":
        if payload.entity_type != "Vehicles":
            raise HTTPException(status_code=422, detail="Work Orders can only be created for Vehicles.")
        title = str(payload.options.get("title") or payload.value or "Bulk-created Work Order").strip()
        priority = str(payload.options.get("priority") or "Medium")
        if not title or len(title) > 150 or priority not in {"Low", "Medium", "High", "Critical"}:
            raise HTTPException(status_code=422, detail="Enter a valid Work Order title and priority.")
        for vehicle in rows:
            work_order = WorkOrder(
                vehicle_id=vehicle.id, source="Manual", title=title,
                description=payload.options.get("description"), priority=priority, status="Open",
                requested_by=current_user.full_name, created_by=current_user.full_name,
            )
            db.add(work_order)
            db.flush()
            created_ids.append(work_order.id)
    elif payload.action == "assign_service_program":
        if payload.entity_type != "Vehicles":
            raise HTTPException(status_code=422, detail="Service Programs can only be assigned to Vehicles.")
        service_type = str(payload.options.get("service_type") or payload.value or "").strip()
        try:
            days = int(payload.options.get("interval_days") or 180)
            km = int(payload.options.get("interval_km") or 10_000)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Service Program intervals must be whole numbers.") from exc
        if not service_type or len(service_type) > 100 or not 1 <= days <= 3650 or not 1 <= km <= 500_000:
            raise HTTPException(status_code=422, detail="Enter a valid Service Program name and interval.")
        for vehicle in rows:
            reminder = VehicleService(
                vehicle_id=vehicle.id, service_type=service_type,
                description=f"Service Program assigned in bulk by {current_user.full_name}.",
                service_date=now, odometer_km=vehicle.odometer_km,
                next_service_date=now + timedelta(days=days), next_service_km_interval=km,
                next_service_odometer_km=(vehicle.odometer_km or 0) + km,
                source="Manual", status="Reminder", reminder_status="Upcoming",
            )
            db.add(reminder)
            db.flush()
            created_ids.append(reminder.id)
    record_audit(
        db, action=f"Bulk {payload.action.replace('_', ' ')}", entity_type=payload.entity_type,
        entity_id=None, user=current_user,
        new_values={"ids": payload.ids, "value": payload.value, "options": payload.options, "created_ids": created_ids},
        description=f"Bulk action {payload.action} applied to {len(rows)} {payload.entity_type} records.",
    )
    db.commit()
    return BulkActionOut(entity_type=payload.entity_type, action=payload.action, affected=len(rows), created_ids=created_ids)


@router.get("/export")
def export_selected(
    entity_type: str,
    ids: str = Query(min_length=1, max_length=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*BULK_ROLES)),
):
    try:
        selected_ids = list(dict.fromkeys(int(value) for value in ids.split(",") if value.strip()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="ids must be comma-separated integers.") from exc
    if not selected_ids or len(selected_ids) > 500:
        raise HTTPException(status_code=422, detail="Select between 1 and 500 records.")
    rows = selected_rows(db, entity_type, selected_ids)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if entity_type == "Vehicles":
        writer.writerow(["ID", "Registration Country", "Licence Plate", "Brand", "Model", "Fuel Type", "Location", "VIN", "Odometer KM", "Status", "Archived"])
        for row in rows:
            writer.writerow([row.id, row.registration_country, row.license_plate, row.brand, row.model, row.fuel_type, row.vehicle_location, row.vin_number, row.odometer_km, row.status, row.archived])
    else:
        writer.writerow(["ID", "Full Name", "Employee Number", "Email", "Phone", "Department", "Licence Number", "Licence Category", "Licence Expiry", "Status", "Archived"])
        for row in rows:
            writer.writerow([row.id, row.full_name, row.employee_number, row.email, row.phone_number, row.department, row.license_number, row.license_category, row.license_expiry_date.strftime("%d-%m-%Y"), row.status, row.archived])
    record_audit(
        db, action="Bulk export selected", entity_type=entity_type, entity_id=None, user=current_user,
        new_values={"ids": selected_ids}, description=f"Exported {len(rows)} selected {entity_type} records.",
    )
    db.commit()
    filename = f"selected-{entity_type.casefold().replace(' ', '-')}.csv"
    return Response(
        content=output.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}", "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
