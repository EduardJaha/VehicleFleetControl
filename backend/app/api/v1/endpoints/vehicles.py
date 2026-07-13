from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models import Vehicle
from app.schemas import UserRole, VehicleCreate, VehicleOut, VehicleUpdate, UpdateLocation, UpdateStatus
from app.utils.domain import find_vehicle_by_plate, parse_vehicle_status, status_name

router = APIRouter(dependencies=[Depends(get_current_user)])


def vehicle_out(vehicle: Vehicle) -> VehicleOut:
    return VehicleOut(
        id=vehicle.id,
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
    )


@router.get("", response_model=list[VehicleOut])
def list_vehicles(status: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Vehicle)
    if status is not None and status != "":
        query = query.filter(Vehicle.status == parse_vehicle_status(status))
    return [vehicle_out(v) for v in query.order_by(Vehicle.id.desc()).all()]


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    vehicle = Vehicle(
        brand=payload.brand.strip(),
        model=payload.model.strip(),
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


@router.put("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: int, payload: VehicleUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    existing = find_vehicle_by_plate(db, payload.license_plate)
    if existing and existing.id != vehicle_id:
        raise HTTPException(status_code=409, detail=f"License plate '{payload.license_plate}' already exists.")

    vehicle.brand = payload.brand.strip()
    vehicle.model = payload.model.strip()
    vehicle.fuel_type = payload.fuel_type.strip()
    vehicle.vehicle_location = payload.vehicle_location.strip()
    vehicle.license_plate = payload.license_plate
    vehicle.year = payload.year
    vehicle.vin_number = payload.vin_number.strip() if payload.vin_number else None
    vehicle.engine_cc = payload.engine_cc
    vehicle.odometer_km = payload.odometer_km
    vehicle.status = parse_vehicle_status(payload.status)
    db.commit()
    db.refresh(vehicle)
    return vehicle_out(vehicle)


@router.put("/status/{license_plate}", response_model=VehicleOut)
def update_vehicle_status(license_plate: str, payload: UpdateStatus, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    vehicle.status = parse_vehicle_status(payload.status)
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
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    db.delete(vehicle)
    db.commit()
    return {"message": "Vehicle deleted."}
