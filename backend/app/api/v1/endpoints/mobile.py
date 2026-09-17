"""Small, explicitly owned mobile projections and retry-safe offline mutations.

No authentication tokens are stored in receipts. Every replay rechecks the current
company, actor, permission and resource ownership before returning a saved result.
"""
import hashlib
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import active_role, authorization_scope, has_permission
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import (Driver, Inspection, MobileOperation, Technician, User, Vehicle,
                        VehicleAccident, VehicleAssignment, VehicleReservation, WorkOrder, WorkOrderTechnician)
from app.schemas import (AccidentCreate, InspectionCreate, InspectionUpdate, VehicleCheckoutCreate,
                         VehicleReturnCreate, WorkOrderCreate)
from app.api.v1.endpoints import accidents, files, inspections, vehicle_assignments, work_orders
from app.services.inspection_templates import can_record_results

router = APIRouter()


def permitted(db, user, permission):
    if not has_permission(db, user, permission):
        raise HTTPException(403, detail="Insufficient permissions.")


def driver_for(db, user):
    return db.query(Driver).filter(Driver.user_id == user.id, Driver.archived.is_(False)).first()


def mobile_vehicles(db, user):
    """A mobile user sees only vehicles linked through actual assignments, never names."""
    driver = driver_for(db, user)
    role = active_role(db, user)
    query = db.query(Vehicle).filter(Vehicle.archived.is_(False))
    scope = authorization_scope(db, user, "vehicles.view")
    if not scope.unrestricted:
        if scope.location_ids:
            query = query.filter(Vehicle.location_id.in_(scope.location_ids))
        if scope.department_ids or scope.cost_center_ids:
            if not driver or (scope.department_ids and driver.department_id not in scope.department_ids) or (scope.cost_center_ids and driver.cost_center_id not in scope.cost_center_ids):
                return query.filter(False)
        if scope.own_records_only and role not in {"driver", "mechanic"}:
            return query.filter(False)
    if role == "driver":
        if not driver:
            return query.filter(False)
        return query.filter(or_(Vehicle.id == driver.assigned_vehicle_id, Vehicle.id.in_(
            db.query(VehicleAssignment.vehicle_id).filter(VehicleAssignment.driver_id == driver.id,
                VehicleAssignment.archived.is_(False), VehicleAssignment.status.in_(["Scheduled", "Active", "Overdue"])))))
    if role == "mechanic":
        return query.filter(Vehicle.id.in_(db.query(WorkOrder.vehicle_id).join(WorkOrderTechnician,
            WorkOrderTechnician.work_order_id == WorkOrder.id).join(Technician,
            Technician.id == WorkOrderTechnician.technician_id).filter(Technician.user_id == user.id,
            Technician.is_active.is_(True), Technician.archived.is_(False), WorkOrder.archived.is_(False))))
    return query


def vehicle_access(db, user, vehicle_id, permission="vehicles.view"):
    permitted(db, user, "vehicles.view")
    permitted(db, user, permission)
    vehicle = mobile_vehicles(db, user).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(403, detail="Vehicle is outside your mobile assignments.")
    scope = authorization_scope(db, user, permission)
    if not scope.unrestricted:
        if scope.location_ids and vehicle.location_id not in scope.location_ids:
            raise HTTPException(403, detail="Vehicle is outside this permission's location scope.")
        if scope.department_ids or scope.cost_center_ids:
            driver = driver_for(db, user)
            if not driver or (scope.department_ids and driver.department_id not in scope.department_ids) or (scope.cost_center_ids and driver.cost_center_id not in scope.cost_center_ids):
                raise HTTPException(403, detail="Vehicle is outside this permission's organizational scope.")
        if scope.own_records_only and active_role(db, user) not in {"driver", "mechanic"}:
            raise HTTPException(403, detail="Own-record scope requires a linked mobile profile.")
    return vehicle


class Operation(BaseModel):
    key: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9:-]+$")
    company_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    kind: Literal["prepare", "inspection", "accident"]
    inspection_id: int | None = None
    expected_updated_at: datetime | None = None
    payload: dict

    @model_validator(mode="after")
    def validate_domain_payload(self):
        schema = AccidentCreate if self.kind == "accident" else InspectionUpdate if self.kind == "inspection" else InspectionCreate
        schema.model_validate(self.payload)
        if self.kind == "inspection" and (not self.inspection_id or self.inspection_id <= 0 or self.expected_updated_at is None):
            raise ValueError("Inspection ID and version are required.")
        return self


def actor(db, user, company_id, user_id):
    if db.info.get("company_id") != company_id or user.id != user_id:
        raise HTTPException(409, detail={"code": "mobile_account_changed"})


