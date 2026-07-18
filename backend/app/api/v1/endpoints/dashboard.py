from collections import Counter
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.db.session import get_db
from app.models import Vehicle, VehicleReservation
from app.schemas import DashboardSummaryOut, DashboardStatusItem, DashboardLocationItem, DashboardReservationStatusItem
from app.utils.domain import reservation_status_name, parse_vehicle_status

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/summary", response_model=DashboardSummaryOut)
def summary(db: Session = Depends(get_db)):
    vehicles = db.query(Vehicle).filter(Vehicle.archived.is_(False)).all()
    reservations = db.query(VehicleReservation).filter(VehicleReservation.archived.is_(False)).all()
    status_counts = Counter(v.status for v in vehicles)
    location_counts = Counter(v.vehicle_location for v in vehicles)
    reservation_counts = Counter(r.status for r in reservations)
    return DashboardSummaryOut(
        total_vehicles=len(vehicles),
        status_summary=[DashboardStatusItem(status=k, count=v) for k, v in sorted(status_counts.items())],
        location_summary=[DashboardLocationItem(location=k, count=v) for k, v in sorted(location_counts.items())],
        reservation_status_summary=[DashboardReservationStatusItem(status=reservation_status_name(k), count=v) for k, v in sorted(reservation_counts.items())],
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
