"""Domain adapters for the retained ImportJob pipeline (no commits here)."""
from datetime import datetime, timezone
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func, or_

from app.models import (
    Attachment, DocumentVersion, Driver, Part, PartCategory, Vehicle,
    VehicleAssignment, VehicleFuel, VehiclePaper, VehicleService, Vendor,
)
from app.maintenance_supply_schemas import PartIn, VendorIn
from app.services.audit import record_audit, snapshot
from app.services.license_plates import normalize_license_plate, validate_license_plate

# key, English label, Albanian label, required, example
VEHICLE_FIELDS = [
    ("registration_country", "Registration Country", "Shteti i Regjistrimit", True, "XK"),
    ("license_plate", "Licence Plate", "Targa", True, "01-123-AB"),
]
SPECS = {
    "Historical Services": VEHICLE_FIELDS + [
        ("service_date", "Service Date", "Data e Servisit", True, "2024-01-15"),
        ("service_type", "Service Type", "Lloji i Servisit", True, "Oil Change"),
        ("odometer_km", "Odometer", "Kilometrazhi", False, 25000),
        ("workshop", "Workshop", "Servisi", False, "Workshop A"),
        ("description", "Description", "Përshkrimi", False, ""),
        ("labor_cost", "Labor Cost", "Kostoja e Punës", False, "20.00"),
        ("parts_cost", "Parts Cost", "Kostoja e Pjesëve", False, "30.00"),
        ("cost", "Total Cost", "Kostoja Totale", False, "50.00"),
        ("next_service_date", "Next Service Date", "Data e Servisit të Ardhshëm", False, ""),
        ("next_service_km_interval", "Next Service Interval", "Intervali i Servisit të Ardhshëm", False, 5000),
    ],
    "Fuel and Charging Records": VEHICLE_FIELDS + [
        ("refuel_date", "Date", "Data", True, "2024-01-15"),
        ("quantity", "Quantity", "Sasia", True, "25.125"),
        ("unit", "Unit", "Njësia", True, "L"),
        ("fuel_type", "Historical Fuel Type", "Lloji Historik i Karburantit", False, "Petrol"),
        ("unit_cost", "Unit Cost", "Kostoja për Njësi", True, "1.5000"),
        ("total_cost", "Total Cost", "Kostoja Totale", False, "37.69"),
        ("odometer_km", "Odometer", "Kilometrazhi", True, 25000),
        ("station_name", "Station / Provider", "Stacioni / Ofruesi", False, "Station A"),
        ("location", "Location", "Lokacioni", True, "Prishtina"),
    ],
    "Vehicle Assignments": VEHICLE_FIELDS + [
        ("employee_number", "Driver Employee Number", "Numri i Punonjësit Shofer", True, "EMP-001"),
        ("start_datetime", "Start Date", "Data e Fillimit", True, "2024-01-15T08:00:00"),
        ("end_datetime", "End Date", "Data e Mbarimit", False, "2024-01-15T17:00:00"),
        ("start_odometer_km", "Start Odometer", "Kilometrazhi Fillestar", True, 25000),
        ("end_odometer_km", "End Odometer", "Kilometrazhi Përfundimtar", False, 25100),
        ("purpose", "Purpose", "Qëllimi", False, ""),
        ("status", "Status", "Statusi", True, "Completed"),
    ],
    "Documents Metadata": [
        ("registration_country", "Registration Country", "Shteti i Regjistrimit", False, "XK"),
        ("license_plate", "Licence Plate", "Targa", False, "01-123-AB"),
        ("employee_number", "Driver Employee Number", "Numri i Punonjësit Shofer", False, ""),
        ("document_type", "Document Type", "Lloji i Dokumentit", True, "Insurance"),
        ("document_number", "Document Number", "Numri i Dokumentit", True, "DOC-001"),
        ("issue_date", "Issue Date", "Data e Lëshimit", True, "2024-01-01"),
        ("expiry_date", "Expiry Date", "Data e Skadimit", True, "2024-12-31"),
        ("issuing_authority", "Issuing Authority", "Autoriteti Lëshues", False, ""),
        ("status", "Status", "Statusi", False, "Expired"),
        ("attachment_id", "Existing Secure Attachment ID", "ID e Bashkëngjitjes së Sigurt", False, ""),
    ],
    "Vendors": [
        ("name", "Name", "Emri", True, "Workshop A"),
        ("vendor_type", "Vendor Type", "Lloji i Furnitorit", True, "Workshop"),
        ("contact_name", "Contact Name", "Emri i Kontaktit", False, ""),
        ("email", "Email", "Email", False, ""),
        ("phone", "Phone", "Telefoni", False, ""),
        ("address", "Address", "Adresa", False, ""),
        ("city", "City", "Qyteti", False, "Prishtina"),
        ("country", "Country", "Shteti", False, "XK"),
        ("tax_number", "Tax Number", "Numri Fiskal", False, ""),
        ("payment_terms", "Payment Terms", "Kushtet e Pagesës", False, ""),
        ("notes", "Notes", "Shënime", False, ""),
    ],
    "Parts": [
        ("part_number", "Part Number", "Numri i Pjesës", True, "OIL-001"),
        ("name", "Name", "Emri", True, "Oil filter"),
        ("category", "Category", "Kategoria", True, "Filters"),
        ("unit", "Unit", "Njësia", True, "piece"),
        ("unit_cost", "Unit Cost", "Kostoja për Njësi", False, "10.0000"),
        ("barcode", "Barcode", "Barkodi", False, ""),
        ("supplier", "Vendor Name", "Emri i Furnitorit", False, ""),
        ("manufacturer", "Manufacturer", "Prodhuesi", False, ""),
        ("description", "Description", "Përshkrimi", False, ""),
        ("minimum_stock", "Minimum Stock", "Stoku Minimal", False, "0.000"),
    ],
}
MODELS = {"Historical Services": VehicleService, "Fuel and Charging Records": VehicleFuel,
          "Vehicle Assignments": VehicleAssignment, "Documents Metadata": VehiclePaper,
          "Vendors": Vendor, "Parts": Part}


