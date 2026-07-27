from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from sqlalchemy.orm import Session, joinedload

from app.models import DocumentRequirement, DocumentVersion, Driver, Vehicle, VehiclePaper

COMPLIANT_STATUSES = {"Valid", "Expiring Soon"}


def document_status(
    document: VehiclePaper | None,
    version: DocumentVersion | None,
    *,
    warning_days: int = 30,
    today: date | None = None,
) -> str:
    """Return the lifecycle state for the current immutable version."""
    today = today or datetime.utcnow().date()
    if document is None:
        return "Missing"
    if document.archived or (version is not None and version.archived):
        return "Archived"

    renewal_status = (version.renewal_status if version is not None else document.renewal_status) or "None"
    if renewal_status == "Rejected" or (version is not None and version.rejection_reason):
        return "Rejected"
    if renewal_status in {"In Progress", "Submitted"}:
        return "Renewal In Progress"

    expiry = version.expiry_date if version is not None else document.expiry_date
    days_remaining = (expiry.date() - today).days
    if days_remaining < 0:
        return "Expired"
    if days_remaining <= warning_days:
        return "Expiring Soon"
    return "Valid"


def current_version(document: VehiclePaper) -> DocumentVersion | None:
    return next((version for version in document.versions if version.is_current and not version.archived), None)


def requirement_applies_to_vehicle(requirement: DocumentRequirement, vehicle: Vehicle) -> bool:
    if requirement.applies_to_driver or not requirement.required or not requirement.is_active:
        return False
    if requirement.applies_to_country and requirement.applies_to_country.upper() != vehicle.registration_country.upper():
        return False
    if requirement.applies_to_vehicle_category:
        return (vehicle.vehicle_category or "").casefold() == requirement.applies_to_vehicle_category.casefold()
    return True


def requirement_applies_to_driver(requirement: DocumentRequirement, driver: Driver) -> bool:
    return bool(requirement.applies_to_driver and requirement.required and requirement.is_active and not driver.archived)


def _matching_document(
    documents: Iterable[VehiclePaper],
    requirement: DocumentRequirement,
) -> VehiclePaper | None:
    rows = [document for document in documents if not document.archived]
    exact = next((document for document in rows if document.requirement_id == requirement.id), None)
    if exact:
        return exact
    # Backward compatibility: a legacy record created before Requirements can
    # satisfy a matching rule without changing or duplicating that record.
    return next(
        (
            document
            for document in rows
            if document.requirement_id is None
            and document.document_type.casefold() == requirement.document_type.casefold()
        ),
        None,
    )


def _item(
    requirement: DocumentRequirement,
    document: VehiclePaper | None,
    version: DocumentVersion | None,
    *,
    owner_type: str,
    owner_id: int,
    owner_name: str,
    department: str | None,
    location: str | None,
    country: str | None,
    today: date,
) -> dict:
    status = document_status(
        document,
        version,
        warning_days=requirement.warning_days,
        today=today,
    )
    issue_date = version.issue_date if version else (document.issue_date if document else None)
    expiry_date = version.expiry_date if version else (document.expiry_date if document else None)
    file_path = version.file_path if version else (document.file_path if document else None)
    return {
        "requirement_id": requirement.id,
        "document_id": document.id if document else None,
        "version_id": version.id if version else None,
        "document_type": requirement.document_type,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "owner_name": owner_name,
        "department": department,
        "location": location,
        "country": country,
        "status": status,
        "issue_date": issue_date.date().isoformat() if issue_date else None,
        "expiry_date": expiry_date.date().isoformat() if expiry_date else None,
        "warning_days": requirement.warning_days,
        "file_path": file_path,
    }


