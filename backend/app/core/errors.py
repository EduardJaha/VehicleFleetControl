from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.i18n import request_language, translate

RESOURCE_CODES = (
    ("/notifications", "notification_not_found"),
    ("/vehicle-assignments", "vehicle_assignment_not_found"),
    ("/work-orders", "work_order_not_found"),
    ("/inspections", "inspection_not_found"),
    ("/reservations", "reservation_not_found"),
    ("/services", "service_not_found"),
    ("/drivers", "driver_not_found"),
    ("/vehicles", "vehicle_not_found"),
    ("/papers", "document_not_found"),
    ("/fuel", "fuel_record_not_found"),
)


def infer_error_code(status_code: int, path: str) -> str:
    """Map legacy unstructured exceptions without inspecting their English text."""
    if status_code == 401:
        return "invalid_credentials"
    if status_code == 403:
        return "insufficient_permissions"
    if status_code == 404:
        for prefix, code in RESOURCE_CODES:
            if prefix in path:
                return code
        return "api_error"
    if status_code == 415:
        return "invalid_file_type"
    if status_code == 409:
        if "/reservations" in path:
            return "reservation_overlap"
        if "/vehicles" in path:
            return "duplicate_license_plate"
        return "record_already_exists"
    if status_code in {400, 422}:
        return "invalid_value"
    return "api_error"


def localized_http_exception(
    status_code: int,
    code: str,
    *,
    language: str = "en",
    params: dict[str, Any] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": translate(code, language, params), "params": params or {}},
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    language = request_language(request)
    if isinstance(exc.detail, dict) and isinstance(exc.detail.get("code"), str):
        code = exc.detail["code"]
        params = exc.detail.get("params") if isinstance(exc.detail.get("params"), dict) else {}
        message = translate(code, language, params)
    else:
        fallback = str(exc.detail)
        code = infer_error_code(exc.status_code, request.url.path)
        params = {}
        message = translate(code, language)
        if code == "api_error" and language == "en":
            message = fallback
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": message, "params": params},
        headers=exc.headers,
    )


def validation_code(error_type: str, message: str) -> str:
    normalized = error_type.lower()
    if "missing" in normalized:
        return "required"
    if "email" in normalized or "email" in message.lower():
        return "invalid_email"
    if "too_short" in normalized or "min_length" in normalized:
        return "min_length"
    if "too_long" in normalized or "max_length" in normalized:
        return "max_length"
    if "date" in normalized:
        return "invalid_date"
    return "invalid_value"


async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    language = request_language(request)
    field_errors: list[dict[str, Any]] = []
    for issue in exc.errors():
        location = [str(part) for part in issue.get("loc", ()) if str(part) not in {"body", "query", "path"}]
        code = validation_code(str(issue.get("type", "")), str(issue.get("msg", "")))
        context = issue.get("ctx") if isinstance(issue.get("ctx"), dict) else {}
        safe_params = {
            key: value for key, value in context.items()
            if isinstance(value, (str, int, float, bool)) and key not in {"error", "input"}
        }
        field_errors.append({"field": ".".join(location), "code": code, "params": safe_params})
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": translate("validation_error", language),
            "field_errors": field_errors,
        },
    )
