from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.db.session import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogOut, AuditLogPage, UserRole
from app.utils.dates import parse_date

router = APIRouter()


def audit_out(row: AuditLog) -> AuditLogOut:
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return AuditLogOut(
        id=row.id,
        user_id=row.user_id,
        username=row.username,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        old_values=row.old_values,
        new_values=row.new_values,
        description=row.description,
        action_code=row.action_code,
        description_key=row.description_key,
        description_params=row.description_params,
        ip_address=row.ip_address,
        created_at=created_at.isoformat(),
    )


@router.get("", response_model=AuditLogPage)
def list_audit_logs(
    user_id: int | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin, UserRole.fleet_manager)),
):
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page must be at least 1 and page_size must be between 1 and 100.")
    query = db.query(AuditLog)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action.strip()}%"))
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)
    if from_date:
        query = query.filter(AuditLog.created_at >= parse_date(from_date, "from_date"))
    if to_date:
        query = query.filter(AuditLog.created_at <= parse_date(to_date, "to_date"))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(
            AuditLog.username.ilike(term),
            AuditLog.action.ilike(term),
            AuditLog.entity_type.ilike(term),
            AuditLog.description.ilike(term),
        ))
    total = query.order_by(None).count()
    rows = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return AuditLogPage(
        items=[audit_out(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
        pages=(total + page_size - 1) // page_size,
    )
