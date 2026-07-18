from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.models import User, VehicleReservation
from app.schemas import AddReservation, ReservationStatusUpdate, UserRole, VehicleReservationListOut
from app.utils.dates import format_date, parse_date
from app.utils.domain import find_vehicle_by_plate, parse_reservation_status, reservation_status_name
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles

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
        archived=reservation.archived,
    )


@router.post("")
def add_reservation(payload: AddReservation, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager, UserRole.driver))):
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
        .filter(VehicleReservation.archived.is_(False))
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
    db.flush()
    record_audit(
        db, action="Reservation created", entity_type="VehicleReservation", entity_id=reservation.id,
        user=current_user, new_values=snapshot(reservation),
        description=f"Reservation #{reservation.id} created.",
    )
    notify_roles(
        db, roles={"admin", "fleet_manager"}, notification_type="Reservation pending approval",
        title=f"Reservation #{reservation.id} awaits approval",
        message=f"{vehicle.license_plate} for {reservation.reserved_by}",
        priority="Medium", entity_type="VehicleReservation", entity_id=reservation.id,
        deduplication_key=f"reservation:{reservation.id}:pending",
    )
    db.commit()
    db.refresh(reservation)
    return {"message": "Reservation created.", "id": reservation.id}


@router.get("", response_model=list[VehicleReservationListOut])
def all_reservations(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if include_archived and current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Only Admin users can include archived Reservations.")
    query = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle))
    if not include_archived:
        query = query.filter(VehicleReservation.archived.is_(False))
    reservations = query.order_by(VehicleReservation.start_date.desc()).all()
    return [reservation_out(r) for r in reservations]


@router.get("/by-plate/{license_plate}", response_model=list[VehicleReservationListOut])
def by_plate(license_plate: str, db: Session = Depends(get_db)):
    vehicle = find_vehicle_by_plate(db, license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    reservations = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle)).filter(
        VehicleReservation.vehicle_id == vehicle.id, VehicleReservation.archived.is_(False)
    ).order_by(VehicleReservation.start_date.desc()).all()
    return [reservation_out(r) for r in reservations]


@router.put("/{reservation_id}/status")
def update_status(reservation_id: int, payload: ReservationStatusUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    old_status = reservation.status
    reservation.status = parse_reservation_status(payload.status)
    action = {
        1: "Reservation approved", 2: "Reservation rejected", 3: "Reservation cancelled"
    }.get(reservation.status, "Reservation status changed")
    record_audit(
        db, action=action, entity_type="VehicleReservation", entity_id=reservation.id,
        user=current_user, old_values={"status": old_status}, new_values={"status": reservation.status},
        description=f"Reservation #{reservation.id} status changed.",
    )
    db.commit()
    return {"message": f"Status updated to {reservation_status_name(reservation.status)}."}


@router.put("/{reservation_id}/approve")
def approve(reservation_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    reservation.status = 1
    record_audit(
        db, action="Reservation approved", entity_type="VehicleReservation", entity_id=reservation.id,
        user=current_user, new_values={"status": 1}, description=f"Reservation #{reservation.id} approved.",
    )
    db.commit()
    return {"message": "Reservation approved."}


@router.put("/{reservation_id}/reject")
def reject(reservation_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    reservation.status = 2
    record_audit(
        db, action="Reservation rejected", entity_type="VehicleReservation", entity_id=reservation.id,
        user=current_user, new_values={"status": 2}, description=f"Reservation #{reservation.id} rejected.",
    )
    db.commit()
    return {"message": "Reservation rejected."}


@router.delete("/{reservation_id}")
def archive_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager)),
):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    reservation.archived = True
    reservation.archived_at = datetime.utcnow()
    reservation.archived_by = current_user.id
    record_audit(
        db, action="Reservation archived", entity_type="VehicleReservation", entity_id=reservation.id,
        user=current_user, new_values={"archived": True},
        description=f"Reservation #{reservation.id} archived.",
    )
    db.commit()
    return {"message": "Reservation archived."}


@router.post("/{reservation_id}/restore")
def restore_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    reservation.archived = False
    reservation.archived_at = None
    reservation.archived_by = None
    record_audit(
        db, action="Reservation restored", entity_type="VehicleReservation", entity_id=reservation.id,
        user=current_user, new_values={"archived": False},
        description=f"Reservation #{reservation.id} restored.",
    )
    db.commit()
    return {"message": "Reservation restored."}