def _rates(items: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        name = item.get(key)
        if name:
            groups[str(name)].append(item)
    result = []
    for name, rows in sorted(groups.items(), key=lambda entry: entry[0].casefold()):
        compliant = sum(1 for row in rows if row["status"] in COMPLIANT_STATUSES)
        required = len(rows)
        result.append(
            {
                "name": name,
                "compliant": compliant,
                "required": required,
                "rate": round((compliant / required) * 100, 2) if required else 100.0,
            }
        )
    return result


def compliance_dashboard(db: Session, *, today: date | None = None) -> dict:
    today = today or datetime.utcnow().date()
    requirements = (
        db.query(DocumentRequirement)
        .filter(DocumentRequirement.is_active.is_(True), DocumentRequirement.required.is_(True))
        .order_by(DocumentRequirement.document_type, DocumentRequirement.id)
        .all()
    )
    vehicles = (
        db.query(Vehicle)
        .options(joinedload(Vehicle.papers).joinedload(VehiclePaper.versions), joinedload(Vehicle.assigned_drivers))
        .filter(Vehicle.archived.is_(False))
        .order_by(Vehicle.id)
        .all()
    )
    drivers = (
        db.query(Driver)
        .options(
            joinedload(Driver.documents).joinedload(VehiclePaper.versions),
            joinedload(Driver.assigned_vehicle),
        )
        .filter(Driver.archived.is_(False))
        .order_by(Driver.id)
        .all()
    )

    items: list[dict] = []
    for vehicle in vehicles:
        active_driver = next((driver for driver in vehicle.assigned_drivers if not driver.archived), None)
        for requirement in requirements:
            if not requirement_applies_to_vehicle(requirement, vehicle):
                continue
            document = _matching_document(vehicle.papers, requirement)
            items.append(
                _item(
                    requirement,
                    document,
                    current_version(document) if document else None,
                    owner_type="Vehicle",
                    owner_id=vehicle.id,
                    owner_name=vehicle.license_plate,
                    department=active_driver.department if active_driver else None,
                    location=vehicle.vehicle_location,
                    country=vehicle.registration_country,
                    today=today,
                )
            )

    for driver in drivers:
        for requirement in requirements:
            if not requirement_applies_to_driver(requirement, driver):
                continue
            document = _matching_document(driver.documents, requirement)
            items.append(
                _item(
                    requirement,
                    document,
                    current_version(document) if document else None,
                    owner_type="Driver",
                    owner_id=driver.id,
                    owner_name=driver.full_name,
                    department=driver.department,
                    location=driver.assigned_vehicle.vehicle_location if driver.assigned_vehicle else None,
                    country=None,
                    today=today,
                )
            )

    def days_until(item: dict) -> int | None:
        return (date.fromisoformat(item["expiry_date"]) - today).days if item["expiry_date"] else None

    missing = [item for item in items if item["status"] == "Missing"]
    expired = [item for item in items if item["status"] == "Expired"]
    expiring_7 = [
        item for item in items
        if item["status"] in {"Valid", "Expiring Soon"}
        and (days_until(item) is not None and 0 <= days_until(item) <= 7)
    ]
    expiring_30 = [
        item for item in items
        if item["status"] in {"Valid", "Expiring Soon"}
        and (days_until(item) is not None and 0 <= days_until(item) <= 30)
    ]
    renewals = [item for item in items if item["status"] == "Renewal In Progress"]
    compliant_count = sum(1 for item in items if item["status"] in COMPLIANT_STATUSES)

    vehicle_items = [item for item in items if item["owner_type"] == "Vehicle"]
    driver_items = [item for item in items if item["owner_type"] == "Driver"]
    return {
        "missing_required": missing,
        "expired": expired,
        "expiring_in_7_days": expiring_7,
        "expiring_in_30_days": expiring_30,
        "renewal_in_progress": renewals,
        "items": items,
        "compliance_by_vehicle": _rates(vehicle_items, "owner_name"),
        "compliance_by_driver": _rates(driver_items, "owner_name"),
        "compliance_by_department": _rates(items, "department"),
        "compliance_by_location": _rates(items, "location"),
        "overall_compliance_rate": round((compliant_count / len(items)) * 100, 2) if items else 100.0,
    }
