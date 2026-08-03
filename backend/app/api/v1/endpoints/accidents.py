from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import (
    AccidentClaim,
    AccidentFile,
    AccidentInjury,
    AccidentParty,
    Attachment,
    AuditLog,
    Driver,
    User,
    Vehicle,
    VehicleAccident,
    VehicleAssignment,
    VehiclePaper,
    VehicleReservation,
    WorkOrder,
)
from app.schemas import (
    AccidentClaimPayload,
    AccidentCreate,
    AccidentInjuryPayload,
    AccidentOut,
    AccidentPartyPayload,
    AccidentStatus,
    AccidentUpdate,
    AccidentWorkOrderPayload,
    UserRole,
    WorkOrderStatus,
)
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles, resolve_by_prefix
from app.services.vehicle_assignments import active_assignment_at
from app.utils.dates import format_date, parse_date
from app.utils.domain import VehicleStatusEnum, find_vehicle_by_plate
from app.utils.files import file_url, store_upload

router = APIRouter(dependencies=[Depends(get_current_user)])
MANAGE_ROLES = (UserRole.admin, UserRole.fleet_manager)
CLAIM_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.finance)

STATUS_TRANSITIONS = {
    "Reported": {"Under Review", "Rejected"},
    "Under Review": {"Claim Opened", "Repair Approved", "Rejected"},
    "Claim Opened": {"Repair Approved", "Rejected"},
    "Repair Approved": {"Repair In Progress", "Resolved"},
    "Repair In Progress": {"Resolved"},
    "Resolved": {"Closed"},
    "Rejected": {"Closed"},
    "Closed": set(),
}


def parse_datetime(value: str, field: str) -> datetime:
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return parse_date(text, field)


def decimal_value(value) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def get_accident(db: Session, accident_id: int, *, include_archived: bool = False) -> VehicleAccident:
    query = db.query(VehicleAccident).options(
        joinedload(VehicleAccident.vehicle),
        joinedload(VehicleAccident.driver),
        joinedload(VehicleAccident.vehicle_assignment),
        joinedload(VehicleAccident.reservation),
        joinedload(VehicleAccident.claim).joinedload(AccidentClaim.insurance_document),
        joinedload(VehicleAccident.parties),
        joinedload(VehicleAccident.injuries),
        joinedload(VehicleAccident.work_orders).joinedload(WorkOrder.linked_service),
        joinedload(VehicleAccident.files),
    ).filter(VehicleAccident.id == accident_id)
    if not include_archived:
        query = query.filter(VehicleAccident.archived.is_(False))
    accident = query.first()
    if not accident:
        raise HTTPException(status_code=404, detail="Accident not found.")
    return accident


def authorize_driver(current_user: User, accident: VehicleAccident) -> None:
    if current_user.role == UserRole.driver.value:
        if not current_user.driver_profile or current_user.driver_profile.id != accident.driver_id:
            raise HTTPException(status_code=403, detail="Drivers can only access their own Accident records.")


def validate_links(
    db: Session,
    *,
    vehicle: Vehicle,
    driver_id: int,
    assignment_id: int | None,
    reservation_id: int | None,
) -> tuple[Driver, VehicleAssignment | None, VehicleReservation | None]:
    driver = db.get(Driver, driver_id)
    if not driver or driver.archived:
        raise HTTPException(status_code=404, detail="Driver not found.")
    assignment = db.get(VehicleAssignment, assignment_id) if assignment_id else None
    if assignment_id and (not assignment or assignment.archived):
        raise HTTPException(status_code=404, detail="Vehicle Assignment not found.")
    if assignment and (assignment.vehicle_id != vehicle.id or assignment.driver_id != driver.id):
        raise HTTPException(status_code=400, detail="Vehicle Assignment must match the Accident vehicle and driver.")
    reservation = db.get(VehicleReservation, reservation_id) if reservation_id else None
    if reservation_id and (not reservation or reservation.archived):
        raise HTTPException(status_code=404, detail="Reservation not found.")
    if reservation and reservation.vehicle_id != vehicle.id:
        raise HTTPException(status_code=400, detail="Reservation and Accident must belong to the same vehicle.")
    return driver, assignment, reservation


def apply_availability(accident: VehicleAccident) -> None:
    if not accident.vehicle_available_after_accident:
        accident.vehicle.status = VehicleStatusEnum.InService.value