class RowError(ValueError):
    def __init__(self, field, code, message):
        super().__init__(message)
        self.field, self.code = field, code


def fail(field, code, message):
    raise RowError(field, code, message)


def text(value, required=False, maximum=255):
    result = str(value if value is not None else "").strip()
    if (required and not result) or len(result) > maximum:
        fail("row", "invalid_value", f"Required text must be present and at most {maximum} characters.")
    return result or None


def number(value, places=2, required=False):
    if value is None or str(value).strip() == "":
        if required:
            fail("row", "invalid_value", "A numeric value is required.")
        return None
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or amount < 0 or amount >= Decimal(10) ** (12 - places):
            raise ValueError()
        return amount.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
    except (ValueError, InvalidOperation):
        fail("row", "invalid_value", "Use a finite nonnegative decimal within the supported range.")


def mileage(value, required=False):
    if value is None or str(value).strip() == "":
        if required:
            fail("odometer", "invalid_value", "Odometer is required.")
        return None
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or amount != int(amount) or not 0 <= amount <= 2_000_000:
            raise ValueError()
        return int(amount)
    except (ValueError, InvalidOperation):
        fail("odometer", "invalid_value", "Odometer must be a whole number from 0 to 2000000.")


def timestamp(value, required=True):
    raw = text(value, required)
    if not raw:
        return None
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        result = None
        for pattern in ("%d-%m-%Y", "%d/%m/%Y"):
            try:
                result = datetime.strptime(raw, pattern)
                break
            except ValueError:
                pass
        if result is None:
            fail("date", "invalid_date", "Use ISO dates/times, dd-MM-yyyy, or dd/MM/yyyy.")
    return result.astimezone(timezone.utc).replace(tzinfo=None) if result.tzinfo else result


def query(db, model, company):
    return db.query(model).filter(model.company_id == company)


def unique(db, model, company, **values):
    rows = query(db, model, company)
    for key, value in values.items():
        column = getattr(model, key)
        rows = rows.filter(func.lower(func.trim(column)) == value.lower() if isinstance(value, str) else column == value)
    matches = rows.limit(2).all()
    if len(matches) > 1:
        fail("row", "conflicting_duplicates", "More than one existing record matches; resolve the ambiguity first.")
    return matches[0] if matches else None


