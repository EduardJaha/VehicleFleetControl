from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
import re

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from app.models import AuditLog, User

SENSITIVE_KEYS = {
    "credentials_reference",
    "key_hash",
    "raw_key",
    "password",
    "hashed_password",
    "password_hash",
    "secret",
    "secret_key",
    "jwt",
    "token",
    "access_token",
    "authorization",
    "cookie",
}


def _safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def redact(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    safe: dict[str, Any] = {}
    for key, value in values.items():
        normalized = key.lower().replace("-", "_")
        if normalized in SENSITIVE_KEYS or any(part in normalized for part in ("password", "secret", "token", "authorization")):
            continue
        if isinstance(value, dict):
            safe[key] = redact(value)
        elif isinstance(value, list):
            safe[key] = [redact(item) if isinstance(item, dict) else _safe_value(item) for item in value]
        else:
            safe[key] = _safe_value(value)
    return safe


def snapshot(entity: Any, fields: tuple[str, ...] | None = None) -> dict[str, Any]:
    mapper = sqlalchemy_inspect(entity.__class__)
    names = fields or tuple(attribute.key for attribute in mapper.column_attrs)
    return redact({name: getattr(entity, name, None) for name in names}) or {}


def record_audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: int | None,
    user: User | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    description: str | None = None,
    action_code: str | None = None,
    description_key: str | None = None,
    description_params: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    stable_action = action_code or re.sub(r"[^a-z0-9]+", "_", action.lower()).strip("_")
    log = AuditLog(
        user_id=user.id if user else None,
        username=user.email if user else "System",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=redact(old_values),
        new_values=redact(new_values),
        description=description,
        action_code=stable_action,
        description_key=description_key or f"modules:auditDescriptions.{stable_action}",
        description_params=redact(description_params) or {
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
        ip_address=ip_address,
    )
    db.add(log)
    return log
