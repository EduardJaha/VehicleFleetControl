from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import Attachment, User, Vehicle, VehicleFuel
from app.schemas import (
    EnergyUnit,
    FuelFleetTotalsOut,
    FuelOverviewOut,
    FuelRecordOut,
    FuelUpdate,
    UserRole,
)
from app.services.audit import record_audit, snapshot
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, normalize_plate
from app.utils.files import store_upload

router = APIRouter(dependencies=[Depends(get_current_user)])
VALID_FUEL_TYPES = {"Petrol", "Diesel", "Hybrid", "Electric", "LPG", "CNG", "Gas"}
MONEY_QUANTUM = Decimal("0.01")
FUEL_AUDIT_FIELDS = (
    "id",
    "vehicle_id",
    "refuel_date",
    "fuel_type",
    "quantity",
    "unit",
    "unit_cost",
    "total_cost",
    "location",
    "station_name",
    "odometer_km",
    "archived",
    "unit_review_required",
)


def validate_fuel_type(value: str) -> str:
    for allowed in VALID_FUEL_TYPES:
        if value.strip().lower() == allowed.lower():
            return allowed
    raise HTTPException(
        status_code=400,
        detail=(
            f"Invalid Vehicle fuel type '{value}'. Allowed: "
            f"{', '.join(sorted(VALID_FUEL_TYPES))}"
        ),
    )


def energy_unit_for_fuel_type(fuel_type: str) -> EnergyUnit:
    return (
        EnergyUnit.kilowatt_hour
        if validate_fuel_type(fuel_type) == "Electric"
        else EnergyUnit.liter
    )


def calculate_total(quantity: Decimal, unit_cost: Decimal) -> Decimal:
    return (quantity * unit_cost).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def fuel_snapshot(record: VehicleFuel) -> dict:
    return snapshot(record, FUEL_AUDIT_FIELDS)


def quantity_error(unit: EnergyUnit) -> str:
    if unit == EnergyUnit.kilowatt_hour:
        return "Charging energy in kWh must be greater than zero."
    return "Fuel quantity in liters must be greater than zero."


def unit_cost_error(unit: EnergyUnit) -> str:
    if unit == EnergyUnit.kilowatt_hour:
        return "Cost per kWh cannot be negative."
    return "Cost per liter cannot be negative."


def fuel_record_out(record: VehicleFuel) -> FuelRecordOut:
    vehicle = record.vehicle
    return FuelRecordOut(
        id=record.id,
        vehicle_id=record.vehicle_id,
        license_plate=vehicle.license_plate,
        brand=vehicle.brand,
        model=vehicle.model,
        refuel_date=format_date(record.refuel_date) or "",
        fuel_type=record.fuel_type,
        quantity=record.quantity,
        unit=EnergyUnit(record.unit),
        unit_cost=record.unit_cost,
        total_cost=record.total_cost,
        location=record.location,
        station_name=record.station_name,
        bill_file_path=record.bill_file_path,
        odometer_km=record.odometer_km,
        archived=record.archived,
        unit_review_required=record.unit_review_required,
    )


def resolve_vehicle(
    db: Session,
    *,
    vehicle_id: int | None,
    license_plate: str | None,
) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id) if vehicle_id is not None else None
    plate_vehicle = (
        find_vehicle_by_plate(db, license_plate)
        if license_plate and license_plate.strip()
        else None
    )
    if vehicle_id is not None and vehicle is None:
        raise HTTPException(
            status_code=404,
            detail=f"No Vehicle was found with id {vehicle_id}.",
        )
    if vehicle is not None and plate_vehicle is not None and vehicle.id != plate_vehicle.id:
        raise HTTPException(
            status_code=400,
            detail="The submitted Vehicle id and licence plate do not identify the same Vehicle.",
        )
    vehicle = vehicle or plate_vehicle
    if vehicle is None:
        if license_plate and license_plate.strip():
            raise HTTPException(
                status_code=404,
                detail=f"No Vehicle was found with licence plate {license_plate.strip()}.",
            )
        raise HTTPException(status_code=422, detail="A valid Vehicle must be selected.")
    if vehicle.archived:
        raise HTTPException(
            status_code=400,
            detail="Fuel records cannot be added to an archived Vehicle.",
        )
    return vehicle


def sync_vehicle_odometer(vehicle: Vehicle, odometer_km: int | None) -> None:
    current = vehicle.odometer_km or 0
    if odometer_km is not None and odometer_km < current:
        raise HTTPException(
            status_code=400,
            detail=(
                "The Fuel Record odometer cannot be lower than the Vehicle's "
                f"current odometer of {current:,} km."
            ),
        )
    if odometer_km is not None:
        vehicle.odometer_km = odometer_km


