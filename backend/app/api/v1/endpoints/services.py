from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import ServiceBill, User, Vehicle, VehicleService
from app.schemas import AddService, ServiceReminderOut, UserRole, VehicleServiceListOut, VehicleServiceOverviewOut
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, normalize_plate
from app.utils.files import delete_upload, save_upload

router = APIRouter(dependencies=[Depends(get_current_user)])

MILEAGE_TYPES = {"General Service", "Oil Change"}
DATE_TYPES = {"Tire Change/Control"}
VALID_KM_INTERVALS = {5000, 10000, 15000}


def build_reminder_values(service_type: str, service_date: datetime, next_service_date_text: str | None, odometer_km: int | None, next_service_km_interval: int | None):
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
    bill = sorted(service.bills, key=lambda b: b.uploaded_at, reverse=True)[0]
    return bill.file_path


def service_list_out(service: VehicleService) -> VehicleServiceListOut:
    return VehicleServiceListOut(
        id=service.id,
        service_type=service.service_type,
        service_date=format_date(service.service_date) or "",
        odometer_km=service.odometer_km,
        cost=service.cost,
        workshop=service.workshop,
        description=service.description,
        bill_file_path=latest_bill_path(service),
        next_service_date=format_date(service.next_service_date),
        next_service_km_interval=service.next_service_km_interval,
        next_service_odometer_km=service.next_service_odometer_km,
    )


def sync_vehicle_odometer(vehicle: Vehicle, odometer_km: int | None) -> None:
    if odometer_km is not None:
        vehicle.odometer_km = odometer_km


@router.post("")
def add_service(payload: AddService, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.mechanic))):
    vehicle = find_vehicle_by_plate(db, payload.license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{payload.license_plate}'.")
    service_date = parse_date(payload.service_date, "ServiceDate")
    next_date, next_interval, next_odo = build_reminder_values(payload.service_type, service_date, payload.next_service_date, payload.odometer_km, payload.next_service_km_interval)
    service = VehicleService(
        vehicle_id=vehicle.id,
        service_type=payload.service_type,
        description=payload.description,
        service_date=service_date,
        odometer_km=payload.odometer_km,
        cost=str(payload.cost) if payload.cost is not None else None,
        workshop=payload.workshop,
        next_service_date=next_date,
        next_service_km_interval=next_interval,
        next_service_odometer_km=next_odo,
    )
    sync_vehicle_odometer(vehicle, payload.odometer_km)
    db.add(service)
    db.commit()
    db.refresh(service)
    return {"message": "Service record created successfully.", "id": service.id}


@router.post("/register-with-bill")
async def register_with_bill(
    license_plate: str = Form(...),
    service_type: str = Form(...),
    description: str | None = Form(None),
    workshop: str | None = Form(None),
    odometer_km: int | None = Form(None),
    cost: Decimal | None = Form(None),
    service_date: str = Form(...),
    next_service_date: str | None = Form(None),
    next_service_km_interval: int | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.mechanic)),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    parsed_service_date = parse_date(service_date, "ServiceDate")
    next_date, next_interval, next_odo = build_reminder_values(service_type, parsed_service_date, next_service_date, odometer_km, next_service_km_interval)
    file_path = await save_upload(file, "bills")
    service = VehicleService(
        vehicle_id=vehicle.id,
        service_type=service_type,
        description=description,
        service_date=parsed_service_date,
        odometer_km=odometer_km,
        cost=str(cost) if cost is not None else None,
        workshop=workshop,
        next_service_date=next_date,
        next_service_km_interval=next_interval,
        next_service_odometer_km=next_odo,
    )
    sync_vehicle_odometer(vehicle, odometer_km)
    service.bills.append(ServiceBill(file_path=file_path, uploaded_at=datetime.utcnow()))
    db.add(service)
    db.commit()
    db.refresh(service)
    return {"message": "Service and bill registered successfully.", "id": service.id, "license_plate": vehicle.license_plate, "bill_url": f"/{file_path}"}


@router.post("/upload-bill-later")
async def upload_bill_later(
    license_plate: str = Form(...),
    service_type: str = Form(...),
    bill_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.mechanic)),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    service = (
        db.query(VehicleService)
        .filter(VehicleService.vehicle_id == vehicle.id)
        .filter(VehicleService.service_type.ilike(service_type))
        .order_by(VehicleService.service_date.desc(), VehicleService.id.desc())
        .first()
    )
    if not service:
        raise HTTPException(status_code=404, detail=f"No service found for type '{service_type}' on '{license_plate}'.")
    file_path = await save_upload(bill_file, "bills")
    bill = ServiceBill(vehicle_service_id=service.id, file_path=file_path, uploaded_at=datetime.utcnow())
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return {"message": f"Bill uploaded for '{service_type}' on '{license_plate}'.", "id": bill.id, "bill_url": f"/{file_path}"}