def claim(db, user, key, payload):
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    query = db.query(MobileOperation).filter(MobileOperation.user_id == user.id, MobileOperation.operation_key == key)
    receipt = query.first()
    if receipt is None:
        receipt = MobileOperation(user_id=user.id, operation_key=key, payload_hash=digest)
        db.add(receipt)
        try:
            db.flush()  # Unique key serializes concurrent retries before any domain write or file upload.
        except IntegrityError:
            db.rollback()
            receipt = query.one()
    if receipt.payload_hash != digest:
        raise HTTPException(409, detail={"code": "mobile_retry_changed"})
    return receipt


@router.get("/home")
def home(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    permitted(db, user, "vehicles.view")
    vehicles = mobile_vehicles(db, user).all()
    ids = [v.id for v in vehicles]
    driver = driver_for(db, user)
    def visible_ids(permission):
        if not has_permission(db, user, permission):
            return []
        allowed = []
        for vehicle_id in ids:
            try:
                vehicle_access(db, user, vehicle_id, permission)
                allowed.append(vehicle_id)
            except HTTPException as exc:
                if exc.status_code != 403:
                    raise
        return allowed
    assignments = []
    if driver and has_permission(db, user, "assignments.view"):
        assignments = db.query(VehicleAssignment).filter(VehicleAssignment.driver_id == driver.id,
            VehicleAssignment.vehicle_id.in_(visible_ids("assignments.view")), VehicleAssignment.archived.is_(False),
            VehicleAssignment.status.in_(["Scheduled", "Active", "Overdue"])).all()
    reservations = []
    if has_permission(db, user, "reservations.view"):
        # reserved_by is free text, so only an assignment's FK proves ownership.
        reservations = db.query(VehicleReservation).filter(VehicleReservation.id.in_(
            [a.reservation_id for a in assignments if a.reservation_id]), VehicleReservation.vehicle_id.in_(visible_ids("reservations.view")), VehicleReservation.archived.is_(False)).all()
    orders = []
    if has_permission(db, user, "maintenance.view"):
        orders = db.query(WorkOrder).join(WorkOrderTechnician, WorkOrderTechnician.work_order_id == WorkOrder.id).join(
            Technician, Technician.id == WorkOrderTechnician.technician_id).filter(Technician.user_id == user.id,
            Technician.is_active.is_(True), Technician.archived.is_(False), WorkOrder.archived.is_(False),
            WorkOrder.vehicle_id.in_(visible_ids("maintenance.view")), WorkOrder.status.notin_(["Completed", "Cancelled"])).all()
    pending = []
    if has_permission(db, user, "inspections.view") and has_permission(db, user, "inspections.create"):
        candidates = db.query(Inspection).filter(Inspection.vehicle_id.in_(visible_ids("inspections.view")),
            Inspection.completed_at.is_(None), Inspection.archived.is_(False)).order_by(Inspection.inspection_date).limit(100).all()
        pending = [r for r in candidates if can_record_results(db, user, r)]
    return {"inspections": [{"id": r.id, "vehicle_id": r.vehicle_id, "inspection_type": r.inspection_type,
                            "inspection_date": r.inspection_date.strftime("%d-%m-%Y")} for r in pending], "vehicles": [{"id": v.id, "license_plate": v.license_plate, "name": f"{v.brand} {v.model}",
                "odometer_km": v.odometer_km} for v in vehicles],
            "driver_id": driver.id if driver else None,
            "assignments": [{"id": a.id, "vehicle_id": a.vehicle_id, "reservation_id": a.reservation_id, "status": a.status} for a in assignments],
            "reservations": [{"id": r.id, "vehicle_id": r.vehicle_id, "status": r.status} for r in reservations],
            "orders": [{"id": o.id, "title": o.title, "status": o.status, "priority": o.priority} for o in orders]}


def inspect_access(db, user, inspection_id):
    permitted(db, user, "inspections.view")
    permitted(db, user, "inspections.create")
    row = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not row or not can_record_results(db, user, row):
        raise HTTPException(403, detail="Inspection is outside your permissions.")
    vehicle_access(db, user, row.vehicle_id, "inspections.create")
    return row


@router.post("/sync")
def synchronize(operation: Operation, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    actor(db, user, operation.company_id, operation.user_id)
    data = operation.payload
    vehicle_access(db, user, data.get("vehicle_id"), "accidents.report" if operation.kind == "accident" else "inspections.create")
    driver = driver_for(db, user)
    if active_role(db, user) == "driver" and (not driver or data.get("driver_id") != driver.id):
        raise HTTPException(403, detail="Driver must match the signed-in account.")
    if operation.kind == "inspection":
        row = inspect_access(db, user, operation.inspection_id)
        if row.vehicle_id != data.get("vehicle_id") or row.driver_id != data.get("driver_id"):
            raise HTTPException(409, detail={"code": "mobile_conflict"})
    else:
        permitted(db, user, "inspections.create" if operation.kind == "prepare" else "accidents.report")
    receipt = claim(db, user, operation.key, operation.model_dump(mode="json"))
    if receipt.result is not None:
        return receipt.result
    try:
        if operation.kind == "prepare":
            payload = InspectionCreate.model_validate(data)
            # Downloading reserves a frozen server draft, never records results.
            payload.items = []; payload.complete = False; payload.archived = False; payload.overall_status = None
            result = inspections.create_inspection_transaction(payload, db, user, commit=False)
            # Legacy/default checklists also need immutable item identities and completion rules offline.
            prepared = db.get(Inspection, result.id)
            if prepared.template_snapshot is None:
                prepared.template_snapshot = {"code": "OFFLINE_DEFAULT", "name": "Vehicle inspection", "description": None, "offline_default": True}
                for index, item in enumerate(prepared.items):
                    item.item_snapshot = {"required": True, "category": "Other", "display_order": index}
                db.flush()
                result = inspections.inspection_out(prepared)
        elif operation.kind == "inspection":
            if operation.expected_updated_at is None:
                raise HTTPException(422, detail={"code": "mobile_version_required"})
            changed = db.execute(update(Inspection).where(Inspection.id == row.id,
                Inspection.updated_at == operation.expected_updated_at, Inspection.archived.is_(False),
                Inspection.completed_at.is_(None)).values(updated_at=datetime.utcnow()),
                execution_options={"synchronize_session": False}).rowcount
            if changed != 1:
                raise HTTPException(409, detail={"code": "mobile_conflict"})
            result = inspections.update_inspection_transaction(row.id, InspectionUpdate.model_validate(data), db, user, commit=False)
        else:
            payload = AccidentCreate.model_validate(data)
            # Offline reports cannot inject management transitions or financial values.
            payload.status = accidents.AccidentStatus.reported
            payload.estimated_damage_cost = payload.actual_damage_cost = None
            payload.fault_determination = None
            result = accidents.create_accident_transaction(payload, request, db, user, commit=False)
        receipt.result = result.model_dump(mode="json")
        db.commit()
        return receipt.result
    except ValidationError:
        db.rollback()
        raise HTTPException(422, detail={"code": "mobile_invalid_fields"})
    except Exception:
        db.rollback()
        raise


@router.get("/inspections/{inspection_id}")
def download_inspection(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    inspect_access(db, user, inspection_id)
    return inspections.get_inspection(inspection_id, db)


@router.post("/photos")
async def photo(key: str = Form(..., min_length=8, max_length=100), company_id: int = Form(...),
                user_id: int = Form(...), entity_type: Literal["Inspection", "VehicleAccident"] = Form(...),
                entity_id: int = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    actor(db, user, company_id, user_id)
    if entity_type == "Inspection":
        inspect_access(db, user, entity_id)
    else:
        permitted(db, user, "accidents.report")
        row = accidents.get_accident(db, entity_id)
        accidents.authorize_driver(db, user, row)
        vehicle_access(db, user, row.vehicle_id, "accidents.report")
    digest = hashlib.sha256(); size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > 8 * 1024 * 1024:
            raise HTTPException(413, detail={"code": "mobile_photo_size"})
        digest.update(chunk)
    await file.seek(0)
    receipt = claim(db, user, key, [entity_type, entity_id, digest.hexdigest()])
    if receipt.result is not None:
        return receipt.result
    try:
        result = await files.upload_file_transaction(entity_type, entity_id, "image", file, db, user, commit=False)
        receipt.result = result.model_dump(mode="json")
        db.commit()
        return receipt.result
    except Exception:
        db.rollback()
        raise


@router.post("/check-out")
def checkout(payload: VehicleCheckoutCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    permitted(db, user, "assignments.self_service")
    vehicle_access(db, user, payload.vehicle_id, "assignments.self_service")
    driver = driver_for(db, user)
    if not driver or payload.driver_id != driver.id:
        raise HTTPException(403, detail="Driver must match signed-in account.")
    return vehicle_assignments.checkout_vehicle(payload, db, user)


@router.post("/assignments/{assignment_id}/return")
def return_assignment(assignment_id: int, payload: VehicleReturnCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    permitted(db, user, "assignments.self_service")
    driver = driver_for(db, user)
    row = db.query(VehicleAssignment).filter(VehicleAssignment.id == assignment_id).first()
    if not row or not driver or row.driver_id != driver.id:
        raise HTTPException(403, detail="Assignment must belong to signed-in driver.")
    vehicle_access(db, user, row.vehicle_id, "assignments.self_service")
    return vehicle_assignments.return_vehicle(assignment_id, payload, db, user)


class Issue(BaseModel):
    vehicle_id: int
    description: str = Field(min_length=1, max_length=5000)


@router.post("/issues")
def report_issue(payload: Issue, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    permitted(db, user, "maintenance.report_issue")
    vehicle_access(db, user, payload.vehicle_id, "maintenance.report_issue")
    return work_orders.create_work_order(WorkOrderCreate(vehicle_id=payload.vehicle_id,
        title=payload.description[:150], reported_issue=payload.description, requested_by=user.full_name), db, user)
