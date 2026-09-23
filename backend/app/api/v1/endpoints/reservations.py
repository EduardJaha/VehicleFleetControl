from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.core.authorization import has_permission, require_permission
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User, Vehicle, VehicleReservation
from app.schemas import AddReservation, ReservationStatusUpdate, UserRole, VehicleReservationListOut
from app.utils.dates import format_date, parse_date
from app.utils.domain import ReservationStatusEnum, find_vehicle_by_plate, parse_reservation_status, reservation_status_name
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles

router = APIRouter(dependencies=[Depends(require_permission("reservations.view"))])

BLOCKING_STATUSES = (ReservationStatusEnum.Pending, ReservationStatusEnum.Approved)


def ensure_no_reservation_overlap(
    db: Session,
    *,
    vehicle: Vehicle,
    start: datetime,
    end: datetime,
    exclude_reservation_id: int | None = None,
) -> None:
    # Serialize reservation activation for one vehicle on databases with row locks
    # (notably PostgreSQL). Locking existing reservations would miss empty ranges.
    db.query(Vehicle).filter(
        Vehicle.id == vehicle.id,
        Vehicle.company_id == vehicle.company_id,
    ).with_for_update().one()
    query = db.query(VehicleReservation).filter(
        VehicleReservation.company_id == vehicle.company_id,
        VehicleReservation.vehicle_id == vehicle.id,
        VehicleReservation.archived.is_(False),
        VehicleReservation.status.in_(BLOCKING_STATUSES),
        VehicleReservation.start_date <= end,
        VehicleReservation.end_date >= start,
    )
    if exclude_reservation_id is not None:
        query = query.filter(VehicleReservation.id != exclude_reservation_id)
    if query.first():
        raise HTTPException(status_code=409, detail="This vehicle is already reserved during the selected dates.")


def reservation_out(reservation: VehicleReservation) -> VehicleReservationListOut:
    linked_assignment = max(reservation.assignments, key=lambda item: item.id, default=None)
    return VehicleReservationListOut(
        id=reservation.id,
        vehicle_id=reservation.vehicle_id,
        vehicle_assignment_id=linked_assignment.id if linked_assignment else None,
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
def add_reservation(payload: AddReservation, db: Session = Depends(get_db), current_user: User = Depends(require_permission("reservations.create"))):
    vehicle = find_vehicle_by_plate(db, payload.license_plate)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"No vehicle found with license plate '{payload.license_plate}'.")
    if vehicle.archived:
        raise HTTPException(status_code=400, detail="Archived Vehicles cannot receive new Reservations.")
    start = parse_date(payload.start_date, "StartDate")
    end = parse_date(payload.end_date, "EndDate")
    if end < start:
        raise HTTPException(status_code=400, detail="EndDate must be on or after StartDate.")
    ensure_no_reservation_overlap(db, vehicle=vehicle, start=start, end=end)
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
        message_params={"id": reservation.id, "plate": vehicle.license_plate, "reserved_by": reservation.reserved_by},
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
    if include_archived and not has_permission(db, current_user, "reservations.approve"):
        raise HTTPException(status_code=403, detail="reservations.approve is required to include archived Reservations.")
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
def update_status(reservation_id: int, payload: ReservationStatusUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("reservations.approve"))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    if reservation.status == 4:
        raise HTTPException(status_code=409, detail="A completed Reservation cannot be reopened.")
    old_status = reservation.status
    new_status = parse_reservation_status(payload.status)
    if new_status in BLOCKING_STATUSES:
        ensure_no_reservation_overlap(
            db, vehicle=reservation.vehicle, start=reservation.start_date,
            end=reservation.end_date, exclude_reservation_id=reservation.id,
        )
    reservation.status = new_status
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
def approve(reservation_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("reservations.approve"))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    if reservation.status == 4:
        raise HTTPException(status_code=409, detail="A completed Reservation cannot be reopened.")
    ensure_no_reservation_overlap(
        db, vehicle=reservation.vehicle, start=reservation.start_date,
        end=reservation.end_date, exclude_reservation_id=reservation.id,
    )
    reservation.status = 1
    record_audit(
        db, action="Reservation approved", entity_type="VehicleReservation", entity_id=reservation.id,
        user=current_user, new_values={"status": 1}, description=f"Reservation #{reservation.id} approved.",
    )
    db.commit()
    return {"message": "Reservation approved."}


@router.put("/{reservation_id}/reject")
def reject(reservation_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("reservations.approve"))):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    if reservation.status == 4:
        raise HTTPException(status_code=409, detail="A completed Reservation cannot be reopened.")
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
    current_user: User = Depends(require_permission("reservations.approve")),
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
    current_user: User = Depends(require_permission("reservations.approve")),
):
    reservation = db.get(VehicleReservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found.")
    if reservation.status in BLOCKING_STATUSES:
        ensure_no_reservation_overlap(
            db, vehicle=reservation.vehicle, start=reservation.start_date,
            end=reservation.end_date, exclude_reservation_id=reservation.id,
        )
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