def notify_accident(db: Session, accident: VehicleAccident, event: str, priority: str = "High") -> None:
    notify_roles(
        db,
        roles={"admin", "fleet_manager", "finance"} if "claim" in event.lower() else {"admin", "fleet_manager"},
        notification_type=event,
        title=f"{event}: Accident #{accident.id}",
        message=f"{accident.vehicle.license_plate} · {accident.location}",
        priority=priority,
        entity_type="VehicleAccident",
        entity_id=accident.id,
        deduplication_key=f"accident:{accident.id}:{event.lower().replace(' ', '-')}",
        message_params={"id": accident.id, "license_plate": accident.vehicle.license_plate},
    )


def accident_out(accident: VehicleAccident, request: Request) -> AccidentOut:
    return AccidentOut(
        id=accident.id,
        vehicle_id=accident.vehicle_id,
        driver_id=accident.driver_id,
        vehicle_assignment_id=accident.vehicle_assignment_id,
        reservation_id=accident.reservation_id,
        accident_date=format_date(accident.accident_date) or "",
        accident_datetime=accident.accident_date.isoformat(),
        location=accident.location,
        severity=accident.severity or "Minor",
        status=accident.status or "Reported",
        police_involved=accident.police_involved or False,
        police_report_number=accident.police_report_number,
        description=accident.description,
        vehicle_available_after_accident=accident.vehicle_available_after_accident,
        estimated_damage_cost=decimal_value(accident.estimated_damage_cost),
        actual_damage_cost=decimal_value(accident.actual_damage_cost),
        fault_determination=accident.fault_determination,
        license_plate=accident.vehicle.license_plate if accident.vehicle else None,
        brand=accident.vehicle.brand if accident.vehicle else None,
        model=accident.vehicle.model if accident.vehicle else None,
        driver_name=accident.driver.full_name if accident.driver else None,
        files=[file_url(row.file_path, request) or "" for row in accident.files],
        archived=accident.archived,
    )


def transition_status(accident: VehicleAccident, target: str) -> None:
    current = accident.status or AccidentStatus.reported.value
    if target not in STATUS_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=409, detail=f"Accident cannot transition from {current} to {target}.")
    accident.status = target
    now = datetime.utcnow()
    if target == AccidentStatus.resolved.value:
        accident.resolved_at = now
    if target == AccidentStatus.closed.value:
        accident.closed_at = now


