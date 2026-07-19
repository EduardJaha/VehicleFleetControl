from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Attachment, User, Vehicle, VehicleFuel
from app.schemas import FuelOverviewOut, FuelRecordOut, FuelUpdate, UserRole
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, normalize_plate
from app.utils.files import store_upload
from app.services.audit import record_audit, snapshot

router = APIRouter(dependencies=[Depends(get_current_user)])
VALID_FUEL_TYPES = {"Petrol", "Diesel", "Hybrid", "Electric", "LPG", "CNG", "Gas"}


def validate_fuel_type(value: str) -> str:
    for allowed in VALID_FUEL_TYPES:
        if value.lower() == allowed.lower():
            return allowed
    raise HTTPException(status_code=400, detail=f"Invalid fuel type '{value}'. Allowed: {', '.join(sorted(VALID_FUEL_TYPES))}")


def fuel_record_out(record: VehicleFuel) -> FuelRecordOut:
    vehicle = record.vehicle
    return FuelRecordOut(
        id=record.id,
        license_plate=vehicle.license_plate,
        brand=vehicle.brand,
        model=vehicle.model,
        refuel_date=format_date(record.refuel_date) or "",
        fuel_type=record.fuel_type,
        liters=record.liters,
        cost_per_liter=record.cost_per_liter,
        total_cost=record.total_cost,
        location=record.location,
        station_name=record.station_name,
        bill_file_path=record.bill_file_path,
        odometer_km=record.odometer_km,
        archived=record.archived,
    )


def sync_vehicle_odometer(vehicle: Vehicle, odometer_km: int | None) -> None:
    if odometer_km is not None and odometer_km < (vehicle.odometer_km or 0):
        raise HTTPException(
            status_code=400,
            detail=f"Fuel odometer cannot be lower than the vehicle's current odometer ({vehicle.odometer_km or 0} km).",
        )
    if odometer_km is not None:
        vehicle.odometer_km = odometer_km


@router.post("")
async def add_fuel_record(
    license_plate: str = Form(...),
    refuel_date: str = Form(...),
    fuel_type: str = Form(...),
    liters: Decimal = Form(...),
    cost_per_liter: Decimal | None = Form(None),
    location: str | None = Form(None),
    station_name: str | None = Form(None),
    odometer_km: int | None = Form(None),
    bill_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.finance)),
):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    if liters <= 0:
        raise HTTPException(status_code=400, detail="Liters must be greater than 0.")
    unit_cost = cost_per_liter if cost_per_liter is not None else Decimal("0")
    if unit_cost < 0:
        raise HTTPException(status_code=400, detail="Cost per liter cannot be negative.")
    parsed_date = parse_date(refuel_date, "RefuelDate")
    record = VehicleFuel(
        vehicle_id=vehicle.id,
        refuel_date=parsed_date,
        liters=liters,
        cost_per_liter=unit_cost,
        total_cost=liters * unit_cost,
        fuel_type=validate_fuel_type(fuel_type),
        location=(location.strip() if location else vehicle.vehicle_location or ""),
        station_name=(station_name.strip() if station_name else ""),
        bill_file_path=None,
        odometer_km=odometer_km if odometer_km is not None else vehicle.odometer_km or 0,
    )
    sync_vehicle_odometer(vehicle, odometer_km)
    db.add(record)
    db.flush()
    if bill_file:
        stored = await store_upload(bill_file, "fuel-bills", "auto")
        attachment = Attachment(
            original_filename=stored.original_filename, stored_filename=stored.stored_filename,
            storage_path=stored.storage_path, mime_type=stored.mime_type, file_size=stored.file_size,
            uploaded_by=current_user.id, entity_type="VehicleFuel", entity_id=record.id,
        )
        db.add(attachment)
        db.flush()
        record.bill_file_path = f"/api/v1/files/{attachment.id}/download"
    record_audit(
        db, action="Fuel record created", entity_type="VehicleFuel", entity_id=record.id,
        user=current_user, new_values=snapshot(record),
        description=f"Fuel record #{record.id} created for {vehicle.license_plate}.",
    )
    db.commit()
    db.refresh(record)
    return {"message": f"Fuel record added for {vehicle.license_plate}.", "record": fuel_record_out(record)}


