from __future__ import annotations

from typing import Any

from fastapi import Request

SUPPORTED_LANGUAGES = {"en", "sq"}
DEFAULT_LANGUAGE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "api_error": "The request could not be completed.",
        "validation_error": "Validation failed.",
        "invalid_credentials": "Invalid email or password.",
        "inactive_user": "User account is inactive.",
        "insufficient_permissions": "Insufficient permissions.",
        "vehicle_not_found": "Vehicle not found.",
        "driver_not_found": "Driver not found.",
        "work_order_not_found": "Work order not found.",
        "service_not_found": "Service not found.",
        "inspection_not_found": "Inspection not found.",
        "document_not_found": "Document not found.",
        "fuel_record_not_found": "Fuel or charging record not found.",
        "reservation_not_found": "Reservation not found.",
        "notification_not_found": "Notification not found.",
        "duplicate_license_plate": "This licence plate is already assigned to another vehicle.",
        "invalid_license_plate": "Enter a valid licence plate.",
        "invalid_date": "Enter a valid date.",
        "invalid_odometer": "Enter a valid odometer value.",
        "invalid_quantity": "Enter a valid quantity.",
        "invalid_unit_cost": "Enter a valid unit cost.",
        "reservation_overlap": "This vehicle is already reserved during the selected dates.",
        "file_too_large": "The file is too large.",
        "invalid_file_type": "This file type is not supported.",
        "record_archived": "This record is archived.",
        "record_already_exists": "This record already exists.",
        "work_order_already_completed": "This work order is already completed.",
        "service_already_linked": "A service is already linked to this work order.",
        "unsupported_language": "Select English or Albanian.",
        "invalid_email": "Enter a valid email address.",
        "required": "This field is required.",
        "min_length": "This value is too short.",
        "max_length": "This value is too long.",
        "invalid_value": "Enter a valid value.",
    },
    "sq": {
        "api_error": "Kërkesa nuk mund të përfundohej.",
        "validation_error": "Validimi dështoi.",
        "invalid_credentials": "Email-i ose fjalëkalimi është i pasaktë.",
        "inactive_user": "Llogaria e përdoruesit është joaktive.",
        "insufficient_permissions": "Nuk keni leje të mjaftueshme.",
        "vehicle_not_found": "Automjeti nuk u gjet.",
        "driver_not_found": "Shoferi nuk u gjet.",
        "work_order_not_found": "Urdhri i punës nuk u gjet.",
        "service_not_found": "Servisimi nuk u gjet.",
        "inspection_not_found": "Inspektimi nuk u gjet.",
        "document_not_found": "Dokumenti nuk u gjet.",
        "fuel_record_not_found": "Regjistrimi i karburantit ose karikimit nuk u gjet.",
        "reservation_not_found": "Rezervimi nuk u gjet.",
        "notification_not_found": "Njoftimi nuk u gjet.",
        "duplicate_license_plate": "Kjo targë i është caktuar tashmë një automjeti tjetër.",
        "invalid_license_plate": "Vendosni një targë të vlefshme.",
        "invalid_date": "Vendosni një datë të vlefshme.",
        "invalid_odometer": "Vendosni një vlerë të vlefshme të kilometrazhit.",
        "invalid_quantity": "Vendosni një sasi të vlefshme.",
        "invalid_unit_cost": "Vendosni një kosto të vlefshme për njësi.",
        "reservation_overlap": "Ky automjet është rezervuar tashmë gjatë datave të zgjedhura.",
        "file_too_large": "Skedari është shumë i madh.",
        "invalid_file_type": "Ky lloj skedari nuk mbështetet.",
        "record_archived": "Ky rekord është arkivuar.",
        "record_already_exists": "Ky rekord ekziston tashmë.",
        "work_order_already_completed": "Ky urdhër pune është përfunduar tashmë.",
        "service_already_linked": "Një servisim është lidhur tashmë me këtë urdhër pune.",
        "unsupported_language": "Zgjidhni English ose Shqip.",
        "invalid_email": "Vendosni një adresë email-i të vlefshme.",
        "required": "Kjo fushë është e detyrueshme.",
        "min_length": "Kjo vlerë është shumë e shkurtër.",
        "max_length": "Kjo vlerë është shumë e gjatë.",
        "invalid_value": "Vendosni një vlerë të vlefshme.",
    },
}


def resolve_language(value: str | None) -> str:
    if not value:
        return DEFAULT_LANGUAGE
    for part in value.split(","):
        tag = part.split(";", 1)[0].strip().lower()
        base = tag.split("-", 1)[0]
        if base in SUPPORTED_LANGUAGES:
            return base
    return DEFAULT_LANGUAGE


def request_language(request: Request) -> str:
    return resolve_language(request.headers.get("accept-language"))


def translate(code: str, language: str = DEFAULT_LANGUAGE, params: dict[str, Any] | None = None) -> str:
    template = MESSAGES.get(language, MESSAGES[DEFAULT_LANGUAGE]).get(
        code, MESSAGES[DEFAULT_LANGUAGE].get(code, MESSAGES[DEFAULT_LANGUAGE]["api_error"])
    )
    try:
        return template.format(**(params or {}))
    except (KeyError, ValueError):
        return template
