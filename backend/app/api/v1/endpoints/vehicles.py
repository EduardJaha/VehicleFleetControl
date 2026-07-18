from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import User, Vehicle, VehicleBrand, VehicleModel
from app.schemas import UserRole, VehicleCreate, VehicleOut, VehicleUpdate, UpdateLocation, UpdateStatus
from app.schemas import MaintenanceTimelinePage, VehicleMaintenanceSummaryOut
from app.api.v1.endpoints.maintenance import vehicle_summary, vehicle_timeline
from app.utils.domain import find_vehicle_by_plate, parse_vehicle_status, status_name
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles

router = APIRouter(dependencies=[Depends(get_current_user)])


def vehicle_out(vehicle: Vehicle) -> VehicleOut:
    return VehicleOut(
        id=vehicle.id,
        brand_id=vehicle.brand_id,
        model_id=vehicle.model_id,
        brand=vehicle.brand,
        model=vehicle.model,
        fuel_type=vehicle.fuel_type,
        vehicle_location=vehicle.vehicle_location,
        license_plate=vehicle.license_plate,
        year=vehicle.year,
        vin_number=vehicle.vin_number,
        engine_cc=vehicle.engine_cc,
        odometer_km=vehicle.odometer_km,
        status=vehicle.status,
        status_name=status_name(vehicle.status),
        archived=vehicle.archived,
        archived_at=vehicle.archived_at.isoformat() if vehicle.archived_at else None,
        archived_by=vehicle.archived_by,
    )


def validate_catalog_selection(
    db: Session,
    brand_id: int,
    model_id: int,
    existing_vehicle: Vehicle | None = None,
) -> tuple[VehicleBrand, VehicleModel]:
    brand = db.get(VehicleBrand, brand_id)
    if not brand:
        raise HTTPException(status_code=422, detail="The selected vehicle brand does not exist.")
    model = db.get(VehicleModel, model_id)
    if not model:
        raise HTTPException(status_code=422, detail="The selected vehicle model does not exist.")
    if model.brand_id != brand.id:
        raise HTTPException(status_code=422, detail="The selected model does not belong to the selected brand.")

    unchanged_historical_selection = (
        existing_vehicle is not None
        and existing_vehicle.brand_id == brand.id
        and existing_vehicle.model_id == model.id
    )
    if (not brand.is_active or not model.is_active) and not unchanged_historical_selection:
        raise HTTPException(status_code=422, detail="Inactive vehicle brands and models cannot be selected.")
    return brand, model