@router.post("", response_model=AccidentOut, status_code=201)
def create_accident(
    payload: AccidentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    vehicle = db.get(Vehicle, payload.vehicle_id)
    if not vehicle or vehicle.archived:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    driver, assignment, reservation = validate_links(
        db, vehicle=vehicle, driver_id=payload.driver_id,
        assignment_id=payload.assignment_id, reservation_id=payload.reservation_id,
    )
    accident = VehicleAccident(
        vehicle_id=vehicle.id,
        driver_id=driver.id,
        vehicle_assignment_id=assignment.id if assignment else None,
        reservation_id=reservation.id if reservation else None,
        accident_date=parse_datetime(payload.accident_datetime, "accident_datetime"),
        location=payload.location.strip(),
        severity=payload.severity.value,
        status=payload.status.value,
        police_involved=payload.police_involved,
        police_report_number=payload.police_report_number,
        description=payload.description,
        vehicle_available_after_accident=payload.vehicle_available_after_accident,
        estimated_damage_cost=payload.estimated_damage_cost,
        actual_damage_cost=payload.actual_damage_cost,
        fault_determination=payload.fault_determination,
        vehicle=vehicle,
    )
    db.add(accident)
    apply_availability(accident)
    db.flush()
    record_audit(
        db, action="Accident reported", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values=snapshot(accident),
        description=f"Accident #{accident.id} reported for {vehicle.license_plate}.",
    )
    notify_accident(db, accident, "Accident reported", "Critical" if not accident.vehicle_available_after_accident else "High")
    db.commit()
    return accident_out(get_accident(db, accident.id), request)


@router.post("/report")
async def report_accident(
    license_plate: str = Form(...),
    accident_date: str = Form(...),
    location: str = Form(...),
    description: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    """Backward-compatible report endpoint used by the original Accident UI."""
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{license_plate}' not found.")
    occurred_at = parse_date(accident_date, "AccidentDate")
    assignment = active_assignment_at(db, vehicle_id=vehicle.id, occurred_at=occurred_at)
    accident = VehicleAccident(
        vehicle_id=vehicle.id,
        driver_id=assignment.driver_id if assignment else None,
        vehicle_assignment_id=assignment.id if assignment else None,
        reservation_id=assignment.reservation_id if assignment else None,
        accident_date=occurred_at,
        location=location,
        description=description,
        severity="Minor",
        status="Reported",
        vehicle_available_after_accident=True,
    )
    db.add(accident)
    db.flush()
    for uploaded in files or []:
        if uploaded.filename:
            stored = await store_upload(uploaded, "accidents", "image")
            attachment = Attachment(
                original_filename=stored.original_filename, stored_filename=stored.stored_filename,
                storage_path=stored.storage_path, mime_type=stored.mime_type, file_size=stored.file_size,
                uploaded_by=current_user.id, entity_type="VehicleAccident", entity_id=accident.id,
            )
            db.add(attachment)
            db.flush()
            db.add(AccidentFile(vehicle_accident_id=accident.id, file_path=f"/api/v1/files/{attachment.id}/download"))
    record_audit(
        db, action="Accident reported", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values=snapshot(accident),
        description=f"Accident #{accident.id} reported for {vehicle.license_plate}.",
    )
    notify_accident(db, accident, "Accident reported")
    db.commit()
    return {"message": "Accident reported successfully.", "id": accident.id}


@router.get("/all", response_model=list[AccidentOut])
def all_accidents(
    request: Request,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can include archived Accidents.")
    query = db.query(VehicleAccident).options(
        joinedload(VehicleAccident.vehicle), joinedload(VehicleAccident.driver), joinedload(VehicleAccident.files)
    )
    if not include_archived:
        query = query.filter(VehicleAccident.archived.is_(False))
    if current_user.role == UserRole.driver.value:
        if not current_user.driver_profile:
            return []
        query = query.filter(VehicleAccident.driver_id == current_user.driver_profile.id)
    return [accident_out(row, request) for row in query.order_by(VehicleAccident.accident_date.desc()).all()]


@router.get("/id/{accident_id}/detail")
def accident_detail(
    accident_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    accident = get_accident(db, accident_id, include_archived=current_user.role == UserRole.admin.value)
    authorize_driver(current_user, accident)
    generic_files = db.query(Attachment).filter(
        Attachment.entity_type == "VehicleAccident",
        Attachment.entity_id == accident.id,
        Attachment.archived.is_(False),
    ).order_by(Attachment.uploaded_at, Attachment.id).all()
    claim = accident.claim
    audits = db.query(AuditLog).filter(
        AuditLog.entity_type == "VehicleAccident", AuditLog.entity_id == accident.id
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).all()
    return {
        **accident_out(accident, request).model_dump(mode="json"),
        "assignment_id": accident.vehicle_assignment_id,
        "claim": {
            "id": claim.id,
            "insurance_company": claim.insurance_company,
            "policy_number": claim.policy_number,
            "claim_number": claim.claim_number,
            "claim_status": claim.claim_status,
            "claim_opened_date": claim.claim_opened_date.isoformat(),
            "claim_closed_date": claim.claim_closed_date.isoformat() if claim.claim_closed_date else None,
            "settlement_amount": str(claim.settlement_amount) if claim.settlement_amount is not None else None,
            "deductible": str(claim.deductible) if claim.deductible is not None else None,
            "adjuster_name": claim.adjuster_name,
            "notes": claim.notes,
            "insurance_document_id": claim.insurance_document_id,
            "insurance_document_type": claim.insurance_document.document_type if claim.insurance_document else None,
        } if claim else None,
        "parties": [snapshot(row) for row in accident.parties],
        "injuries": [snapshot(row) for row in accident.injuries],
        "work_orders": [{
            "id": row.id, "title": row.title, "status": row.status,
            "total_cost": str(row.total_cost) if row.total_cost is not None else None,
            "service": {
                "id": row.linked_service.id,
                "service_type": row.linked_service.service_type,
                "service_date": row.linked_service.service_date.isoformat(),
                "cost": str(row.linked_service.cost) if row.linked_service.cost is not None else None,
            } if row.linked_service else None,
        } for row in accident.work_orders],
        "attachments": [{
            "id": row.id,
            "original_filename": row.original_filename,
            "mime_type": row.mime_type,
            "file_size": row.file_size,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "uploaded_at": row.uploaded_at.isoformat(),
            "download_url": str(request.base_url).rstrip("/") + f"/api/v1/files/{row.id}/download",
        } for row in generic_files],
        "timeline": [{
            "id": row.id, "action": row.action, "description": row.description,
            "username": row.username, "created_at": row.created_at.isoformat(),
        } for row in audits],
        "resolved_at": accident.resolved_at.isoformat() if accident.resolved_at else None,
        "closed_at": accident.closed_at.isoformat() if accident.closed_at else None,
    }


@router.put("/id/{accident_id}")
def update_accident(
    accident_id: int,
    payload: AccidentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    accident = get_accident(db, accident_id)
    old = snapshot(accident)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if hasattr(value, "value"):
            value = value.value
        setattr(accident, key, value)
    if accident.police_report_number and not accident.police_involved:
        raise HTTPException(status_code=422, detail="police_involved must be true when a police report number is provided.")
    apply_availability(accident)
    if accident.estimated_damage_cost is not None and accident.status in {"Reported", "Under Review", "Claim Opened"}:
        accident.status = "Repair Approved"
    elif accident.status == "Reported":
        accident.status = "Under Review"
    record_audit(
        db, action="Accident updated", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, old_values=old, new_values=snapshot(accident),
        description=f"Accident #{accident.id} details updated.",
    )
    db.commit()
    return accident_out(get_accident(db, accident.id), request)


@router.post("/id/{accident_id}/transition/{target_status}")
def transition_accident(
    accident_id: int,
    target_status: AccidentStatus,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    accident = get_accident(db, accident_id)
    old_status = accident.status
    transition_status(accident, target_status.value)
    record_audit(
        db, action="Accident status changed", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, old_values={"status": old_status}, new_values={"status": accident.status},
        description=f"Accident #{accident.id} moved from {old_status} to {accident.status}.",
    )
    db.commit()
    return accident_out(get_accident(db, accident.id), request)


def validate_insurance_document(db: Session, accident: VehicleAccident, document_id: int | None) -> None:
    if document_id is None:
        return
    document = db.get(VehiclePaper, document_id)
    if not document or document.archived:
        raise HTTPException(status_code=404, detail="Insurance Document not found.")
    if document.vehicle_id != accident.vehicle_id or "insurance" not in document.document_type.lower():
        raise HTTPException(status_code=400, detail="Insurance Document must be an insurance record for the Accident vehicle.")


@router.post("/id/{accident_id}/claim")
def open_claim(
    accident_id: int,
    payload: AccidentClaimPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*CLAIM_ROLES)),
):
    accident = get_accident(db, accident_id)
    if accident.claim:
        raise HTTPException(status_code=409, detail="An Insurance Claim already exists for this Accident.")
    validate_insurance_document(db, accident, payload.insurance_document_id)
    claim = AccidentClaim(
        accident_id=accident.id,
        insurance_document_id=payload.insurance_document_id,
        insurance_company=payload.insurance_company.strip(),
        policy_number=payload.policy_number.strip(),
        claim_number=payload.claim_number.strip(),
        claim_status=getattr(payload.claim_status, "value", payload.claim_status),
        claim_opened_date=parse_datetime(payload.claim_opened_date, "claim_opened_date"),
        claim_closed_date=parse_datetime(payload.claim_closed_date, "claim_closed_date") if payload.claim_closed_date else None,
        settlement_amount=payload.settlement_amount,
        deductible=payload.deductible,
        adjuster_name=payload.adjuster_name,
        notes=payload.notes,
    )
    db.add(claim)
    if accident.status in {"Reported", "Under Review"}:
        accident.status = "Claim Opened"
    db.flush()
    record_audit(
        db, action="Insurance Claim opened", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values=snapshot(claim),
        description=f"Claim {claim.claim_number} opened for Accident #{accident.id}.",
    )
    notify_accident(db, accident, "Insurance claim opened")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Claim number must be unique.") from exc
    return {"message": "Insurance Claim opened.", "id": claim.id}


@router.put("/id/{accident_id}/claim")
def update_claim(
    accident_id: int,
    payload: AccidentClaimPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*CLAIM_ROLES)),
):
    accident = get_accident(db, accident_id)
    claim = accident.claim
    if not claim:
        raise HTTPException(status_code=404, detail="Insurance Claim not found.")
    validate_insurance_document(db, accident, payload.insurance_document_id)
    old = snapshot(claim)
    claim.insurance_document_id = payload.insurance_document_id
    claim.insurance_company = payload.insurance_company.strip()
    claim.policy_number = payload.policy_number.strip()
    claim.claim_number = payload.claim_number.strip()
    claim.claim_status = getattr(payload.claim_status, "value", payload.claim_status)
    claim.claim_opened_date = parse_datetime(payload.claim_opened_date, "claim_opened_date")
    claim.claim_closed_date = parse_datetime(payload.claim_closed_date, "claim_closed_date") if payload.claim_closed_date else None
    claim.settlement_amount = payload.settlement_amount
    claim.deductible = payload.deductible
    claim.adjuster_name = payload.adjuster_name
    claim.notes = payload.notes
    record_audit(
        db, action="Insurance Claim updated", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, old_values=old, new_values=snapshot(claim),
        description=f"Claim {claim.claim_number} updated.",
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Claim number must be unique.") from exc
    return {"message": "Insurance Claim updated.", "id": claim.id}


@router.post("/id/{accident_id}/actions/close-claim")
def close_claim(
    accident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*CLAIM_ROLES)),
):
    accident = get_accident(db, accident_id)
    if not accident.claim:
        raise HTTPException(status_code=409, detail="Open an Insurance Claim first.")
    if accident.claim.claim_status not in {"Settled", "Rejected", "Approved"}:
        raise HTTPException(status_code=409, detail="A Claim must be settled, rejected, or approved before it can be closed.")
    accident.claim.claim_status = "Closed"
    accident.claim.claim_closed_date = datetime.utcnow()
    record_audit(
        db, action="Insurance Claim closed", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values=snapshot(accident.claim),
        description=f"Claim {accident.claim.claim_number} closed.",
    )
    notify_accident(db, accident, "Insurance claim closed", "Medium")
    db.commit()
    return {"message": "Insurance Claim closed."}


@router.post("/id/{accident_id}/actions/mark-unavailable")
def mark_vehicle_unavailable(
    accident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    accident = get_accident(db, accident_id)
    accident.vehicle_available_after_accident = False
    accident.vehicle.status = VehicleStatusEnum.InService.value
    if accident.status == "Reported":
        accident.status = "Under Review"
    record_audit(
        db, action="Vehicle marked unavailable after Accident", entity_type="VehicleAccident",
        entity_id=accident.id, user=current_user,
        new_values={"vehicle_available_after_accident": False, "vehicle_status": "InService"},
        description=f"{accident.vehicle.license_plate} marked unavailable after Accident #{accident.id}.",
    )
    notify_accident(db, accident, "Vehicle unavailable after Accident", "Critical")
    db.commit()
    return {"message": "Vehicle marked unavailable."}


@router.post("/id/{accident_id}/actions/create-work-order")
def create_accident_work_order(
    accident_id: int,
    payload: AccidentWorkOrderPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.mechanic)),
):
    accident = get_accident(db, accident_id)
    if accident.estimated_damage_cost is None and payload.estimated_damage_cost is None:
        raise HTTPException(status_code=409, detail="Enter a Repair estimate before creating a Work Order.")
    if payload.estimated_damage_cost is not None:
        accident.estimated_damage_cost = payload.estimated_damage_cost
    duplicate = next((row for row in accident.work_orders if not row.archived and row.status != "Cancelled"), None)
    if duplicate:
        raise HTTPException(status_code=409, detail=f"Work Order #{duplicate.id} is already linked to this Accident.")
    order = WorkOrder(
        vehicle_id=accident.vehicle_id,
        driver_id=accident.driver_id,
        accident_id=accident.id,
        source="Accident",
        title=payload.title.strip(),
        description=payload.description or accident.description,
        reported_issue=accident.description or f"Damage from Accident #{accident.id}",
        priority=payload.priority.value,
        status=WorkOrderStatus.open.value,
        assigned_to=payload.assigned_to,
        workshop=payload.workshop,
        expected_completion_date=(
            parse_datetime(payload.expected_completion_date, "expected_completion_date")
            if payload.expected_completion_date else None
        ),
        created_by=current_user.full_name,
    )
    db.add(order)
    accident.status = "Repair In Progress"
    accident.vehicle_available_after_accident = False
    accident.vehicle.status = VehicleStatusEnum.InService.value
    db.flush()
    record_audit(
        db, action="Work Order created from Accident", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values={"work_order_id": order.id, "status": accident.status},
        description=f"Work Order #{order.id} created for Accident #{accident.id}.",
    )
    record_audit(
        db, action="Work Order created", entity_type="WorkOrder", entity_id=order.id,
        user=current_user, new_values=snapshot(order),
        description=f"Work Order #{order.id} created for Accident #{accident.id}.",
    )
    db.commit()
    return {"message": "Work Order created.", "id": order.id}


