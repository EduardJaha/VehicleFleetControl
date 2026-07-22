from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import Notification, User
from app.schemas import (
    NotificationOut,
    NotificationPage,
    NotificationPriority,
    NotificationStatus,
    NotificationUnreadCount,
)
from app.services.notifications import transition
from app.utils.dates import parse_date

router = APIRouter()


def notification_out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        notification_type=row.notification_type,
        title=row.title,
        message=row.message,
        title_key=row.title_key,
        message_key=row.message_key,
        message_params=row.message_params,
        priority=NotificationPriority(row.priority),
        status=NotificationStatus(row.status),
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        created_at=row.created_at.isoformat(),
        read_at=row.read_at.isoformat() if row.read_at else None,
        resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
        dismissed_at=row.dismissed_at.isoformat() if row.dismissed_at else None,
    )


def owned_notification(db: Session, notification_id: int, user: User) -> Notification:
    row = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return row


@router.get("", response_model=NotificationPage)
def list_notifications(
    status: NotificationStatus | None = None,
    priority: NotificationPriority | None = None,
    notification_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page must be at least 1 and page_size must be between 1 and 100.")
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if status:
        query = query.filter(Notification.status == status.value)
    if priority:
        query = query.filter(Notification.priority == priority.value)
    if notification_type:
        query = query.filter(Notification.notification_type == notification_type)
    if from_date:
        query = query.filter(Notification.created_at >= parse_date(from_date, "from_date"))
    if to_date:
        query = query.filter(Notification.created_at <= parse_date(to_date, "to_date"))
    total = query.order_by(None).count()
    rows = query.order_by(Notification.created_at.desc(), Notification.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return NotificationPage(
        items=[notification_out(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/unread-count", response_model=NotificationUnreadCount)
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.status == NotificationStatus.unread.value,
    ).count()
    return NotificationUnreadCount(unread_count=count)


@router.put("/read-all")
def read_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.status == NotificationStatus.unread.value,
    ).all()
    now = datetime.utcnow()
    for row in rows:
        row.status = NotificationStatus.read.value
        row.read_at = now
    db.commit()
    return {"message": f"{len(rows)} notification(s) marked as read."}


def _transition_endpoint(notification_id: int, target: str, db: Session, current_user: User) -> NotificationOut:
    row = owned_notification(db, notification_id, current_user)
    transition(row, target)
    db.commit()
    return notification_out(row)


@router.put("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _transition_endpoint(notification_id, NotificationStatus.read.value, db, current_user)


@router.put("/{notification_id}/resolve", response_model=NotificationOut)
def resolve(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _transition_endpoint(notification_id, NotificationStatus.resolved.value, db, current_user)


@router.put("/{notification_id}/dismiss", response_model=NotificationOut)
def dismiss(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _transition_endpoint(notification_id, NotificationStatus.dismissed.value, db, current_user)