def owner_vehicle(db, company, mapped):
    country = text(mapped.get("registration_country"), True).upper()
    try:
        plate = validate_license_plate(country, text(mapped.get("license_plate"), True))
        normalized = normalize_license_plate(country, plate)
    except ValueError as exc:
        fail("license_plate", "invalid_license_plate", str(exc))
    vehicle = unique(db, Vehicle, company, registration_country=country, license_plate_normalized=normalized)
    if not vehicle:
        fail("license_plate", "import_unknown_reference", "Vehicle not found in this company.")
    return vehicle


def owner_driver(db, company, mapped):
    driver = unique(db, Driver, company, employee_number=text(mapped.get("employee_number"), True))
    if not driver:
        fail("employee_number", "import_unknown_reference", "Driver employee number not found in this company.")
    return driver


def prepare(db, job, mapped):
    kind, company = job.entity_type, job.company_id
    data, identities, warnings = {}, [], []
    vehicle = None
    if kind in {"Historical Services", "Fuel and Charging Records", "Vehicle Assignments"}:
        vehicle = owner_vehicle(db, company, mapped)
        data["vehicle_id"] = vehicle.id
    if kind == "Historical Services":
        data.update(service_date=timestamp(mapped.get("service_date")), service_type=text(mapped.get("service_type"), True, 100),
                    odometer_km=mileage(mapped.get("odometer_km")), workshop=text(mapped.get("workshop"), maximum=100),
                    description=text(mapped.get("description"), maximum=10000),
                    next_service_date=timestamp(mapped.get("next_service_date"), False),
                    next_service_km_interval=mileage(mapped.get("next_service_km_interval")))
        for key in ("cost", "labor_cost", "parts_cost"):
            data[key] = number(mapped.get(key))
        if data["cost"] is None and (data["labor_cost"] is not None or data["parts_cost"] is not None):
            data["cost"] = (data["labor_cost"] or Decimal(0)) + (data["parts_cost"] or Decimal(0))
        data["cost"] = number(data["cost"])
        interval, odometer = data["next_service_km_interval"], data["odometer_km"]
        if interval is not None and (interval not in {5000, 10000, 15000} or odometer is None):
            fail("next_service_km_interval", "invalid_value", "Use 5000, 10000 or 15000 km with an odometer.")
        data["next_service_odometer_km"] = odometer + interval if interval else None
        if data["next_service_date"] and data["next_service_date"] < data["service_date"]:
            fail("next_service_date", "invalid_date", "Next service date cannot precede service date.")
        natural = {key: data[key] for key in ("vehicle_id", "service_date", "service_type")}
    elif kind == "Fuel and Charging Records":
        data.update(refuel_date=timestamp(mapped.get("refuel_date")), quantity=number(mapped.get("quantity"), 3, True),
                    unit=text(mapped.get("unit"), True).upper(), unit_cost=number(mapped.get("unit_cost"), 4, True),
                    odometer_km=mileage(mapped.get("odometer_km"), True), location=text(mapped.get("location"), True),
                    station_name=text(mapped.get("station_name")) or "")
        if data["unit"] not in {"L", "KWH"} or data["quantity"] <= 0:
            fail("unit", "import_energy_unit", "Use positive quantity and unit L or KWH.")
        natural = {key: data[key] for key in ("vehicle_id", "refuel_date", "odometer_km", "unit")}
        existing = unique(db, VehicleFuel, company, **natural)
        fuel = text(mapped.get("fuel_type")) or (existing.fuel_type if existing else vehicle.fuel_type)
        from app.api.v1.endpoints.fuel import validate_fuel_type, energy_unit_for_fuel_type
        from fastapi import HTTPException
        try:
            data["fuel_type"] = validate_fuel_type(fuel)
        except HTTPException:
            fail("fuel_type", "import_energy_unit", "Use a supported historical vehicle fuel type.")
        if data["unit"] != energy_unit_for_fuel_type(data["fuel_type"]).value:
            fail("fuel_type", "import_energy_unit", "Unit must match the historical fuel type; supply the snapshot if different from today's vehicle.")
        data["total_cost"] = (data["quantity"] * data["unit_cost"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = number(mapped.get("total_cost"))
        if total is not None and total != data["total_cost"]:
            fail("total_cost", "import_cost_mismatch", "Total must equal rounded quantity multiplied by unit cost.")
        number(data["total_cost"], required=True)
    elif kind == "Vehicle Assignments":
        driver = owner_driver(db, company, mapped)
        data.update(driver_id=driver.id, start_datetime=timestamp(mapped.get("start_datetime")),
                    end_datetime=timestamp(mapped.get("end_datetime"), False),
                    start_odometer_km=mileage(mapped.get("start_odometer_km"), True),
                    end_odometer_km=mileage(mapped.get("end_odometer_km")), purpose=text(mapped.get("purpose")))
        data["status"] = text(mapped.get("status"), True).capitalize()
        if data["status"] not in {"Completed", "Cancelled", "Scheduled"}:
            fail("status", "import_assignment_status", "Import Completed, Cancelled or Scheduled records. Start live assignments through the checked handover workflow.")
        if data["status"] == "Completed" and (data["end_datetime"] is None or data["end_odometer_km"] is None):
            fail("end_datetime", "invalid_value", "Completed assignments require end date and end odometer.")
        if data["end_datetime"] and data["end_datetime"] < data["start_datetime"]:
            fail("end_datetime", "invalid_date", "End date cannot precede start date.")
        if data["end_odometer_km"] is not None and data["end_odometer_km"] < data["start_odometer_km"]:
            fail("end_odometer_km", "invalid_value", "End odometer cannot be below start odometer.")
        if data["status"] == "Completed" and data["end_datetime"] > datetime.utcnow():
            fail("end_datetime", "invalid_date", "Completed assignments cannot end in the future.")
        if data["status"] == "Scheduled":
            from app.services.vehicle_assignments import validate_assignment_parties
            from fastapi import HTTPException
            try:
                validate_assignment_parties(db, vehicle.id, driver.id, None)
            except HTTPException:
                fail("owner", "import_archived", "Scheduled assignments require unarchived vehicles and drivers.")
        natural = {key: data[key] for key in ("vehicle_id", "driver_id", "start_datetime")}
    elif kind == "Documents Metadata":
        if bool(text(mapped.get("license_plate"))) == bool(text(mapped.get("employee_number"))):
            fail("owner", "import_document_owner", "Provide exactly one Vehicle plate/country or Driver employee number.")
        vehicle = owner_vehicle(db, company, mapped) if text(mapped.get("license_plate")) else None
        driver = owner_driver(db, company, mapped) if not vehicle else None
        data.update(vehicle_id=vehicle.id if vehicle else None, driver_id=driver.id if driver else None,
                    document_type=text(mapped.get("document_type"), True), document_number=text(mapped.get("document_number"), True, 150),
                    issuing_authority=text(mapped.get("issuing_authority")), issue_date=timestamp(mapped.get("issue_date")),
                    expiry_date=timestamp(mapped.get("expiry_date")))
        if data["expiry_date"] < data["issue_date"]:
            fail("expiry_date", "invalid_date", "Expiry cannot precede issue date.")
        status = text(mapped.get("status"))
        days = (data["expiry_date"].date() - datetime.utcnow().date()).days
        derived = "Expired" if days < 0 else "Expiring Soon" if days <= 30 else "Valid"
        if status and status not in {derived, "Renewal In Progress", "Rejected"}:
            fail("status", "import_document_status", "Status must agree with expiry, or be Renewal In Progress or Rejected.")
        data["renewal_status"] = {"Renewal In Progress": "In Progress", "Rejected": "Rejected"}.get(status, "None")
        natural = {key: data[key] for key in ("vehicle_id", "driver_id", "document_type", "document_number")}
    elif kind == "Vendors":
        payload = VendorIn(**{key: text(value, maximum=10000) for key, value in mapped.items()})
        data = payload.model_dump(mode="python")
        data["vendor_type"] = payload.vendor_type.value
        natural = {"name": data["name"]}
    elif kind == "Parts":
        category = unique(db, PartCategory, company, name=text(mapped.get("category"), True))
        if not category or category.archived or not category.is_active:
            fail("category", "import_unknown_reference", "Category must match an active maintenance part category.")
        supplier = unique(db, Vendor, company, name=text(mapped.get("supplier"))) if text(mapped.get("supplier")) else None
        if text(mapped.get("supplier")) and (not supplier or supplier.archived or not supplier.is_active):
            fail("supplier", "import_unknown_reference", "Supplier must match an active maintenance vendor.")
        values = {key: text(value, maximum=10000) for key, value in mapped.items() if key not in {"category", "supplier", "unit_cost", "minimum_stock"}}
        values.update(category_id=category.id, supplier_id=supplier.id if supplier else None,
                      unit_cost=number(mapped.get("unit_cost"), 4) or Decimal(0), minimum_stock=number(mapped.get("minimum_stock"), 3) or Decimal(0))
        data = PartIn(**values).model_dump(mode="python")
        natural = {"part_number": data["part_number"]}
        if data.get("barcode"):
            identities.append(("barcode", data["barcode"].lower()))
    else:
        raise ValueError("Unsupported import entity")

    model = MODELS[kind]
    existing = unique(db, model, company, **natural)
    if kind == "Parts" and data.get("barcode"):
        barcode = unique(db, Part, company, barcode=data["barcode"])
        if barcode and (not existing or barcode.id != existing.id):
            fail("barcode", "conflicting_duplicates", "Barcode belongs to a different part number.")
    if existing and existing.archived:
        fail("row", "import_archived", "Archived records cannot be updated by import.")
    if kind == "Historical Services" and existing and existing.work_order_id:
        fail("row", "import_linked_record", "Work-order-linked services must be edited through maintenance.")
    if kind == "Vehicle Assignments":
        if existing and (existing.status not in {"Completed", "Cancelled", "Scheduled"} or existing.reservation_id):
            fail("status", "import_linked_record", "Live or reservation-linked assignments cannot be overwritten by import.")
        overlaps = query(db, VehicleAssignment, company).filter(
            VehicleAssignment.id != (existing.id if existing else -1), VehicleAssignment.archived.is_(False),
            VehicleAssignment.status != "Cancelled",
            or_(VehicleAssignment.vehicle_id == data["vehicle_id"], VehicleAssignment.driver_id == data["driver_id"]),
            VehicleAssignment.start_datetime <= (data["end_datetime"] or datetime.max),
            or_(VehicleAssignment.end_datetime.is_(None), VehicleAssignment.end_datetime >= data["start_datetime"]),
        ).first()
        if overlaps and data["status"] != "Cancelled":
            if data["status"] == "Scheduled":
                fail("start_datetime", "import_assignment_overlap", "Scheduled assignment conflicts with an existing assignment.")
            warnings.append({"field": "start_datetime", "code": "import_assignment_overlap", "message": "Historical assignment overlaps an existing vehicle or driver assignment; source dates are preserved."})
    if kind in {"Historical Services", "Fuel and Charging Records"}:
        event = data.get("service_date") or data.get("refuel_date")
        if event.date() > datetime.utcnow().date():
            fail("date", "invalid_date", "Historical records cannot be future-dated.")
        # Historical mileage never changes today's Vehicle odometer. Flag suspect sequences for review.
        if data.get("odometer_km") is not None:
            for history, date_field in ((VehicleService, "service_date"), (VehicleFuel, "refuel_date")):
                reading = query(db, history, company).filter(history.vehicle_id == vehicle.id, history.archived.is_(False), history.odometer_km.isnot(None))
                if history == model and existing:
                    reading = reading.filter(history.id != existing.id)
                conflict = reading.filter(or_(
                    (getattr(history, date_field) < event) & (history.odometer_km > data["odometer_km"]),
                    (getattr(history, date_field) > event) & (history.odometer_km < data["odometer_km"]),
                )).first()
                if conflict:
                    warnings.append({"field": "odometer_km", "code": "import_mileage_conflict", "message": "Mileage conflicts with dated history; review the source correction."})
                    break
            if vehicle.odometer_km is not None and data["odometer_km"] > vehicle.odometer_km:
                warnings.append({"field": "odometer_km", "code": "import_mileage_conflict", "message": "Historical mileage exceeds the current vehicle reading; the current reading will be preserved."})
    if kind == "Documents Metadata":
        attachment_id = mileage(mapped.get("attachment_id"))
        if attachment_id:
            attachment = unique(db, Attachment, company, id=attachment_id)
            owner_document = None
            if attachment and not attachment.archived and attachment.mime_type == "application/pdf":
                if attachment.entity_type == "VehiclePaper":
                    owner_document = unique(db, VehiclePaper, company, id=attachment.entity_id)
                elif attachment.entity_type == "DocumentVersion":
                    version = unique(db, DocumentVersion, company, id=attachment.entity_id)
                    if version and not version.archived:
                        owner_document = unique(db, VehiclePaper, company, id=version.document_id)
            if not owner_document or owner_document.archived or owner_document.vehicle_id != data["vehicle_id"] or owner_document.driver_id != data["driver_id"]:
                fail("attachment_id", "import_unsafe_attachment", "Use an existing secure PDF attachment belonging to a document for the same owner and company.")
            from app.core.config import get_settings
            base = get_settings().uploads_path.resolve()
            path = (base / attachment.storage_path).resolve()
            if base not in path.parents or not path.is_file():
                fail("attachment_id", "import_unsafe_attachment", "Secure attachment file is unavailable.")
            data["_attachment_id"] = attachment.id
            data["file_path"] = f"/api/v1/files/{attachment.id}/download"
        else:
            data["file_path"] = existing.file_path if existing else ""
    identities.insert(0, ("identity", repr(tuple((key, value.lower() if isinstance(value, str) else str(value)) for key, value in natural.items()))))
    data["_target_fingerprint"] = fingerprint(existing) if existing else None
    data["_warnings"] = warnings
    # JSON staging retains exact decimal values and UTC timestamps.
    data = {key: value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, Decimal) else value for key, value in data.items()}
    return data, existing.id if existing else None, list(natural), [], identities


def fingerprint(entity):
    return hashlib.sha256(json.dumps(snapshot(entity), sort_keys=True, default=str).encode()).hexdigest()


def apply(db, job, row, user, data):
    model = MODELS[job.entity_type]
    entity = unique(db, model, job.company_id, id=row.target_id) if row.target_id else model(company_id=job.company_id)
    if entity is None:
        raise ValueError("Matched record disappeared")
    old = snapshot(entity) if row.target_id else None
    supplied = {key for key, value in (job.column_mapping or {}).items() if value}
    aliases = {"category": "category_id", "supplier": "supplier_id", "status": "renewal_status" if model == VehiclePaper else "status"}
    provided = supplied | {aliases[key] for key in supplied if key in aliases}
    if "next_service_km_interval" in supplied or "odometer_km" in supplied:
        provided.add("next_service_odometer_km")
    if model == VehicleFuel:
        provided |= {"total_cost", "fuel_type"}
    if model == VehicleService and "cost" not in supplied and {"labor_cost", "parts_cost"} & supplied:
        provided.add("cost")
    if "attachment_id" in supplied:
        provided.add("file_path")
    for key, value in data.items():
        if key.startswith("_") or (row.target_id and key not in provided):
            continue
        column = model.__table__.columns.get(model.__mapper__.attrs[key].columns[0].name)
        if value is not None:
            if column.type.python_type is datetime:
                value = timestamp(value)
            elif column.type.python_type is Decimal:
                value = Decimal(value)
        setattr(entity, key, value)
    if model == VehicleAssignment and not row.target_id:
        entity.assigned_by_user_id = user.id
    if model == VehicleService and not row.target_id:
        entity.source = "Imported"
    if not row.target_id:
        db.add(entity)
    db.flush()
    if model == VehiclePaper:
        versions = query(db, DocumentVersion, job.company_id).filter(DocumentVersion.document_id == entity.id).all()
        previous = next((version for version in versions if version.is_current), None)
        for version in versions:
            version.is_current = False
        db.flush()
        db.add(DocumentVersion(
            company_id=job.company_id, document_id=entity.id, version_number=max((v.version_number for v in versions), default=0) + 1,
            attachment_id=data.get("_attachment_id") or (previous.attachment_id if previous else None),
            uploaded_by=user.id, **{key: getattr(entity, key) for key in ("file_path", "document_number", "issuing_authority", "issue_date", "expiry_date", "renewal_status")},
        ))
        db.flush()
    action = "updated" if row.target_id else "created"
    record_audit(db, action=f"{model.__name__} imported ({action})", entity_type=model.__name__, entity_id=entity.id,
                 user=user, old_values=old, new_values=snapshot(entity), description=f"Import job #{job.id}, row {row.row_number}.")
    return action, entity.id

