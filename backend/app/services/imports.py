from __future__ import annotations

import csv
import io
import re
from copy import copy
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from openpyxl import Workbook, load_workbook
from pydantic import ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Driver, ImportJob, ImportRowResult, User, Vehicle, VehicleBrand, VehicleModel
from app.schemas import (
    DriverCreate,
    ImportEntityType,
    ImportJobStatus,
    ImportTransactionMode,
    ImportUpdateMode,
    VehicleCreate,
)
from app.services.audit import record_audit, snapshot
from app.services.license_plates import PlateValidationError, RegistrationCountry, normalize_license_plate, validate_license_plate
from app.utils.vehicle_catalog import normalize_catalog_name

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 20_000
MAX_IMPORT_COLUMNS = 100
SUPPORTED_ENTITIES = {ImportEntityType.vehicles.value, ImportEntityType.drivers.value}
TERMINAL_STATUSES = {
    ImportJobStatus.completed.value,
    ImportJobStatus.completed_with_errors.value,
    ImportJobStatus.failed.value,
    ImportJobStatus.cancelled.value,
}


@dataclass(frozen=True)
class ImportField:
    key: str
    labels: dict[str, str]
    required: bool
    example: str | int
    aliases: tuple[str, ...] = ()


FIELDS: dict[str, tuple[ImportField, ...]] = {
    ImportEntityType.vehicles.value: (
        ImportField("registration_country", {"en": "Registration Country", "sq": "Shteti i Regjistrimit"}, True, "XK", ("country", "country code")),
        ImportField("license_plate", {"en": "Licence Plate", "sq": "Targa"}, True, "01-123-AB", ("license plate", "plate", "registration")),
        ImportField("brand", {"en": "Brand", "sq": "Marka"}, True, "Toyota", ("make",)),
        ImportField("model", {"en": "Model", "sq": "Modeli"}, True, "Corolla"),
        ImportField("fuel_type", {"en": "Fuel Type", "sq": "Lloji i Karburantit"}, True, "Petrol", ("fuel",)),
        ImportField("vehicle_location", {"en": "Location", "sq": "Lokacioni"}, True, "Prishtina", ("vehicle location",)),
        ImportField("vehicle_category", {"en": "Vehicle Category", "sq": "Kategoria e Automjetit"}, False, "Pool", ("category",)),
        ImportField("year", {"en": "Year", "sq": "Viti"}, False, 2025),
        ImportField("vin_number", {"en": "VIN", "sq": "VIN"}, False, "JTDBR32E720123456", ("vin number",)),
        ImportField("engine_cc", {"en": "Engine CC", "sq": "Vëllimi i Motorit CC"}, False, 1800, ("engine",)),
        ImportField("odometer_km", {"en": "Odometer KM", "sq": "Kilometrazhi KM"}, False, 25000, ("odometer", "mileage")),
        ImportField("status", {"en": "Status", "sq": "Statusi"}, False, "Active"),
    ),
    ImportEntityType.drivers.value: (
        ImportField("full_name", {"en": "Full Name", "sq": "Emri i Plotë"}, True, "Arben Krasniqi", ("name", "driver name")),
        ImportField("employee_number", {"en": "Employee Number", "sq": "Numri i Punonjësit"}, True, "EMP-001", ("employee id", "staff number")),
        ImportField("email", {"en": "Email", "sq": "Email"}, False, "arben@example.com", ("email address",)),
        ImportField("phone_number", {"en": "Phone Number", "sq": "Numri i Telefonit"}, False, "+38344123456", ("phone",)),
        ImportField("department", {"en": "Department", "sq": "Departamenti"}, False, "Operations"),
        ImportField("license_number", {"en": "Licence Number", "sq": "Numri i Patentës"}, True, "LIC-001", ("license number", "driving licence")),
        ImportField("license_category", {"en": "Licence Category", "sq": "Kategoria e Patentës"}, True, "B", ("license category",)),
        ImportField("license_expiry_date", {"en": "Licence Expiry Date", "sq": "Data e Skadimit të Patentës"}, True, "31-12-2027", ("license expiry", "expiry date")),
        ImportField("status", {"en": "Status", "sq": "Statusi"}, False, "Active"),
        ImportField("notes", {"en": "Notes", "sq": "Shënime"}, False, ""),
    ),
}

