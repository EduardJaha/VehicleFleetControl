from enum import IntEnum
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.services.license_plates import normalized_plate_search
from app.models import Vehicle


class VehicleStatusEnum(IntEnum):
    Active = 0
    InService = 1
    Sold = 2
    OutOfUse = 3
    Assigned = 4


class ReservationStatusEnum(IntEnum):
    Pending = 0
    Approved = 1
    Rejected = 2
    Cancelled = 3
    Completed = 4


def normalize_plate(plate: str | None) -> str:
    return normalized_plate_search(plate)


def status_name(status: int) -> str:
    names = {0: "Active", 1: "InService", 2: "Sold", 3: "OutOfUse", 4: "Assigned"}
    return names.get(status, str(status))


def reservation_status_name(status: int) -> str:
    names = {0: "Pending", 1: "Approved", 2: "Rejected", 3: "Cancelled", 4: "Completed"}
    return names.get(status, str(status))


def parse_vehicle_status(raw: str | int) -> int:
    if isinstance(raw, int):
        if raw in [0, 1, 2, 3, 4]:
            return raw
        raise HTTPException(status_code=400, detail="Invalid status.")
    text = str(raw).strip()
    if text.isdigit():
        return parse_vehicle_status(int(text))
    mapping = {"active": 0, "inservice": 1, "in_service": 1, "sold": 2, "outofuse": 3, "out_of_use": 3, "assigned": 4}
    key = text.replace(" ", "").lower()
    if key not in mapping:
        raise HTTPException(status_code=400, detail="Invalid status.")
    return mapping[key]


def parse_reservation_status(raw: str | int) -> int:
    if isinstance(raw, int):
        if raw in [0, 1, 2, 3, 4]:
            return raw
        raise HTTPException(status_code=400, detail="Invalid reservation status.")
    text = str(raw).strip()
    if text.isdigit():
        return parse_reservation_status(int(text))
    mapping = {"pending": 0, "approved": 1, "rejected": 2, "cancelled": 3, "canceled": 3, "completed": 4}
    key = text.replace(" ", "").lower()
    if key not in mapping:
        raise HTTPException(status_code=400, detail="Invalid reservation status.")
    return mapping[key]


def find_vehicle_by_plate(db: Session, plate: str) -> Vehicle | None:
    normalized = normalize_plate(plate)
    return (
        db.query(Vehicle)
        .filter(Vehicle.license_plate_normalized == normalized)
        .first()
    )