@router.get("/reminders", response_model=list[ServiceReminderOut])
def reminders(db: Session = Depends(get_db)):
    today = datetime.today().date()
    services = (
        db.query(VehicleService)
        .options(joinedload(VehicleService.vehicle))
        .filter(
            ((VehicleService.service_type.in_(MILEAGE_TYPES)) & (VehicleService.next_service_odometer_km.isnot(None)))
            | ((VehicleService.service_type.in_(DATE_TYPES)) & (VehicleService.next_service_date.isnot(None)))
        )
        .all()
    )
    latest: dict[tuple[int, str], VehicleService] = {}
    for service in services:
        key = (service.vehicle_id, service.service_type)
        current = latest.get(key)
        if current is None or (service.service_date, service.id) > (current.service_date, current.id):
            latest[key] = service

    result: list[ServiceReminderOut] = []
    for service in latest.values():
        if service.service_type in MILEAGE_TYPES:
            current_odo = service.vehicle.odometer_km if service.vehicle else None
            km_left = service.next_service_odometer_km - current_odo if current_odo is not None and service.next_service_odometer_km is not None else None
            result.append(ServiceReminderOut(
                license_plate=service.vehicle.license_plate if service.vehicle else "",
                service_type=service.service_type,
                service_date=format_date(service.service_date) or "",
                reminder_mode="Kilometers",
                current_odometer_km=current_odo,
                next_service_odometer_km=service.next_service_odometer_km,
                next_service_km_interval=service.next_service_km_interval,
                km_left=km_left,
            ))
        else:
            result.append(ServiceReminderOut(
                license_plate=service.vehicle.license_plate if service.vehicle else "",
                service_type=service.service_type,
                service_date=format_date(service.service_date) or "",
                reminder_mode="Date",
                next_service_date=format_date(service.next_service_date),
                days_left=(service.next_service_date.date() - today).days if service.next_service_date else None,
            ))
    return sorted(result, key=lambda r: r.km_left if r.reminder_mode == "Kilometers" and r.km_left is not None else r.days_left if r.days_left is not None else 999999)


@router.get("/overview-filter", response_model=list[VehicleServiceOverviewOut])
def overview_filter(plate: str | None = None, type: str | None = None, workshop: str | None = None, from_date: str | None = None, to_date: str | None = None, db: Session = Depends(get_db)):
    query = db.query(VehicleService).options(joinedload(VehicleService.vehicle), joinedload(VehicleService.bills))
    if plate:
        norm = normalize_plate(plate)
        query = query.join(VehicleService.vehicle).filter(Vehicle.license_plate.ilike(f"%{norm}%"))
    if type:
        query = query.filter(VehicleService.service_type == type)
    if workshop:
        query = query.filter(VehicleService.workshop.ilike(f"%{workshop}%"))
    if from_date:
        query = query.filter(VehicleService.service_date >= parse_date(from_date, "from"))
    if to_date:
        query = query.filter(VehicleService.service_date <= parse_date(to_date, "to"))
    rows = query.order_by(VehicleService.service_date.desc()).all()
    return [
        VehicleServiceOverviewOut(
            id=s.id,
            license_plate=s.vehicle.license_plate,
            service_type=s.service_type,
            service_date=format_date(s.service_date) or "",
            odometer_km=s.odometer_km,
            workshop=s.workshop,
            cost=s.cost,
            description=s.description,
            bill_file_path=latest_bill_path(s),
            next_service_date=format_date(s.next_service_date),
            next_service_km_interval=s.next_service_km_interval,
            next_service_odometer_km=s.next_service_odometer_km,
        )
        for s in rows
    ]


@router.get("/{license_plate}", response_model=list[VehicleServiceListOut])
def get_by_license_plate(license_plate: str, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    services = (
        db.query(VehicleService)
        .options(joinedload(VehicleService.bills))
        .filter(VehicleService.vehicle_id == vehicle.id)
        .order_by(VehicleService.service_date.desc())
        .all()
    )
    return [service_list_out(s) for s in services]


@router.delete("/{service_id}")
def delete_service(service_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.mechanic))):
    service = db.query(VehicleService).options(joinedload(VehicleService.bills)).filter(VehicleService.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail=f"Service with id '{service_id}' was not found.")
    for bill in service.bills:
        delete_upload(bill.file_path)
    db.delete(service)
    db.commit()
    return {"message": "Service deleted successfully."}