VEHICLE_STATUSES = {
    "0": 0, "active": 0,
    "1": 1, "in service": 1, "in_service": 1,
    "2": 2, "sold": 2,
    "3": 3, "out of use": 3, "out_of_use": 3,
    "4": 4, "assigned": 4,
}
DRIVER_STATUSES = {"active": "Active", "suspended": "Suspended", "left company": "Left Company"}


def normalized_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def fields_for(entity_type: str, language: str = "en") -> list[dict[str, Any]]:
    language = "sq" if language == "sq" else "en"
    return [
        {"key": field.key, "label": field.labels[language], "required": field.required, "example": field.example}
        for field in FIELDS.get(entity_type, ())
    ]


def suggested_mapping(entity_type: str, headers: list[str]) -> dict[str, str]:
    available = {normalized_header(header): header for header in headers}
    result: dict[str, str] = {}
    for field in FIELDS.get(entity_type, ()):
        candidates = {normalized_header(field.key), *(normalized_header(value) for value in field.labels.values()), *(normalized_header(value) for value in field.aliases)}
        match = next((available[candidate] for candidate in candidates if candidate in available), None)
        if match:
            result[field.key] = match
    return result


def template_bytes(entity_type: str, language: str, file_format: str) -> tuple[bytes, str, str]:
    if entity_type not in SUPPORTED_ENTITIES:
        raise HTTPException(status_code=422, detail="Templates are currently available for Vehicles and Drivers.")
    language = "sq" if language == "sq" else "en"
    fields = FIELDS[entity_type]
    headers = [field.labels[language] for field in fields]
    example = [field.example for field in fields]
    stem = "vehicles" if entity_type == ImportEntityType.vehicles.value else "drivers"
    if file_format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerow(example)
        return output.getvalue().encode("utf-8-sig"), f"{stem}-import-template-{language}.csv", "text/csv"
    if file_format != "xlsx":
        raise HTTPException(status_code=422, detail="format must be csv or xlsx.")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Import"
    sheet.append(headers)
    sheet.append(example)
    sheet.freeze_panes = "A2"
    for cell in sheet[1]:
        font = copy(cell.font)
        font.bold = True
        cell.font = font
    for column in sheet.columns:
        width = max(len(str(cell.value or "")) for cell in column) + 2
        sheet.column_dimensions[column[0].column_letter].width = min(max(width, 12), 35)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), f"{stem}-import-template-{language}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _json_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def parse_import_bytes(data: bytes, extension: str) -> tuple[list[str], list[dict[str, Any]]]:
    if not data:
        raise HTTPException(status_code=400, detail="Empty files are not allowed.")
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Import files cannot exceed 10 MB.")
    rows: list[list[Any]] = []
    if extension == ".csv":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="CSV files must use UTF-8 encoding.") from exc
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), dialect))
        except csv.Error as exc:
            raise HTTPException(status_code=422, detail=f"The CSV file is malformed: {exc}.") from exc
    elif extension == ".xlsx":
        if not data.startswith(b"PK"):
            raise HTTPException(status_code=415, detail="The file content is not a valid XLSX workbook.")
        try:
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheet = workbook.active
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            workbook.close()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="The XLSX workbook could not be read.") from exc
    else:
        raise HTTPException(status_code=415, detail="Only .csv and .xlsx import files are supported.")
    while rows and not any(str(value or "").strip() for value in rows[-1]):
        rows.pop()
    if not rows:
        raise HTTPException(status_code=422, detail="The file must contain a header row.")
    if len(rows) - 1 > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=413, detail=f"Import files cannot contain more than {MAX_IMPORT_ROWS} data rows.")
    if len(rows[0]) > MAX_IMPORT_COLUMNS:
        raise HTTPException(status_code=422, detail=f"Import files cannot contain more than {MAX_IMPORT_COLUMNS} columns.")
    headers = [str(value or "").strip() for value in rows[0]]
    if not headers or any(not value for value in headers):
        raise HTTPException(status_code=422, detail="Every source column must have a header.")
    normalized = [normalized_header(value) for value in headers]
    duplicates = [name for name, count in Counter(normalized).items() if count > 1]
    if duplicates:
        raise HTTPException(status_code=422, detail="Source column headers must be unique.")
    output: list[dict[str, Any]] = []
    for row in rows[1:]:
        values = list(row[: len(headers)]) + [None] * max(0, len(headers) - len(row))
        if not any(str(value or "").strip() for value in values):
            continue
        output.append({header: _json_value(value) for header, value in zip(headers, values)})
    return headers, output


