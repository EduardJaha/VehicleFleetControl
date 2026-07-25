from collections import Counter
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import Vehicle, VehicleAssignment, VehicleReservation
from app.schemas import (
    DashboardActiveUsageItem,
    DashboardLocationItem,
    DashboardReservationStatusItem,
    DashboardStatusItem,
    DashboardSummaryOut,
)
from app.utils.domain import reservation_status_name, parse_vehicle_status

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/summary", response_model=DashboardSummaryOut)
def summary(db: Session = Depends(get_db)):
    vehicles = db.query(Vehicle).filter(Vehicle.archived.is_(False)).all()
    reservations = db.query(VehicleReservation).filter(VehicleReservation.archived.is_(False)).all()
    status_counts = Counter(v.status for v in vehicles)
    location_counts = Counter(v.vehicle_location for v in vehicles)
    reservation_counts = Counter(r.status for r in reservations)
    active_assignments = db.query(VehicleAssignment).options(
        joinedload(VehicleAssignment.vehicle),
        joinedload(VehicleAssignment.driver),
        joinedload(VehicleAssignment.reservation),
    ).filter(
        VehicleAssignment.archived.is_(False),
        VehicleAssignment.status.in_(["Active", "Overdue"]),
        VehicleAssignment.end_datetime.is_(None),
    ).order_by(VehicleAssignment.start_datetime).all()
    now = datetime.utcnow()
    active_usage = [
        DashboardActiveUsageItem(
            assignment_id=assignment.id,
            vehicle_id=assignment.vehicle_id,
            driver_id=assignment.driver_id,
            license_plate=assignment.vehicle.license_plate,
            vehicle_name=f"{assignment.vehicle.brand} {assignment.vehicle.model}",
            driver_name=assignment.driver.full_name,
            checkout_datetime=assignment.start_datetime.isoformat(),
            expected_return_datetime=(
                assignment.reservation.end_date.isoformat() if assignment.reservation else None
            ),
            destination=assignment.destination,
            overdue=(
                assignment.status == "Overdue"
                or bool(assignment.reservation and assignment.reservation.end_date < now)
            ),
        )
        for assignment in active_assignments
    ]
    return DashboardSummaryOut(
        total_vehicles=len(vehicles),
        status_summary=[DashboardStatusItem(status=k, count=v) for k, v in sorted(status_counts.items())],
        location_summary=[DashboardLocationItem(location=k, count=v) for k, v in sorted(location_counts.items())],
        reservation_status_summary=[DashboardReservationStatusItem(status=reservation_status_name(k), count=v) for k, v in sorted(reservation_counts.items())],
        active_usage=active_usage,
        active_usage_count=len(active_usage),
        overdue_return_count=sum(1 for item in active_usage if item.overdue),
    )


@router.get("/filtered")
def filtered(status: str | None = None, location: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Vehicle).filter(Vehicle.archived.is_(False))
    if status:
        query = query.filter(Vehicle.status == parse_vehicle_status(status))
    if location:
        query = query.filter(Vehicle.vehicle_location == location)
    vehicles = query.all()
    status_counts = Counter(v.status for v in vehicles)
    location_counts = Counter(v.vehicle_location for v in vehicles)
    return {
        "total_vehicles": len(vehicles),
        "status_summary": [{"status": k, "count": v} for k, v in sorted(status_counts.items())],
        "location_summary": [{"location": k, "count": v} for k, v in sorted(location_counts.items())],
    }
