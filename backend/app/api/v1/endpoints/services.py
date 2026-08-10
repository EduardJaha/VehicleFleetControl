from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import Numeric, case, cast, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.authorization import has_permission, require_permission
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import Attachment, ServiceBill, User, Vehicle, VehicleService, WorkOrder
from app.schemas import (
    AddService,
    LinkedWorkOrder,
    ReminderPage,
    ReminderStatus,
    ReminderStatusUpdate,
    ServiceAttachment,
    ServicePage,
    ServiceReminderOut,
    ServiceSource,
    UserRole,
    VehicleServiceListOut,
    VehicleServiceOverviewOut,
    WorkOrderPriority,
    WorkOrderStatus,
)
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, normalize_plate
from app.utils.files import store_upload
from app.services.audit import record_audit, snapshot

router = APIRouter(dependencies=[Depends(require_permission("maintenance.view"))])

MILEAGE_TYPES = {"General Service", "Oil Change"}
DATE_TYPES = {"Tire Change/Control"}
VALID_KM_INTERVALS = {5000, 10000, 15000}
WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.mechanic)


def decimal_from_text(value) -> Decimal | None:
    return Decimal(str(value)) if value not in (None, "") else None


def total_cost(labor: Decimal | None, parts: Decimal | None, fallback: Decimal | None = None) -> Decimal | None:
    if labor is None and parts is None:
        return fallback
    return (labor or Decimal("0")) + (parts or Decimal("0"))


def build_reminder_values(
    service_type: str,
    service_date: datetime,
    next_service_date_text: str | None,
    odometer_km: int | None,
    next_service_km_interval: int | None,
):
    if service_type in MILEAGE_TYPES:
        if odometer_km is None:
            raise HTTPException(status_code=400, detail="OdometerKm is required for General Service and Oil Change.")
        if next_service_km_interval not in VALID_KM_INTERVALS:
            raise HTTPException(status_code=400, detail="NextServiceKmInterval must be 5000, 10000 or 15000.")
        return None, next_service_km_interval, odometer_km + next_service_km_interval
    if service_type in DATE_TYPES:
        if not next_service_date_text:
            raise HTTPException(status_code=400, detail="NextServiceDate is required for Tire Change/Control.")
        next_date = parse_date(next_service_date_text, "NextServiceDate")
        if next_date < service_date:
            raise HTTPException(status_code=400, detail="NextServiceDate must be after ServiceDate.")
        return next_date, None, None
    return None, None, None


def latest_bill_path(service: VehicleService) -> str | None:
    if not service.bills:
        return None
    return max(service.bills, key=lambda bill: bill.uploaded_at).file_path


def linked_work_order(work_order: WorkOrder | None) -> LinkedWorkOrder | None:
    if not work_order:
        return None
    return LinkedWorkOrder(
        id=work_order.id,
        title=work_order.title,
        status=WorkOrderStatus(work_order.status),
        priority=WorkOrderPriority(work_order.priority),
    )


def service_query(db: Session):
    return db.query(VehicleService).options(
        joinedload(VehicleService.vehicle),
        joinedload(VehicleService.bills),
        joinedload(VehicleService.work_order),
    )


def service_overview_out(service: VehicleService) -> VehicleServiceOverviewOut:
    labor = decimal_from_text(service.labor_cost)
    parts = decimal_from_text(service.parts_cost)
    actual = total_cost(labor, parts, decimal_from_text(service.cost))
    return VehicleServiceOverviewOut(
        id=service.id,
        vehicle_id=service.vehicle_id,
        license_plate=service.vehicle.license_plate,
        vehicle_name=f"{service.vehicle.brand} {service.vehicle.model}",
        service_type=service.service_type,
        service_date=format_date(service.service_date) or "",
        odometer_km=service.odometer_km,
        workshop=service.workshop,
        cost=actual,
        labor_cost=labor,
        parts_cost=parts,
        total_cost=actual,
        description=service.description,
        bill_file_path=latest_bill_path(service),
        next_service_date=format_date(service.next_service_date),
        next_service_km_interval=service.next_service_km_interval,
        next_service_odometer_km=service.next_service_odometer_km,
        source=ServiceSource(service.source or ServiceSource.manual.value),
        status=service.status or "Completed",
        archived=service.archived,
        linked_work_order=linked_work_order(service.work_order),
        reminder_status=current_reminder_status(service) if service.next_service_date or service.next_service_odometer_km else None,
    )