async def store_import(file: UploadFile, entity_type: str, user: User, db: Session) -> ImportJob:
    if entity_type not in FIELDS:
        raise HTTPException(status_code=422, detail="This import type is planned but is not enabled yet.")
    filename = Path((file.filename or "").replace("\\", "/")).name[:255]
    extension = Path(filename).suffix.lower()
    data = await file.read(MAX_IMPORT_BYTES + 1)
    await file.close()
    headers, rows = parse_import_bytes(data, extension)
    base = get_settings().uploads_path.resolve()
    folder = (base / "imports").resolve()
    if base not in folder.parents:
        raise HTTPException(status_code=400, detail="Invalid import storage path.")
    folder.mkdir(parents=True, exist_ok=True)
    target = (folder / f"{uuid4().hex}{extension}").resolve()
    if base not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid import storage path.")
    try:
        target.write_bytes(data)
        job = ImportJob(
            entity_type=entity_type,
            filename=filename,
            source_path=target.relative_to(base).as_posix(),
            uploaded_by=user.id,
            status=ImportJobStatus.uploaded.value,
            source_headers=headers,
            total_rows=len(rows),
        )
        db.add(job)
        db.flush()
        record_audit(
            db, action="Import uploaded", entity_type="ImportJob", entity_id=job.id, user=user,
            new_values={"entity_type": entity_type, "filename": filename, "total_rows": len(rows)},
            description=f"{entity_type} import file uploaded for dry-run validation.",
        )
        db.commit()
        db.refresh(job)
        return job
    except Exception:
        target.unlink(missing_ok=True)
        db.rollback()
        raise


def read_job_rows(job: ImportJob) -> list[dict[str, Any]]:
    base = get_settings().uploads_path.resolve()
    path = (base / job.source_path).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="The retained import source file was not found.")
    _, rows = parse_import_bytes(path.read_bytes(), path.suffix.lower())
    return rows


def validate_mapping(job: ImportJob, mapping: dict[str, str]) -> None:
    definitions = {field.key: field for field in FIELDS[job.entity_type]}
    unknown = sorted(set(mapping) - set(definitions))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown target fields: {', '.join(unknown)}.")
    missing = [field.key for field in definitions.values() if field.required and not mapping.get(field.key)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Required fields are not mapped: {', '.join(missing)}.")
    sources = [value for value in mapping.values() if value]
    if len(sources) != len(set(sources)):
        raise HTTPException(status_code=422, detail="A source column can only be mapped once.")
    unavailable = sorted(set(sources) - set(job.source_headers or []))
    if unavailable:
        raise HTTPException(status_code=422, detail=f"Mapped source columns were not found: {', '.join(unavailable)}.")


def _text(value: Any, *, required: bool = False, maximum: int | None = None) -> str | None:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError("This field is required.")
    if maximum and len(result) > maximum:
        raise ValueError(f"Must contain at most {maximum} characters.")
    return result or None


def _integer(value: Any, *, minimum: int, maximum: int, field: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text):
        text = text.replace(",", "")
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be a whole number.") from exc
    if not number.is_integer() or not minimum <= number <= maximum:
        raise ValueError(f"{field} must be a whole number from {minimum} to {maximum}.")
    return int(number)


def _date_text(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%d-%m-%Y")
    text = str(value or "").strip()
    for pattern in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).strftime("%d-%m-%Y")
        except ValueError:
            continue
    raise ValueError("Date must use dd-MM-yyyy, yyyy-MM-dd, or dd/MM/yyyy.")


def _pydantic_errors(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"field": str(error.get("loc", ["row"])[-1]), "code": "invalid_value", "message": str(error.get("msg", "Invalid value." )).replace("Value error, ", "")}
        for error in exc.errors()
    ]