@router.post("/id/{accident_id}/actions/resolve")
def resolve_accident(
    accident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    accident = get_accident(db, accident_id)
    incomplete = [row.id for row in accident.work_orders if not row.archived and row.status not in {"Completed", "Cancelled"}]
    if incomplete:
        raise HTTPException(status_code=409, detail=f"Complete linked Work Orders first: {incomplete}.")
    if accident.claim and accident.claim.claim_status not in {"Closed", "Rejected"}:
        raise HTTPException(status_code=409, detail="Close or reject the Insurance Claim before resolving the Accident.")
    if accident.status not in {"Repair Approved", "Repair In Progress"}:
        raise HTTPException(status_code=409, detail="Accident must be in an active repair state before resolution.")
    if accident.actual_damage_cost is None and accident.work_orders:
        accident.actual_damage_cost = sum((row.total_cost or Decimal("0")) for row in accident.work_orders)
    accident.status = "Resolved"
    accident.resolved_at = datetime.utcnow()
    record_audit(
        db, action="Accident resolved", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values=snapshot(accident),
        description=f"Accident #{accident.id} resolved.",
    )
    resolve_by_prefix(db, f"accident:{accident.id}:")
    notify_accident(db, accident, "Accident resolved", "Medium")
    db.commit()
    return {"message": "Accident resolved."}


@router.post("/id/{accident_id}/actions/close")
def close_accident(
    accident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    accident = get_accident(db, accident_id)
    if accident.status not in {"Resolved", "Rejected"}:
        raise HTTPException(status_code=409, detail="Resolve or reject the Accident before closing it.")
    transition_status(accident, "Closed")
    record_audit(
        db, action="Accident closed", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values={"status": "Closed", "closed_at": accident.closed_at},
        description=f"Accident #{accident.id} closed.",
    )
    db.commit()
    return {"message": "Accident closed."}


@router.post("/id/{accident_id}/parties", status_code=201)
def add_party(
    accident_id: int,
    payload: AccidentPartyPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    accident = get_accident(db, accident_id)
    party = AccidentParty(accident_id=accident.id, **payload.model_dump())
    db.add(party)
    db.flush()
    record_audit(
        db, action="Accident Party added", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values=snapshot(party), description=f"A Party was added to Accident #{accident.id}.",
    )
    db.commit()
    return {"message": "Accident Party added.", "id": party.id}


@router.post("/id/{accident_id}/injuries", status_code=201)
def add_injury(
    accident_id: int,
    payload: AccidentInjuryPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    accident = get_accident(db, accident_id)
    if payload.party_id:
        party = db.get(AccidentParty, payload.party_id)
        if not party or party.accident_id != accident.id:
            raise HTTPException(status_code=400, detail="Injury Party must belong to this Accident.")
    injury = AccidentInjury(accident_id=accident.id, **payload.model_dump())
    db.add(injury)
    db.flush()
    record_audit(
        db, action="Accident Injury added", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values=snapshot(injury), description=f"An Injury was added to Accident #{accident.id}.",
    )
    db.commit()
    return {"message": "Accident Injury added.", "id": injury.id}


@router.delete("/id/{accident_id}")
def archive_accident(
    accident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    accident = get_accident(db, accident_id)
    accident.archived = True
    accident.archived_at = datetime.utcnow()
    accident.archived_by = current_user.id
    record_audit(
        db, action="Accident archived", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values={"archived": True}, description=f"Accident #{accident.id} archived.",
    )
    db.commit()
    return {"message": "Accident archived."}


@router.post("/id/{accident_id}/restore")
def restore_accident(
    accident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    accident = get_accident(db, accident_id, include_archived=True)
    accident.archived = False
    accident.archived_at = None
    accident.archived_by = None
    record_audit(
        db, action="Accident restored", entity_type="VehicleAccident", entity_id=accident.id,
        user=current_user, new_values={"archived": False}, description=f"Accident #{accident.id} restored.",
    )
    db.commit()
    return {"message": "Accident restored."}


@router.get("/{license_plate}", response_model=list[AccidentOut])
def accidents_by_plate(
    license_plate: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{license_plate}' not found.")
    query = db.query(VehicleAccident).options(
        joinedload(VehicleAccident.vehicle), joinedload(VehicleAccident.driver), joinedload(VehicleAccident.files)
    ).filter(VehicleAccident.vehicle_id == vehicle.id, VehicleAccident.archived.is_(False))
    if current_user.role == UserRole.driver.value:
        if not current_user.driver_profile:
            return []
        query = query.filter(VehicleAccident.driver_id == current_user.driver_profile.id)
    return [accident_out(row, request) for row in query.order_by(VehicleAccident.accident_date.desc()).all()]
