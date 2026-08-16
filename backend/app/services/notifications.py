from datetime import datetime
import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CompanyUser, Notification, User

ACTIVE_STATUSES = {"Unread", "Read"}


def notification_key(notification_type: str, part: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", notification_type.lower()).strip("_")
    return f"modules:notificationContent.{slug}.{part}"


def notify_user(
    db: Session,
    *,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    priority: str,
    entity_type: str | None,
    entity_id: int | None,
    deduplication_key: str,
    title_key: str | None = None,
    message_key: str | None = None,
    message_params: dict | None = None,
) -> Notification:
    existing = db.query(Notification).filter(
        Notification.deduplication_key == deduplication_key,
    ).first()
    if existing:
        existing.notification_type = notification_type
        existing.title = title
        existing.message = message
        existing.title_key = title_key or notification_key(notification_type, "title")
        existing.message_key = message_key or notification_key(notification_type, "message")
        existing.message_params = message_params or {}
        existing.priority = priority
        existing.entity_type = entity_type
        existing.entity_id = entity_id
        if existing.status in {"Resolved", "Dismissed"}:
            existing.status = "Unread"
            existing.read_at = None
            existing.resolved_at = None
            existing.dismissed_at = None
        return existing

    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        title_key=title_key or notification_key(notification_type, "title"),
        message_key=message_key or notification_key(notification_type, "message"),
        message_params=message_params or {},
        priority=priority,
        entity_type=entity_type,
        entity_id=entity_id,
        deduplication_key=deduplication_key,
    )
    db.add(notification)
    return notification


def notify_roles(
    db: Session,
    *,
    roles: set[str],
    notification_type: str,
    title: str,
    message: str,
    priority: str,
    entity_type: str | None,
    entity_id: int | None,
    deduplication_key: str,
    title_key: str | None = None,
    message_key: str | None = None,
    message_params: dict | None = None,
) -> list[Notification]:
    company_id = db.info.get("company_id")
    if company_id is None:
        users = db.query(User).filter(User.is_active.is_(True), User.role.in_(roles)).all()
    else:
        member_ids = db.query(CompanyUser.user_id).filter(
            CompanyUser.company_id == company_id,
            CompanyUser.is_active.is_(True),
            CompanyUser.role.in_(roles),
        )
        users = db.query(User).execution_options(skip_tenant_scope=True).filter(
            User.id.in_(member_ids),
            User.is_active.is_(True),
        ).all()
    return [
        notify_user(
            db,
            user_id=user.id,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            entity_type=entity_type,
            entity_id=entity_id,
            deduplication_key=f"{deduplication_key}:user:{user.id}",
            title_key=title_key,
            message_key=message_key,
            message_params=message_params,
        )
        for user in users
    ]


def transition(notification: Notification, status: str) -> None:
    now = datetime.utcnow()
    notification.status = status
    if status == "Read":
        notification.read_at = notification.read_at or now
    elif status == "Resolved":
        notification.read_at = notification.read_at or now
        notification.resolved_at = now
    elif status == "Dismissed":
        notification.read_at = notification.read_at or now
        notification.dismissed_at = now


def resolve_by_prefix(db: Session, prefix: str) -> int:
    rows = db.query(Notification).filter(
        Notification.deduplication_key.like(f"{prefix}%"),
        Notification.status.in_(ACTIVE_STATUSES),
    ).all()
    for row in rows:
        transition(row, "Resolved")
    return len(rows)