def service_list_out(service: VehicleService) -> VehicleServiceListOut:
    overview = service_overview_out(service)
    return VehicleServiceListOut(
        **overview.model_dump(),
        bills=[
            ServiceAttachment(id=bill.id, file_path=bill.file_path, uploaded_at=bill.uploaded_at.isoformat())
            for bill in sorted(service.bills, key=lambda row: row.uploaded_at, reverse=True)
        ],
    )


def resolve_work_order(db: Session, work_order_id: int | None, vehicle_id: int) -> WorkOrder | None:
    if work_order_id is None:
        return None
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work Order not found.")
    if work_order.vehicle_id != vehicle_id:
        raise HTTPException(status_code=400, detail="Work Order and Service must belong to the same vehicle.")
    already_linked = db.query(VehicleService).filter(
        VehicleService.work_order_id == work_order_id,
        VehicleService.archived.is_(False),
    ).first()
    if already_linked:
        raise HTTPException(status_code=409, detail=f"Work Order #{work_order_id} is already linked to Service #{already_linked.id}.")
    return work_order


def apply_service_payload(service: VehicleService, payload: AddService, db: Session, allow_current_id: int | None = None) -> Vehicle:
    vehicle = find_vehicle_by_plate(db, payload.license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{payload.license_plate}'.")
    work_order = None
    if payload.work_order_id is not None:
        work_order = db.get(WorkOrder, payload.work_order_id)
        if not work_order:
            raise HTTPException(status_code=404, detail="Work Order not found.")
        if work_order.vehicle_id != vehicle.id:
            raise HTTPException(status_code=400, detail="Work Order and Service must belong to the same vehicle.")
        duplicate = db.query(VehicleService).filter(
            VehicleService.work_order_id == payload.work_order_id,
            VehicleService.archived.is_(False),
        )
        if allow_current_id is not None:
            duplicate = duplicate.filter(VehicleService.id != allow_current_id)
        existing = duplicate.first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Work Order #{payload.work_order_id} is already linked to Service #{existing.id}.")

    service_date = parse_date(payload.service_date, "ServiceDate")
    next_date, next_interval, next_odo = build_reminder_values(
        payload.service_type, service_date, payload.next_service_date,
        payload.odometer_km, payload.next_service_km_interval,
    )
    actual = total_cost(payload.labor_cost, payload.parts_cost, payload.cost)
    service.vehicle_id = vehicle.id
    service.work_order_id = payload.work_order_id
    service.service_type = payload.service_type
    service.description = payload.description
    service.service_date = service_date
    service.odometer_km = payload.odometer_km
    service.cost = actual
    service.labor_cost = payload.labor_cost
    service.parts_cost = payload.parts_cost
    service.workshop = payload.workshop
    service.next_service_date = next_date
    service.next_service_km_interval = next_interval
    service.next_service_odometer_km = next_odo
    service.source = ServiceSource.work_order.value if payload.work_order_id else payload.source.value
    service.status = "Completed"
    service.updated_at = datetime.utcnow()
    if payload.odometer_km is not None:
        current_odometer = vehicle.odometer_km or 0
        if payload.odometer_km < current_odometer:
            raise HTTPException(
                status_code=400,
                detail=f"Service odometer cannot be lower than the vehicle's current odometer ({current_odometer} km).",
            )
        vehicle.odometer_km = payload.odometer_km
    if work_order and work_order.reminder_service:
        work_order.reminder_service.reminder_status = ReminderStatus.resolved.value
    return vehicle


@router.post("")
def add_service(payload: AddService, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    service = VehicleService(created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    apply_service_payload(service, payload, db)
    db.add(service)
    db.flush()
    record_audit(
        db, action="Service created", entity_type="VehicleService", entity_id=service.id,
        user=current_user, new_values=snapshot(service), description=f"Service #{service.id} created.",
    )
    db.commit()
    db.refresh(service)
    return {"message": "Service record created successfully.", "id": service.id}


@router.post("/register-with-bill")
async def register_with_bill(
    license_plate: str = Form(...), service_type: str = Form(...), description: str | None = Form(None),
    workshop: str | None = Form(None), odometer_km: int | None = Form(None), cost: Decimal | None = Form(None),
    labor_cost: Decimal | None = Form(None), parts_cost: Decimal | None = Form(None),
    service_date: str = Form(...), next_service_date: str | None = Form(None),
    next_service_km_interval: int | None = Form(None), work_order_id: int | None = Form(None),
    source: ServiceSource = Form(ServiceSource.manual), file: UploadFile = File(...),
    db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order")),
):
    payload = AddService(
        license_plate=license_plate, service_type=service_type, description=description, workshop=workshop,
        odometer_km=odometer_km, cost=cost, labor_cost=labor_cost, parts_cost=parts_cost,
        service_date=service_date, next_service_date=next_service_date,
        next_service_km_interval=next_service_km_interval, work_order_id=work_order_id, source=source,
    )
    service = VehicleService(created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    vehicle = apply_service_payload(service, payload, db)
    db.add(service)
    db.flush()
    stored = await store_upload(file, "bills", "auto")
    attachment = Attachment(
        original_filename=stored.original_filename, stored_filename=stored.stored_filename,
        storage_path=stored.storage_path, mime_type=stored.mime_type, file_size=stored.file_size,
        uploaded_by=current_user.id, entity_type="VehicleService", entity_id=service.id,
    )
    db.add(attachment)
    db.flush()
    service.bills.append(ServiceBill(file_path=f"/api/v1/files/{attachment.id}/download", uploaded_at=datetime.utcnow()))
    record_audit(
        db, action="Service created", entity_type="VehicleService", entity_id=service.id,
        user=current_user, new_values=snapshot(service),
        description=f"Service #{service.id} created with bill attachment #{attachment.id}.",
    )
    db.commit()
    db.refresh(service)
    return {
        "message": "Service and bill registered successfully.",
        "id": service.id,
        "license_plate": vehicle.license_plate,
        "bill_url": f"/api/v1/files/{attachment.id}/download",
    }


@router.post("/upload-bill-later")
async def upload_bill_later(
    license_plate: str = Form(...), service_type: str = Form(...), bill_file: UploadFile = File(...),
    db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order")),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    service = db.query(VehicleService).filter(
        VehicleService.vehicle_id == vehicle.id,
        VehicleService.service_type.ilike(service_type),
        VehicleService.archived.is_(False),
    ).order_by(VehicleService.service_date.desc(), VehicleService.id.desc()).first()
    if not service:
        raise HTTPException(status_code=404, detail=f"No service found for type '{service_type}' on '{license_plate}'.")
    stored = await store_upload(bill_file, "bills", "auto")
    attachment = Attachment(
        original_filename=stored.original_filename, stored_filename=stored.stored_filename,
        storage_path=stored.storage_path, mime_type=stored.mime_type, file_size=stored.file_size,
        uploaded_by=current_user.id, entity_type="VehicleService", entity_id=service.id,
    )
    db.add(attachment)
    db.flush()
    bill = ServiceBill(vehicle_service_id=service.id, file_path=f"/api/v1/files/{attachment.id}/download", uploaded_at=datetime.utcnow())
    db.add(bill)
    record_audit(
        db, action="Document uploaded", entity_type="VehicleService", entity_id=service.id,
        user=current_user, new_values={"attachment_id": attachment.id},
        description=f"Bill attached to Service #{service.id}.",
    )
    db.commit()
    db.refresh(bill)
    return {
        "message": f"Bill uploaded for '{service_type}' on '{license_plate}'.",
        "id": bill.id,
        "bill_url": f"/api/v1/files/{attachment.id}/download",
    }


def reminder_status_expression(today: datetime):
    due_soon = today + timedelta(days=30)
    return case(
        (VehicleService.reminder_status == ReminderStatus.resolved.value, ReminderStatus.resolved.value),
        (VehicleService.reminder_status == ReminderStatus.dismissed.value, ReminderStatus.dismissed.value),
        (or_(VehicleService.next_service_date < today, VehicleService.next_service_odometer_km < Vehicle.odometer_km), ReminderStatus.overdue.value),
        (or_(func.date(VehicleService.next_service_date) == today.date(), VehicleService.next_service_odometer_km == Vehicle.odometer_km), ReminderStatus.due.value),
        (or_(VehicleService.next_service_date <= due_soon, VehicleService.next_service_odometer_km - Vehicle.odometer_km <= 1000), ReminderStatus.due_soon.value),
        else_=ReminderStatus.upcoming.value,
    )


def reminder_priority(status: ReminderStatus) -> WorkOrderPriority:
    return {
        ReminderStatus.overdue: WorkOrderPriority.critical,
        ReminderStatus.due: WorkOrderPriority.high,
        ReminderStatus.due_soon: WorkOrderPriority.medium,
    }.get(status, WorkOrderPriority.low)


def current_reminder_status(service: VehicleService) -> ReminderStatus:
    if service.reminder_status in {ReminderStatus.resolved.value, ReminderStatus.dismissed.value}:
        return ReminderStatus(service.reminder_status)
    today = datetime.today().date()
    current_odometer = service.vehicle.odometer_km if service.vehicle else None
    if service.next_service_date:
        days_left = (service.next_service_date.date() - today).days
        if days_left < 0:
            return ReminderStatus.overdue
        if days_left == 0:
            return ReminderStatus.due
        if days_left <= 30:
            return ReminderStatus.due_soon
    if service.next_service_odometer_km is not None and current_odometer is not None:
        km_left = service.next_service_odometer_km - current_odometer
        if km_left < 0:
            return ReminderStatus.overdue
        if km_left == 0:
            return ReminderStatus.due
        if km_left <= 1000:
            return ReminderStatus.due_soon
    return ReminderStatus.upcoming


def reminder_out(service: VehicleService, status: ReminderStatus) -> ServiceReminderOut:
    today = datetime.today().date()
    current_odo = service.vehicle.odometer_km if service.vehicle else None
    km_left = service.next_service_odometer_km - current_odo if service.next_service_odometer_km is not None and current_odo is not None else None
    work_orders = sorted(
        (order for order in service.reminder_work_orders if not order.archived),
        key=lambda order: order.id,
        reverse=True,
    )
    return ServiceReminderOut(
        id=service.id,
        vehicle_id=service.vehicle_id,
        license_plate=service.vehicle.license_plate,
        vehicle_name=f"{service.vehicle.brand} {service.vehicle.model}",
        service_type=service.service_type,
        service_date=format_date(service.service_date) or "",
        reminder_mode="Kilometers" if service.next_service_odometer_km is not None else "Date",
        next_service_date=format_date(service.next_service_date),
        days_left=(service.next_service_date.date() - today).days if service.next_service_date else None,
        current_odometer_km=current_odo,
        next_service_odometer_km=service.next_service_odometer_km,
        next_service_km_interval=service.next_service_km_interval,
        km_left=km_left,
        status=status,
        priority=reminder_priority(status),
        linked_work_order=linked_work_order(work_orders[0] if work_orders else None),
    )


@router.get("/reminders", response_model=ReminderPage)
def reminders(
    page: int = 1, page_size: int = 20, search: str | None = None, vehicle_id: int | None = None,
    license_plate: str | None = None, reminder_type: str | None = None, status: ReminderStatus | None = None,
    priority: WorkOrderPriority | None = None, from_date: str | None = None, to_date: str | None = None,
    overdue_only: bool = False, has_linked_work_order: bool | None = None, db: Session = Depends(get_db),
):
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page must be at least 1 and page_size must be between 1 and 100.")
    ranked = db.query(
        VehicleService.id.label("service_id"),
        func.row_number().over(
            partition_by=(VehicleService.vehicle_id, VehicleService.service_type),
            order_by=(VehicleService.service_date.desc(), VehicleService.id.desc()),
        ).label("row_number"),
    ).filter(
        VehicleService.archived.is_(False),
        or_(VehicleService.next_service_date.isnot(None), VehicleService.next_service_odometer_km.isnot(None)),
    ).subquery()
    query = db.query(VehicleService).join(ranked, VehicleService.id == ranked.c.service_id).filter(ranked.c.row_number == 1).join(VehicleService.vehicle).options(
        joinedload(VehicleService.vehicle), joinedload(VehicleService.reminder_work_orders),
    )
    status_expr = reminder_status_expression(datetime.combine(datetime.today().date(), datetime.min.time()))
    if search:
        text = f"%{search.strip()}%"
        normalized_text = f"%{normalize_plate(search)}%"
        query = query.filter(or_(Vehicle.license_plate_normalized.ilike(normalized_text), VehicleService.service_type.ilike(text)))
    if vehicle_id is not None:
        query = query.filter(VehicleService.vehicle_id == vehicle_id)
    if license_plate:
        query = query.filter(Vehicle.license_plate_normalized.ilike(f"%{normalize_plate(license_plate)}%"))
    if reminder_type:
        query = query.filter(VehicleService.service_type == reminder_type)
    requested_status = ReminderStatus.overdue if overdue_only else status
    if requested_status:
        query = query.filter(status_expr == requested_status.value)
    if priority:
        statuses_for_priority = {
            WorkOrderPriority.critical: [ReminderStatus.overdue.value],
            WorkOrderPriority.high: [ReminderStatus.due.value],
            WorkOrderPriority.medium: [ReminderStatus.due_soon.value],
            WorkOrderPriority.low: [ReminderStatus.upcoming.value, ReminderStatus.resolved.value, ReminderStatus.dismissed.value],
        }[priority]
        query = query.filter(status_expr.in_(statuses_for_priority))
    if from_date:
        query = query.filter(VehicleService.next_service_date >= parse_date(from_date, "from_date"))
    if to_date:
        query = query.filter(VehicleService.next_service_date <= parse_date(to_date, "to_date"))
    if has_linked_work_order is True:
        query = query.filter(VehicleService.reminder_work_orders.any(WorkOrder.archived.is_(False)))
    elif has_linked_work_order is False:
        query = query.filter(~VehicleService.reminder_work_orders.any(WorkOrder.archived.is_(False)))
    total = query.order_by(None).count()
    rows = query.order_by(status_expr, VehicleService.next_service_date, VehicleService.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    items = [reminder_out(row, current_reminder_status(row)) for row in rows]
    return ReminderPage(items=items, page=page, page_size=page_size, total=total, pages=(total + page_size - 1) // page_size)


@router.put("/reminders/{service_id}/status", response_model=ServiceReminderOut)
def update_reminder_status(service_id: int, payload: ReminderStatusUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    if payload.status not in {ReminderStatus.resolved, ReminderStatus.dismissed}:
        raise HTTPException(status_code=400, detail="Reminders can only be manually Resolved or Dismissed.")
    service = db.query(VehicleService).options(joinedload(VehicleService.vehicle), joinedload(VehicleService.reminder_work_orders)).filter(VehicleService.id == service_id).first()
    if not service or (service.next_service_date is None and service.next_service_odometer_km is None):
        raise HTTPException(status_code=404, detail="Service Reminder not found.")
    service.reminder_status = payload.status.value
    service.updated_at = datetime.utcnow()
    record_audit(
        db,
        action="Reminder resolved" if payload.status == ReminderStatus.resolved else "Reminder dismissed",
        entity_type="VehicleService", entity_id=service.id, user=current_user,
        new_values={"reminder_status": payload.status.value},
        description=f"Service reminder #{service.id} marked {payload.status.value}.",
    )
    db.commit()
    return reminder_out(service, payload.status)


@router.get("/history", response_model=ServicePage)
def service_history(
    page: int = 1, page_size: int = 20, search: str | None = None, vehicle_id: int | None = None,
    license_plate: str | None = None, service_type: str | None = None, workshop: str | None = None,
    from_date: str | None = None, to_date: str | None = None, source: ServiceSource | None = None,
    has_linked_work_order: bool | None = None, minimum_cost: Decimal | None = None,
    maximum_cost: Decimal | None = None, include_archived: bool = False, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page must be at least 1 and page_size must be between 1 and 100.")
    if include_archived and not has_permission(db, current_user, "maintenance.assign_work_order"):
        raise HTTPException(status_code=403, detail="maintenance.assign_work_order is required to include archived Services.")
    query = service_query(db)
    if not include_archived:
        query = query.filter(VehicleService.archived.is_(False))
    if search or license_plate:
        query = query.join(VehicleService.vehicle)
    if search:
        text = f"%{search.strip()}%"
        normalized_text = f"%{normalize_plate(search)}%"
        query = query.filter(or_(Vehicle.license_plate_normalized.ilike(normalized_text), VehicleService.service_type.ilike(text), VehicleService.description.ilike(text), VehicleService.workshop.ilike(text)))
    if vehicle_id is not None:
        query = query.filter(VehicleService.vehicle_id == vehicle_id)
    if license_plate:
        query = query.filter(Vehicle.license_plate_normalized.ilike(f"%{normalize_plate(license_plate)}%"))
    if service_type:
        query = query.filter(VehicleService.service_type == service_type)
    if workshop:
        query = query.filter(VehicleService.workshop.ilike(f"%{workshop.strip()}%"))
    if from_date:
        query = query.filter(VehicleService.service_date >= parse_date(from_date, "from_date"))
    if to_date:
        query = query.filter(VehicleService.service_date <= parse_date(to_date, "to_date"))
    if source:
        query = query.filter(VehicleService.source == source.value)
    if has_linked_work_order is True:
        query = query.filter(VehicleService.work_order_id.isnot(None))
    elif has_linked_work_order is False:
        query = query.filter(VehicleService.work_order_id.is_(None))
    cost_value = cast(VehicleService.cost, Numeric(14, 2))
    if minimum_cost is not None:
        query = query.filter(cost_value >= minimum_cost)
    if maximum_cost is not None:
        query = query.filter(cost_value <= maximum_cost)
    total = query.order_by(None).count()
    rows = query.order_by(VehicleService.service_date.desc(), VehicleService.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ServicePage(items=[service_overview_out(row) for row in rows], page=page, page_size=page_size, total=total, pages=(total + page_size - 1) // page_size)


@router.get("/overview-filter", response_model=list[VehicleServiceOverviewOut])
def overview_filter(plate: str | None = None, type: str | None = None, workshop: str | None = None, from_date: str | None = None, to_date: str | None = None, db: Session = Depends(get_db)):
    query = service_query(db).filter(VehicleService.archived.is_(False))
    if plate:
        query = query.join(VehicleService.vehicle).filter(Vehicle.license_plate_normalized.ilike(f"%{normalize_plate(plate)}%"))
    if type:
        query = query.filter(VehicleService.service_type == type)
    if workshop:
        query = query.filter(VehicleService.workshop.ilike(f"%{workshop}%"))
    if from_date:
        query = query.filter(VehicleService.service_date >= parse_date(from_date, "from"))
    if to_date:
        query = query.filter(VehicleService.service_date <= parse_date(to_date, "to"))
    return [service_overview_out(row) for row in query.order_by(VehicleService.service_date.desc()).all()]


@router.get("/id/{service_id}", response_model=VehicleServiceListOut)
def get_service(service_id: int, db: Session = Depends(get_db)):
    service = service_query(db).filter(VehicleService.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found.")
    return service_list_out(service)


@router.put("/id/{service_id}", response_model=VehicleServiceOverviewOut)
def update_service(service_id: int, payload: AddService, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    service = service_query(db).filter(VehicleService.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found.")
    old_values = snapshot(service)
    apply_service_payload(service, payload, db, allow_current_id=service.id)
    record_audit(
        db, action="Service updated", entity_type="VehicleService", entity_id=service.id,
        user=current_user, old_values=old_values, new_values=snapshot(service),
        description=f"Service #{service.id} updated.",
    )
    db.commit()
    return service_overview_out(service)


@router.put("/id/{service_id}/archive", response_model=VehicleServiceOverviewOut)
def archive_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    service = service_query(db).filter(VehicleService.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found.")
    service.archived = True
    service.archived_at = datetime.utcnow()
    service.archived_by = current_user.id
    service.status = "Archived"
    service.updated_at = datetime.utcnow()
    record_audit(
        db, action="Service archived", entity_type="VehicleService", entity_id=service.id,
        user=current_user, new_values={"archived": True}, description=f"Service #{service.id} archived.",
    )
    db.commit()
    return service_overview_out(service)


@router.get("/{license_plate}", response_model=list[VehicleServiceListOut])
def get_by_license_plate(license_plate: str, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    services = service_query(db).filter(
        VehicleService.vehicle_id == vehicle.id,
        VehicleService.archived.is_(False),
    ).order_by(VehicleService.service_date.desc()).all()
    return [service_list_out(service) for service in services]


@router.delete("/{service_id}")
def delete_service(service_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("maintenance.assign_work_order"))):
    service = db.query(VehicleService).options(joinedload(VehicleService.bills)).filter(VehicleService.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail=f"Service with id '{service_id}' was not found.")
    service.archived = True
    service.archived_at = datetime.utcnow()
    service.archived_by = current_user.id
    service.status = "Archived"
    record_audit(
        db, action="Service archived", entity_type="VehicleService", entity_id=service.id,
        user=current_user, new_values={"archived": True}, description=f"Service #{service.id} archived.",
    )
    db.commit()
    return {"message": "Service archived successfully."}


@router.post("/id/{service_id}/restore", response_model=VehicleServiceOverviewOut)
def restore_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("maintenance.assign_work_order")),
):
    service = service_query(db).filter(VehicleService.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found.")
    service.archived = False
    service.archived_at = None
    service.archived_by = None
    service.status = "Completed"
    service.updated_at = datetime.utcnow()
    record_audit(
        db, action="Service restored", entity_type="VehicleService", entity_id=service.id,
        user=current_user, new_values={"archived": False}, description=f"Service #{service.id} restored.",
    )
    db.commit()
    return service_overview_out(service)