@router.get("", response_model=list[VehicleOut])
def list_vehicles(
    status: str | None = None,
    search: str | None = None,
    brand_id: int | None = None,
    model_id: int | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Vehicle)
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can include archived Vehicles.")
    if not include_archived:
        query = query.filter(Vehicle.archived.is_(False))
    if status is not None and status != "":
        query = query.filter(Vehicle.status == parse_vehicle_status(status))
    if brand_id is not None:
        query = query.filter(Vehicle.brand_id == brand_id)
    if model_id is not None:
        query = query.filter(Vehicle.model_id == model_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(or_(
            Vehicle.license_plate.ilike(term),
            Vehicle.brand.ilike(term),
            Vehicle.model.ilike(term),
            Vehicle.vehicle_location.ilike(term),
            Vehicle.vin_number.ilike(term),
        ))
    return [vehicle_out(v) for v in query.order_by(Vehicle.id.desc()).all()]


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    brand, model = validate_catalog_selection(db, payload.brand_id, payload.model_id)
    vehicle = Vehicle(
        brand_id=brand.id,
        model_id=model.id,
        brand=brand.name,
        model=model.name,
        fuel_type=payload.fuel_type.strip(),
        vehicle_location=payload.vehicle_location.strip(),
        license_plate=payload.license_plate,
        year=payload.year,
        vin_number=payload.vin_number.strip() if payload.vin_number else None,
        engine_cc=payload.engine_cc,
        odometer_km=payload.odometer_km,
        status=parse_vehicle_status(payload.status),
    )
    db.add(vehicle)
    try:
        db.flush()
        record_audit(
            db, action="Vehicle created", entity_type="Vehicle", entity_id=vehicle.id,
            user=current_user, new_values=snapshot(vehicle),
            description=f"Vehicle {vehicle.license_plate} created.",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"License plate '{payload.license_plate}' already exists.") from exc
    db.refresh(vehicle)
    return vehicle_out(vehicle)


@router.get("/plate/{plate}", response_model=VehicleOut)
def get_vehicle_by_plate(plate: str, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{plate}' not found.")
    return vehicle_out(vehicle)


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle_out(vehicle)


@router.get("/{vehicle_id}/maintenance-summary", response_model=VehicleMaintenanceSummaryOut)
def get_vehicle_maintenance_summary(vehicle_id: int, db: Session = Depends(get_db)):
    return vehicle_summary(db, vehicle_id)


@router.get("/{vehicle_id}/maintenance-timeline", response_model=MaintenanceTimelinePage)
def get_vehicle_maintenance_timeline(vehicle_id: int, page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    return vehicle_timeline(db, vehicle_id, page, page_size)


@router.put("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: int, payload: VehicleUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    old_values = snapshot(vehicle)
    old_odometer = vehicle.odometer_km
    existing = find_vehicle_by_plate(db, payload.license_plate)
    if existing and existing.id != vehicle_id:
        raise HTTPException(status_code=409, detail=f"License plate '{payload.license_plate}' already exists.")

    brand, model = validate_catalog_selection(
        db,
        payload.brand_id,
        payload.model_id,
        existing_vehicle=vehicle,
    )
    selection_changed = vehicle.brand_id != brand.id or vehicle.model_id != model.id
    vehicle.brand_id = brand.id
    vehicle.model_id = model.id
    if selection_changed:
        vehicle.brand = brand.name
        vehicle.model = model.name
    vehicle.fuel_type = payload.fuel_type.strip()
    vehicle.vehicle_location = payload.vehicle_location.strip()
    vehicle.license_plate = payload.license_plate
    vehicle.year = payload.year
    vehicle.vin_number = payload.vin_number.strip() if payload.vin_number else None
    vehicle.engine_cc = payload.engine_cc
    vehicle.odometer_km = payload.odometer_km
    vehicle.status = parse_vehicle_status(payload.status)
    record_audit(
        db, action="Vehicle updated", entity_type="Vehicle", entity_id=vehicle.id,
        user=current_user, old_values=old_values, new_values=snapshot(vehicle),
        description=f"Vehicle {vehicle.license_plate} updated.",
    )
    if old_odometer != vehicle.odometer_km:
        record_audit(
            db, action="Vehicle odometer changed", entity_type="Vehicle", entity_id=vehicle.id,
            user=current_user, old_values={"odometer_km": old_odometer},
            new_values={"odometer_km": vehicle.odometer_km},
            description=f"Vehicle {vehicle.license_plate} odometer changed.",
        )
    db.commit()
    db.refresh(vehicle)
    return vehicle_out(vehicle)


@router.put("/status/{license_plate}", response_model=VehicleOut)
def update_vehicle_status(license_plate: str, payload: UpdateStatus, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    old_status = vehicle.status
    vehicle.status = parse_vehicle_status(payload.status)
    record_audit(
        db, action="Vehicle status changed", entity_type="Vehicle", entity_id=vehicle.id,
        user=current_user, old_values={"status": old_status}, new_values={"status": vehicle.status},
        description=f"Vehicle {vehicle.license_plate} status changed.",
    )
    notify_roles(
        db, roles={"admin", "fleet_manager"}, notification_type="Vehicle status changed",
        title=f"{vehicle.license_plate} status changed", message=status_name(vehicle.status),
        priority="Medium", entity_type="Vehicle", entity_id=vehicle.id,
        deduplication_key=f"vehicle:{vehicle.id}:status:{vehicle.status}",
    )
    db.commit()
    db.refresh(vehicle)
    return vehicle_out(vehicle)


@router.put("/location/{license_plate}", response_model=VehicleOut)
def update_vehicle_location(license_plate: str, payload: UpdateLocation, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    vehicle.vehicle_location = payload.new_location.strip()
    db.commit()
    db.refresh(vehicle)
    return vehicle_out(vehicle)


@router.delete("/{vehicle_id}")
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    vehicle.archived = True
    vehicle.archived_at = datetime.utcnow()
    vehicle.archived_by = current_user.id
    record_audit(
        db, action="Vehicle archived", entity_type="Vehicle", entity_id=vehicle.id,
        user=current_user, new_values={"archived": True},
        description=f"Vehicle {vehicle.license_plate} archived.",
    )
    db.commit()
    return {"message": "Vehicle archived."}


@router.post("/{vehicle_id}/restore", response_model=VehicleOut)
def restore_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    vehicle.archived = False
    vehicle.archived_at = None
    vehicle.archived_by = None
    record_audit(
        db, action="Vehicle restored", entity_type="Vehicle", entity_id=vehicle.id,
        user=current_user, new_values={"archived": False},
        description=f"Vehicle {vehicle.license_plate} restored.",
    )
    db.commit()
    return vehicle_out(vehicle)