@router.get("/record/{record_id}", response_model=FuelRecordOut)
def get_fuel_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle)).filter(VehicleFuel.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Fuel record with id '{record_id}' was not found.")
    return fuel_record_out(record)


@router.put("/{record_id}")
def update_fuel_record(record_id: int, payload: FuelUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.finance))):
    record = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle)).filter(VehicleFuel.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Fuel record with id '{record_id}' was not found.")
    old_values = snapshot(record)
    if payload.liters <= 0:
        raise HTTPException(status_code=400, detail="Liters must be greater than 0.")
    unit_cost = payload.cost_per_liter if payload.cost_per_liter is not None else Decimal(str(record.cost_per_liter or "0"))
    if unit_cost < 0:
        raise HTTPException(status_code=400, detail="Cost per liter cannot be negative.")
    record.refuel_date = parse_date(payload.refuel_date, "RefuelDate")
    record.fuel_type = validate_fuel_type(payload.fuel_type)
    record.liters = payload.liters
    record.cost_per_liter = unit_cost
    record.total_cost = payload.liters * unit_cost
    if payload.location is not None:
        record.location = payload.location.strip()
    if payload.station_name is not None:
        record.station_name = payload.station_name.strip()
    if payload.odometer_km is not None:
        record.odometer_km = payload.odometer_km
        sync_vehicle_odometer(record.vehicle, payload.odometer_km)
    record_audit(
        db, action="Fuel record updated", entity_type="VehicleFuel", entity_id=record.id,
        user=current_user, old_values=old_values, new_values=snapshot(record),
        description=f"Fuel record #{record.id} updated.",
    )
    db.commit()
    return {"message": "Fuel record updated successfully."}


@router.get("/all", response_model=list[FuelRecordOut])
def all_fuel_records(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can include archived Fuel records.")
    query = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle))
    if not include_archived:
        query = query.filter(VehicleFuel.archived.is_(False))
    records = query.order_by(VehicleFuel.refuel_date.desc()).all()
    return [fuel_record_out(r) for r in records]


@router.get("/overview", response_model=list[FuelOverviewOut])
def overview(plate: str | None = None, from_date: str | None = None, to_date: str | None = None, fuel_type: str | None = None, location: str | None = None, station: str | None = None, db: Session = Depends(get_db)):
    query = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle)).join(VehicleFuel.vehicle).filter(VehicleFuel.archived.is_(False))
    if plate:
        query = query.filter(Vehicle.license_plate_normalized.ilike(f"%{normalize_plate(plate)}%"))
    if fuel_type:
        query = query.filter(VehicleFuel.fuel_type == fuel_type)
    if location:
        query = query.filter(VehicleFuel.location == location)
    if station:
        query = query.filter(VehicleFuel.station_name.ilike(f"%{station}%"))
    if from_date:
        query = query.filter(VehicleFuel.refuel_date >= parse_date(from_date, "from"))
    if to_date:
        query = query.filter(VehicleFuel.refuel_date <= parse_date(to_date, "to"))
    records = query.all()
    grouped = {}
    for r in records:
        key = r.vehicle_id
        if key not in grouped:
            grouped[key] = {
                "license_plate": r.vehicle.license_plate,
                "brand": r.vehicle.brand,
                "model": r.vehicle.model,
                "total_liters": Decimal("0"),
                "total_cost": Decimal("0"),
                "refuel_count": 0,
            }
        grouped[key]["total_liters"] += Decimal(str(r.liters or "0"))
        grouped[key]["total_cost"] += Decimal(str(r.total_cost or "0"))
        grouped[key]["refuel_count"] += 1
    return [FuelOverviewOut(**v) for v in sorted(grouped.values(), key=lambda x: x["license_plate"])]


@router.get("/{license_plate}", response_model=list[FuelRecordOut])
def by_license_plate(license_plate: str, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{license_plate}'.")
    records = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle)).filter(VehicleFuel.vehicle_id == vehicle.id, VehicleFuel.archived.is_(False)).order_by(VehicleFuel.refuel_date.desc()).all()
    return [fuel_record_out(r) for r in records]


@router.delete("/{record_id}")
def delete_fuel_record(record_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.finance))):
    record = db.query(VehicleFuel).filter(VehicleFuel.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Fuel record with id '{record_id}' was not found.")
    record.archived = True
    record.archived_at = datetime.utcnow()
    record.archived_by = current_user.id
    record_audit(
        db, action="Fuel record archived", entity_type="VehicleFuel", entity_id=record.id,
        user=current_user, new_values={"archived": True},
        description=f"Fuel record #{record.id} archived.",
    )
    db.commit()
    return {"message": "Fuel record archived successfully."}


@router.post("/{record_id}/restore", response_model=FuelRecordOut)
def restore_fuel_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    record = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle)).filter(VehicleFuel.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fuel record not found.")
    record.archived = False
    record.archived_at = None
    record.archived_by = None
    record_audit(
        db, action="Fuel record restored", entity_type="VehicleFuel", entity_id=record.id,
        user=current_user, new_values={"archived": False},
        description=f"Fuel record #{record.id} restored.",
    )
    db.commit()
    return fuel_record_out(record)