def validate_compatibility_inputs(
    *,
    expected_fuel_type: str,
    expected_unit: EnergyUnit,
    submitted_fuel_type: str | None,
    submitted_unit: str | None,
) -> None:
    if (
        submitted_fuel_type
        and validate_fuel_type(submitted_fuel_type) != expected_fuel_type
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "The submitted Fuel Record type does not match the selected Vehicle. "
                f"The Vehicle is configured as {expected_fuel_type}."
            ),
        )
    if submitted_unit:
        try:
            unit = EnergyUnit(submitted_unit.upper())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Energy unit must be L or KWH.") from exc
        if unit != expected_unit:
            raise HTTPException(
                status_code=400,
                detail=(
                    "The submitted energy unit does not match the selected Vehicle. "
                    f"The required unit is {expected_unit.value}."
                ),
            )


@router.post("")
async def add_fuel_record(
    refuel_date: str = Form(...),
    vehicle_id: int | None = Form(None),
    license_plate: str | None = Form(None),
    quantity: Decimal | None = Form(None),
    unit_cost: Decimal | None = Form(None),
    location: str | None = Form(None),
    station_name: str | None = Form(None),
    odometer_km: int | None = Form(None),
    bill_file: UploadFile | None = File(None),
    # Deprecated multipart compatibility fields.
    fuel_type: str | None = Form(None),
    unit: str | None = Form(None),
    liters: Decimal | None = Form(None),
    cost_per_liter: Decimal | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.finance)),
):
    vehicle = resolve_vehicle(
        db,
        vehicle_id=vehicle_id,
        license_plate=license_plate,
    )
    authoritative_fuel_type = validate_fuel_type(vehicle.fuel_type)
    authoritative_unit = energy_unit_for_fuel_type(authoritative_fuel_type)
    validate_compatibility_inputs(
        expected_fuel_type=authoritative_fuel_type,
        expected_unit=authoritative_unit,
        submitted_fuel_type=fuel_type,
        submitted_unit=unit,
    )

    if quantity is not None and liters is not None:
        raise HTTPException(
            status_code=400,
            detail="Submit quantity only; do not submit both quantity and deprecated liters.",
        )
    if quantity is None:
        if liters is None:
            raise HTTPException(status_code=400, detail=quantity_error(authoritative_unit))
        if authoritative_unit == EnergyUnit.kilowatt_hour:
            raise HTTPException(
                status_code=400,
                detail="Electric Vehicle records must use quantity in kWh, not liters.",
            )
        quantity = liters

    if unit_cost is not None and cost_per_liter is not None:
        raise HTTPException(
            status_code=400,
            detail="Submit unit_cost only; do not submit both unit_cost and deprecated cost_per_liter.",
        )
    if unit_cost is None:
        if cost_per_liter is not None:
            if authoritative_unit == EnergyUnit.kilowatt_hour:
                raise HTTPException(
                    status_code=400,
                    detail="Electric Vehicle records must use unit_cost as Cost per kWh.",
                )
            unit_cost = cost_per_liter
        else:
            unit_cost = Decimal("0")

    if quantity <= 0:
        raise HTTPException(status_code=400, detail=quantity_error(authoritative_unit))
    if unit_cost < 0:
        raise HTTPException(status_code=400, detail=unit_cost_error(authoritative_unit))

    parsed_date = parse_date(refuel_date, "RefuelDate")
    sync_vehicle_odometer(vehicle, odometer_km)
    record = VehicleFuel(
        vehicle_id=vehicle.id,
        refuel_date=parsed_date,
        quantity=quantity,
        unit=authoritative_unit.value,
        unit_cost=unit_cost,
        total_cost=calculate_total(quantity, unit_cost),
        fuel_type=authoritative_fuel_type,
        unit_review_required=False,
        liters=None,
        cost_per_liter=None,
        location=(location.strip() if location else vehicle.vehicle_location or ""),
        station_name=(station_name.strip() if station_name else ""),
        bill_file_path=None,
        odometer_km=(
            odometer_km
            if odometer_km is not None
            else vehicle.odometer_km or 0
        ),
    )
    try:
        db.add(record)
        db.flush()
        if bill_file:
            stored = await store_upload(bill_file, "fuel-bills", "auto")
            attachment = Attachment(
                original_filename=stored.original_filename,
                stored_filename=stored.stored_filename,
                storage_path=stored.storage_path,
                mime_type=stored.mime_type,
                file_size=stored.file_size,
                uploaded_by=current_user.id,
                entity_type="VehicleFuel",
                entity_id=record.id,
            )
            db.add(attachment)
            db.flush()
            record.bill_file_path = f"/api/v1/files/{attachment.id}/download"
        record_audit(
            db,
            action="Fuel or charging record created",
            entity_type="VehicleFuel",
            entity_id=record.id,
            user=current_user,
            new_values=fuel_snapshot(record),
            description=(
                f"Fuel or charging record #{record.id} created for "
                f"{vehicle.license_plate}."
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(record)
    return {
        "message": f"Fuel or charging record added for {vehicle.license_plate}.",
        "record": fuel_record_out(record),
    }


@router.get("/record/{record_id}", response_model=FuelRecordOut)
def get_fuel_record(record_id: int, db: Session = Depends(get_db)):
    record = (
        db.query(VehicleFuel)
        .options(joinedload(VehicleFuel.vehicle))
        .filter(VehicleFuel.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Fuel record with id '{record_id}' was not found.",
        )
    return fuel_record_out(record)


@router.put("/{record_id}")
def update_fuel_record(
    record_id: int,
    payload: FuelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.finance)),
):
    record = (
        db.query(VehicleFuel)
        .options(joinedload(VehicleFuel.vehicle))
        .filter(VehicleFuel.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Fuel record with id '{record_id}' was not found.",
        )
    stored_unit = EnergyUnit(record.unit)
    validate_compatibility_inputs(
        expected_fuel_type=record.fuel_type,
        expected_unit=stored_unit,
        submitted_fuel_type=payload.fuel_type,
        submitted_unit=payload.unit.value if payload.unit else None,
    )
    if payload.quantity is not None and payload.liters is not None:
        raise HTTPException(
            status_code=400,
            detail="Submit quantity only; do not submit both quantity and deprecated liters.",
        )
    if payload.liters is not None and stored_unit == EnergyUnit.kilowatt_hour:
        raise HTTPException(
            status_code=400,
            detail="Electric Vehicle records must use quantity in kWh, not liters.",
        )
    quantity = payload.quantity if payload.quantity is not None else payload.liters
    if quantity is None or quantity <= 0:
        raise HTTPException(status_code=400, detail=quantity_error(stored_unit))

    if payload.unit_cost is not None and payload.cost_per_liter is not None:
        raise HTTPException(
            status_code=400,
            detail="Submit unit_cost only; do not submit both unit_cost and deprecated cost_per_liter.",
        )
    if payload.cost_per_liter is not None and stored_unit == EnergyUnit.kilowatt_hour:
        raise HTTPException(
            status_code=400,
            detail="Electric Vehicle records must use unit_cost as Cost per kWh.",
        )
    unit_cost = (
        payload.unit_cost
        if payload.unit_cost is not None
        else payload.cost_per_liter
        if payload.cost_per_liter is not None
        else Decimal(str(record.unit_cost or "0"))
    )
    if unit_cost < 0:
        raise HTTPException(status_code=400, detail=unit_cost_error(stored_unit))

    old_values = fuel_snapshot(record)
    record.refuel_date = parse_date(payload.refuel_date, "RefuelDate")
    record.quantity = quantity
    record.unit_cost = unit_cost
    record.total_cost = calculate_total(quantity, unit_cost)
    if payload.location is not None:
        record.location = payload.location.strip()
    if payload.station_name is not None:
        record.station_name = payload.station_name.strip()
    if payload.odometer_km is not None:
        if payload.odometer_km != record.odometer_km:
            sync_vehicle_odometer(record.vehicle, payload.odometer_km)
        record.odometer_km = payload.odometer_km
    record_audit(
        db,
        action="Fuel or charging record updated",
        entity_type="VehicleFuel",
        entity_id=record.id,
        user=current_user,
        old_values=old_values,
        new_values=fuel_snapshot(record),
        description=f"Fuel or charging record #{record.id} updated.",
    )
    db.commit()
    return {"message": "Fuel or charging record updated successfully."}


@router.get("/all", response_model=list[FuelRecordOut])
def all_fuel_records(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(
            status_code=403,
            detail="Only Admin users can include archived Fuel records.",
        )
    query = db.query(VehicleFuel).options(joinedload(VehicleFuel.vehicle))
    if not include_archived:
        query = query.filter(VehicleFuel.archived.is_(False))
    records = query.order_by(VehicleFuel.refuel_date.desc()).all()
    return [fuel_record_out(record) for record in records]


def filtered_fuel_query(
    db: Session,
    *,
    plate: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    fuel_type: str | None = None,
    location: str | None = None,
    station: str | None = None,
):
    query = (
        db.query(VehicleFuel)
        .options(joinedload(VehicleFuel.vehicle))
        .join(VehicleFuel.vehicle)
        .filter(VehicleFuel.archived.is_(False))
    )
    if plate:
        query = query.filter(
            Vehicle.license_plate_normalized.ilike(f"%{normalize_plate(plate)}%")
        )
    if fuel_type:
        query = query.filter(VehicleFuel.fuel_type == fuel_type)
    if location:
        query = query.filter(VehicleFuel.location == location)
    if station:
        query = query.filter(VehicleFuel.station_name.ilike(f"%{station}%"))
    if from_date:
        query = query.filter(
            VehicleFuel.refuel_date >= parse_date(from_date, "from")
        )
    if to_date:
        query = query.filter(
            VehicleFuel.refuel_date <= parse_date(to_date, "to")
        )
    return query


@router.get("/overview", response_model=list[FuelOverviewOut])
def overview(
    plate: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    fuel_type: str | None = None,
    location: str | None = None,
    station: str | None = None,
    db: Session = Depends(get_db),
):
    records = filtered_fuel_query(
        db,
        plate=plate,
        from_date=from_date,
        to_date=to_date,
        fuel_type=fuel_type,
        location=location,
        station=station,
    ).all()
    grouped = {}
    for record in records:
        key = (record.vehicle_id, record.fuel_type, record.unit)
        if key not in grouped:
            grouped[key] = {
                "vehicle_id": record.vehicle_id,
                "license_plate": record.vehicle.license_plate,
                "brand": record.vehicle.brand,
                "model": record.vehicle.model,
                "fuel_type": record.fuel_type,
                "unit": EnergyUnit(record.unit),
                "total_quantity": Decimal("0"),
                "total_cost": Decimal("0"),
                "record_count": 0,
            }
        grouped[key]["total_quantity"] += Decimal(str(record.quantity or "0"))
        grouped[key]["total_cost"] += Decimal(str(record.total_cost or "0"))
        grouped[key]["record_count"] += 1
    return [
        FuelOverviewOut(**values)
        for values in sorted(
            grouped.values(),
            key=lambda value: (value["license_plate"], value["unit"].value),
        )
    ]


@router.get("/overview/totals", response_model=FuelFleetTotalsOut)
def overview_totals(
    plate: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    fuel_type: str | None = None,
    location: str | None = None,
    station: str | None = None,
    db: Session = Depends(get_db),
):
    records = filtered_fuel_query(
        db,
        plate=plate,
        from_date=from_date,
        to_date=to_date,
        fuel_type=fuel_type,
        location=location,
        station=station,
    ).all()
    total_liters = Decimal("0")
    total_kwh = Decimal("0")
    total_cost = Decimal("0")
    for record in records:
        quantity = Decimal(str(record.quantity or "0"))
        if record.unit == EnergyUnit.kilowatt_hour.value:
            total_kwh += quantity
        else:
            total_liters += quantity
        total_cost += Decimal(str(record.total_cost or "0"))
    return FuelFleetTotalsOut(
        total_fuel_cost=total_cost,
        total_liters=total_liters,
        total_kwh=total_kwh,
        record_count=len(records),
    )


@router.get("/{license_plate}", response_model=list[FuelRecordOut])
def by_license_plate(license_plate: str, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(
            status_code=404,
            detail=f"No Vehicle was found with licence plate {license_plate}.",
        )
    records = (
        db.query(VehicleFuel)
        .options(joinedload(VehicleFuel.vehicle))
        .filter(
            VehicleFuel.vehicle_id == vehicle.id,
            VehicleFuel.archived.is_(False),
        )
        .order_by(VehicleFuel.refuel_date.desc())
        .all()
    )
    return [fuel_record_out(record) for record in records]


@router.delete("/{record_id}")
def delete_fuel_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.finance)),
):
    record = db.query(VehicleFuel).filter(VehicleFuel.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Fuel record with id '{record_id}' was not found.",
        )
    record.archived = True
    record.archived_at = datetime.utcnow()
    record.archived_by = current_user.id
    record_audit(
        db,
        action="Fuel or charging record archived",
        entity_type="VehicleFuel",
        entity_id=record.id,
        user=current_user,
        new_values={
            "archived": True,
            "fuel_type": record.fuel_type,
            "quantity": record.quantity,
            "unit": record.unit,
        },
        description=f"Fuel or charging record #{record.id} archived.",
    )
    db.commit()
    return {"message": "Fuel or charging record archived successfully."}


@router.post("/{record_id}/restore", response_model=FuelRecordOut)
def restore_fuel_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    record = (
        db.query(VehicleFuel)
        .options(joinedload(VehicleFuel.vehicle))
        .filter(VehicleFuel.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Fuel record not found.")
    record.archived = False
    record.archived_at = None
    record.archived_by = None
    record_audit(
        db,
        action="Fuel or charging record restored",
        entity_type="VehicleFuel",
        entity_id=record.id,
        user=current_user,
        new_values={
            "archived": False,
            "fuel_type": record.fuel_type,
            "quantity": record.quantity,
            "unit": record.unit,
        },
        description=f"Fuel or charging record #{record.id} restored.",
    )
    db.commit()
    return fuel_record_out(record)
