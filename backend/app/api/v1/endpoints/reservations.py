from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import User, VehicleReservation
from app.schemas import AddReservation, ReservationStatusUpdate, UserRole, VehicleReservationListOut
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, parse_reservation_status, reservation_status_name

router = APIRouter(dependencies=[Depends(get_current_user)])


def reservation_out(reservation: VehicleReservation) -> VehicleReservationListOut:
    return VehicleReservationListOut(
        id=reservation.id,
        license_plate=reservation.vehicle.license_plate,
        reserved_by=reservation.reserved_by,
        reservation_type=reservation.reservation_type,
        start_date=format_date(reservation.start_date) or "",
        end_date=format_date(reservation.end_date) or "",
        notes=reservation.notes or "",
        status=reservation.status,
        status_name=reservation_status_name(reservation.status),
    )


@router.post("")
def add_reservation(payload: AddReservation, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.driver))):
    vehicle = find_vehicle_by_plate(db, payload.license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{payload.license_plate}'.")
    start = parse_date(payload.start_date, "StartDate")
    end = parse_date(payload.end_date, "EndDate")
    if end < start:
        raise HTTPException(status_code=400, detail="EndDate must be on or after StartDate.")
    overlaps = (
        db.query(VehicleReservation)
        .filter(VehicleReservation.vehicle_id == vehicle.id)
        .filter(VehicleReservation.status != 3)
        .filter(start <= VehicleReservation.end_date, end >= VehicleReservation.start_date)
        .first()
    )
    if overlaps:
        raise HTTPException(status_code=409, detail="This vehicle is already reserved during the selected dates.")
    reservation = VehicleReservation(
        vehicle_id=vehicle.id,
        reserved_by=payload.reserved_by,
        reservation_type=payload.reservation_type,
        start_date=start,
        end_date=end,
        notes=payload.notes,
        status=0,
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return {"message": "Reservation created.", "id": reservation.id}


@router.get("", response_model=list[VehicleReservationListOut])
def all_reservations(db: Session = Depends(get_db)):
    reservations = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle)).order_by(VehicleReservation.start_date.desc()).all()
    return [reservation_out(r) for r in reservations]


@router.get("/by-plate/{license_plate}", response_model=list[VehicleReservationListOut])
def by_plate(license_plate: str, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    reservations = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle)).filter(VehicleReservation.vehicle_id == vehicle.id).order_by(VehicleReservation.start_date.desc()).all()
    return [reservation_out(r) for r in reservations]


@router.put("/{reservation_id}/status")
def update_status(reservation_id: int, payload: ReservationStatusUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    reservation.status = parse_reservation_status(payload.status)
    db.commit()
    return {"message": f"Status updated to {reservation_status_name(reservation.status)}."}


@router.put("/{reservation_id}/approve")
def approve(reservation_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    reservation.status = 1
    db.commit()
    return {"message": "Reservation approved."}


@router.put("/{reservation_id}/reject")
def reject(reservation_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    reservation.status = 2
    db.commit()
    return {"message": "Reservation rejected."}