def _candidate_ids(*queries: Any) -> tuple[set[int], list[str]]:
    ids: set[int] = set()
    fields: list[str] = []
    for field, row in queries:
        if row is not None:
            ids.add(row.id)
            fields.append(field)
    return ids, fields


def _vehicle_data(db: Session, mapped: dict[str, Any]) -> tuple[dict[str, Any], int | None, list[str], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    data: dict[str, Any] = {}
    try:
        country = RegistrationCountry(str(mapped.get("registration_country") or "").strip().upper())
        plate = validate_license_plate(country, str(mapped.get("license_plate") or ""))
        data["registration_country"] = country.value
        data["license_plate"] = plate
        data["license_plate_normalized"] = normalize_license_plate(country, plate)
    except (ValueError, PlateValidationError) as exc:
        errors.append({"field": "license_plate", "code": "invalid_license_plate", "message": str(exc)})
    brand_name = _text(mapped.get("brand"), required=True, maximum=255)
    model_name = _text(mapped.get("model"), required=True, maximum=255)
    brand = db.query(VehicleBrand).filter(VehicleBrand.normalized_name == normalize_catalog_name(brand_name or "")).first()
    if not brand or not brand.is_active:
        errors.append({"field": "brand", "code": "unknown_brand", "message": "Brand must match an active Vehicle Catalogue brand."})
    model = db.query(VehicleModel).filter(
        VehicleModel.brand_id == (brand.id if brand else -1),
        VehicleModel.normalized_name == normalize_catalog_name(model_name or ""),
    ).first()
    if not model or not model.is_active:
        errors.append({"field": "model", "code": "unknown_model", "message": "Model must match an active model for the selected brand."})
    try:
        status_text = str(mapped.get("status") or "0").strip().casefold()
        if status_text not in VEHICLE_STATUSES:
            raise ValueError("Status must be Active, In Service, Sold, Out of Use, Assigned, or 0-4.")
        data.update({
            "brand_id": brand.id if brand else None,
            "model_id": model.id if model else None,
            "brand": brand.name if brand else brand_name,
            "model": model.name if model else model_name,
            "fuel_type": _text(mapped.get("fuel_type"), required=True),
            "vehicle_location": _text(mapped.get("vehicle_location"), required=True),
            "vehicle_category": _text(mapped.get("vehicle_category"), maximum=100),
            "year": _integer(mapped.get("year"), minimum=1900, maximum=2100, field="Year"),
            "vin_number": _text(mapped.get("vin_number"), maximum=50),
            "engine_cc": _integer(mapped.get("engine_cc"), minimum=50, maximum=10000, field="Engine CC"),
            "odometer_km": _integer(mapped.get("odometer_km"), minimum=0, maximum=2_000_000, field="Odometer KM"),
            "status": VEHICLE_STATUSES[status_text],
        })
        if not errors:
            VehicleCreate(**{key: data[key] for key in ("brand_id", "model_id", "registration_country", "license_plate", "fuel_type", "vehicle_location", "vehicle_category", "year", "vin_number", "engine_cc", "odometer_km", "status")})
    except (ValueError, ValidationError) as exc:
        errors.extend(_pydantic_errors(exc) if isinstance(exc, ValidationError) else [{"field": "row", "code": "invalid_value", "message": str(exc)}])
    plate_row = None
    if data.get("registration_country") and data.get("license_plate_normalized"):
        plate_row = db.query(Vehicle).filter(
            Vehicle.registration_country == data["registration_country"],
            Vehicle.license_plate_normalized == data["license_plate_normalized"],
        ).first()
    vin_row = db.query(Vehicle).filter(func.lower(Vehicle.vin_number) == data["vin_number"].casefold()).first() if data.get("vin_number") else None
    ids, duplicate_fields = _candidate_ids(("license_plate", plate_row), ("vin_number", vin_row))
    if len(ids) > 1:
        errors.append({"field": "row", "code": "conflicting_duplicates", "message": "The licence plate and VIN match different existing Vehicles."})
    return data, next(iter(ids), None), duplicate_fields, errors


def _driver_data(db: Session, mapped: dict[str, Any]) -> tuple[dict[str, Any], int | None, list[str], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    data: dict[str, Any] = {}
    try:
        status_text = str(mapped.get("status") or "Active").strip().casefold()
        if status_text not in DRIVER_STATUSES:
            raise ValueError("Status must be Active, Suspended, or Left Company.")
        data = {
            "full_name": _text(mapped.get("full_name"), required=True, maximum=255),
            "employee_number": _text(mapped.get("employee_number"), required=True, maximum=100),
            "email": _text(mapped.get("email"), maximum=255),
            "phone_number": _text(mapped.get("phone_number"), maximum=50),
            "department": _text(mapped.get("department"), maximum=100),
            "license_number": _text(mapped.get("license_number"), required=True, maximum=100),
            "license_category": _text(mapped.get("license_category"), required=True, maximum=50),
            "license_expiry_date": _date_text(mapped.get("license_expiry_date")),
            "status": DRIVER_STATUSES[status_text],
            "notes": _text(mapped.get("notes")),
        }
        payload = DriverCreate(**data)
        data = payload.model_dump(mode="json")
    except (ValueError, ValidationError) as exc:
        errors.extend(_pydantic_errors(exc) if isinstance(exc, ValidationError) else [{"field": "row", "code": "invalid_value", "message": str(exc)}])
    email_row = db.query(Driver).filter(func.lower(Driver.email) == str(data.get("email")).casefold()).first() if data.get("email") else None
    employee_row = db.query(Driver).filter(func.lower(Driver.employee_number) == str(data.get("employee_number")).casefold()).first() if data.get("employee_number") else None
    license_row = db.query(Driver).filter(func.lower(Driver.license_number) == str(data.get("license_number")).casefold()).first() if data.get("license_number") else None
    ids, duplicate_fields = _candidate_ids(("email", email_row), ("employee_number", employee_row), ("license_number", license_row))
    if len(ids) > 1:
        errors.append({"field": "row", "code": "conflicting_duplicates", "message": "Email, employee number, and licence number match different existing Drivers."})
    return data, next(iter(ids), None), duplicate_fields, errors


def validate_job(db: Session, job: ImportJob, mapping: dict[str, str], update_mode: ImportUpdateMode) -> ImportJob:
    if job.status in TERMINAL_STATUSES or job.status == ImportJobStatus.importing.value:
        raise HTTPException(status_code=409, detail="This import job can no longer be validated.")
    validate_mapping(job, mapping)
    rows = read_job_rows(job)
    job.status = ImportJobStatus.validating.value
    job.column_mapping = mapping
    job.update_mode = update_mode.value
    job.started_at = datetime.utcnow()
    db.query(ImportRowResult).filter(ImportRowResult.import_job_id == job.id).delete(synchronize_session=False)
    db.flush()
    prepared: list[dict[str, Any]] = []
    identifiers: list[tuple[str, str] | None] = []
    for raw in rows:
        mapped = {target: raw.get(source, "") for target, source in mapping.items() if source}
        try:
            if job.entity_type == ImportEntityType.vehicles.value:
                data, target_id, duplicate_fields, errors = _vehicle_data(db, mapped)
                identity = ("plate", f"{data.get('registration_country')}:{data.get('license_plate_normalized')}") if data.get("license_plate_normalized") else None
                extra_identities = [("vin", str(data.get("vin_number")).casefold())] if data.get("vin_number") else []
                identifier = identity
            else:
                data, target_id, duplicate_fields, errors = _driver_data(db, mapped)
                identifier = ("employee", str(data.get("employee_number")).casefold()) if data.get("employee_number") else None
                extra_identities = []
                if data.get("email"):
                    extra_identities.append(("email", str(data["email"]).casefold()))
                if data.get("license_number"):
                    extra_identities.append(("license_number", str(data["license_number"]).casefold()))
        except ValueError as exc:
            data, target_id, duplicate_fields = mapped, None, []
            errors = [{"field": "row", "code": "invalid_value", "message": str(exc)}]
            identifier, extra_identities = None, []
        prepared.append({"raw": raw, "data": data, "target_id": target_id, "duplicate_fields": duplicate_fields, "errors": errors, "extra_identities": extra_identities})
        identifiers.append(identifier)
    counts = Counter(value for value in identifiers if value)
    extra_counts = Counter(identity for item in prepared for identity in item["extra_identities"])
    valid = invalid = 0
    for index, item in enumerate(prepared, start=2):
        errors = list(item["errors"])
        identity = identifiers[index - 2]
        if identity and counts[identity] > 1:
            errors.append({"field": identity[0], "code": "duplicate_in_file", "message": "This identifier occurs more than once in the import file."})
        for extra_identity in item["extra_identities"]:
            if extra_counts[extra_identity] > 1:
                errors.append({"field": extra_identity[0], "code": "duplicate_in_file", "message": "This identifier occurs more than once in the import file."})
        if item["target_id"] is not None and update_mode == ImportUpdateMode.create_only:
            errors.append({"field": ", ".join(item["duplicate_fields"]), "code": "duplicate_existing", "message": "An existing record matches this row. Select explicit update mode to update it."})
        action = "update" if item["target_id"] is not None else "create"
        status = "Invalid" if errors else "Valid"
        invalid += bool(errors)
        valid += not errors
        db.add(ImportRowResult(
            import_job_id=job.id, row_number=index, status=status, action=action,
            raw_data=item["raw"], mapped_data=item["data"], errors=errors or None,
            duplicate_fields=item["duplicate_fields"] or None, target_id=item["target_id"],
        ))
    job.total_rows = len(prepared)
    job.valid_rows = valid
    job.invalid_rows = invalid
    job.created_rows = job.updated_rows = job.skipped_rows = 0
    job.status = ImportJobStatus.ready.value
    job.error_report_path = f"/api/v1/imports/{job.id}/errors" if invalid else None
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


def _apply_vehicle(db: Session, row: ImportRowResult, user: User) -> tuple[str, int]:
    data = row.mapped_data or {}
    vehicle = db.get(Vehicle, row.target_id) if row.target_id else Vehicle()
    if row.target_id and vehicle is None:
        raise RuntimeError("The Vehicle matched during validation no longer exists.")
    conflicting = db.query(Vehicle).filter(
        or_(
            (Vehicle.registration_country == data.get("registration_country")) & (Vehicle.license_plate_normalized == data.get("license_plate_normalized")),
            func.lower(Vehicle.vin_number) == str(data.get("vin_number") or "").casefold(),
        ),
        Vehicle.id != (row.target_id or -1),
    ).first()
    if conflicting:
        raise RuntimeError("A duplicate Vehicle was created after validation.")
    action = "updated" if row.target_id else "created"
    old = snapshot(vehicle) if row.target_id else None
    for key in ("brand_id", "model_id", "brand", "model", "fuel_type", "vehicle_location", "vehicle_category", "registration_country", "license_plate", "license_plate_normalized", "year", "vin_number", "engine_cc", "odometer_km", "status"):
        setattr(vehicle, key, data.get(key))
    if not row.target_id:
        db.add(vehicle)
    db.flush()
    record_audit(
        db, action=f"Vehicle imported ({action})", entity_type="Vehicle", entity_id=vehicle.id, user=user,
        old_values=old, new_values=snapshot(vehicle), description=f"Vehicle row {row.row_number} {action} by import job #{row.import_job_id}.",
    )
    return action, vehicle.id


def _apply_driver(db: Session, row: ImportRowResult, user: User) -> tuple[str, int]:
    data = row.mapped_data or {}
    driver = db.get(Driver, row.target_id) if row.target_id else Driver()
    if row.target_id and driver is None:
        raise RuntimeError("The Driver matched during validation no longer exists.")
    duplicate_filters = [
        func.lower(Driver.employee_number) == str(data.get("employee_number") or "").casefold(),
        func.lower(Driver.license_number) == str(data.get("license_number") or "").casefold(),
    ]
    if data.get("email"):
        duplicate_filters.append(func.lower(Driver.email) == str(data["email"]).casefold())
    conflicting = db.query(Driver).filter(or_(*duplicate_filters), Driver.id != (row.target_id or -1)).first()
    if conflicting:
        raise RuntimeError("A duplicate Driver was created after validation.")
    action = "updated" if row.target_id else "created"
    old = snapshot(driver) if row.target_id else None
    for key in ("full_name", "employee_number", "email", "phone_number", "department", "license_number", "license_category", "status", "notes"):
        setattr(driver, key, data.get(key))
    driver.license_expiry_date = datetime.strptime(data["license_expiry_date"], "%d-%m-%Y")
    driver.updated_at = datetime.utcnow()
    if not row.target_id:
        db.add(driver)
    db.flush()
    record_audit(
        db, action=f"Driver imported ({action})", entity_type="Driver", entity_id=driver.id, user=user,
        old_values=old, new_values=snapshot(driver), description=f"Driver row {row.row_number} {action} by import job #{row.import_job_id}.",
    )
    return action, driver.id


def _apply_row(db: Session, job: ImportJob, row: ImportRowResult, user: User) -> tuple[str, int]:
    if job.entity_type == ImportEntityType.vehicles.value:
        return _apply_vehicle(db, row, user)
    return _apply_driver(db, row, user)


def confirm_job(db: Session, job: ImportJob, user: User, update_mode: ImportUpdateMode, transaction_mode: ImportTransactionMode) -> ImportJob:
    if job.status != ImportJobStatus.ready.value:
        raise HTTPException(status_code=409, detail="Only a validated Ready import can be confirmed.")
    if job.update_mode != update_mode.value:
        raise HTTPException(status_code=409, detail="Update mode changed. Run dry-run validation again before confirming.")
    job.status = ImportJobStatus.importing.value
    job.transaction_mode = transaction_mode.value
    job.started_at = datetime.utcnow()
    db.flush()
    rows = db.query(ImportRowResult).filter(ImportRowResult.import_job_id == job.id).order_by(ImportRowResult.row_number).all()
    valid_rows = [row for row in rows if row.status == "Valid"]
    created = updated = runtime_failed = 0
    try:
        for row in valid_rows:
            try:
                if transaction_mode == ImportTransactionMode.row:
                    with db.begin_nested():
                        action, target_id = _apply_row(db, job, row, user)
                else:
                    action, target_id = _apply_row(db, job, row, user)
                row.target_id = target_id
                row.status = "Created" if action == "created" else "Updated"
                created += action == "created"
                updated += action == "updated"
            except Exception as exc:
                if transaction_mode == ImportTransactionMode.file:
                    raise
                runtime_failed += 1
                row.status = "Failed"
                row.action = "skip"
                row.errors = [{"field": "row", "code": "import_failed", "message": "The row could not be imported because the data changed after validation."}]
                row.target_id = None
        job.created_rows = created
        job.updated_rows = updated
        job.skipped_rows = job.invalid_rows + runtime_failed
        job.completed_at = datetime.utcnow()
        job.status = ImportJobStatus.completed_with_errors.value if job.skipped_rows else ImportJobStatus.completed.value
        if job.skipped_rows:
            job.error_report_path = f"/api/v1/imports/{job.id}/errors"
        record_audit(
            db, action="Import confirmed", entity_type="ImportJob", entity_id=job.id, user=user,
            new_values={
                "entity_type": job.entity_type, "filename": job.filename, "update_mode": update_mode.value,
                "transaction_mode": transaction_mode.value, "created_rows": created, "updated_rows": updated,
                "skipped_rows": job.skipped_rows, "status": job.status,
            },
            description=f"Import job #{job.id} confirmed using {transaction_mode.value}-transaction mode.",
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_job = db.get(ImportJob, job.id)
        failed_job.status = ImportJobStatus.failed.value
        failed_job.created_rows = failed_job.updated_rows = 0
        failed_job.skipped_rows = failed_job.total_rows
        failed_job.completed_at = datetime.utcnow()
        failed_job.error_report_path = f"/api/v1/imports/{failed_job.id}/errors"
        record_audit(
            db, action="Import confirmed", entity_type="ImportJob", entity_id=failed_job.id, user=user,
            new_values={"status": "Failed", "transaction_mode": transaction_mode.value, "rolled_back": True},
            description=f"Import job #{failed_job.id} was fully rolled back.",
        )
        db.commit()
        db.refresh(failed_job)
        return failed_job
    db.refresh(job)
    return job


REPORT_TEXT = {
    "en": {
        "headers": ["Row", "Result", "Action", "Error Codes", "Errors"],
    },
    "sq": {
        "headers": ["Rreshti", "Rezultati", "Veprimi", "Kodet e Gabimeve", "Gabimet"],
        "invalid_value": "Vendosni një vlerë të vlefshme.",
        "invalid_license_plate": "Vendosni një targë të vlefshme.",
        "unknown_brand": "Marka duhet të përputhet me Katalogun aktiv të Automjeteve.",
        "unknown_model": "Modeli duhet të përputhet me Katalogun aktiv për markën e zgjedhur.",
        "conflicting_duplicates": "Identifikuesit përputhen me rekorde të ndryshme ekzistuese.",
        "duplicate_in_file": "Ky identifikues paraqitet më shumë se një herë në skedar.",
        "duplicate_existing": "Rreshti përputhet me një rekord ekzistues; kërkohet mënyra e përditësimit.",
        "import_failed": "Rreshti nuk mund të importohej sepse të dhënat ndryshuan pas validimit.",
    },
}


def error_report(job: ImportJob, rows: list[ImportRowResult], language: str = "en") -> bytes:
    language = "sq" if language == "sq" else "en"
    translations = REPORT_TEXT[language]
    raw_headers = list(job.source_headers or [])
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([*translations["headers"], *raw_headers])
    for row in rows:
        if row.status in {"Valid", "Created", "Updated"}:
            continue
        errors = row.errors or []
        writer.writerow([
            row.row_number, row.status, row.action,
            "; ".join(str(item.get("code", "")) for item in errors),
            "; ".join(str(translations.get(str(item.get("code", "")), item.get("message", ""))) for item in errors),
            *(row.raw_data.get(header, "") for header in raw_headers),
        ])
    return output.getvalue().encode("utf-8-sig")
