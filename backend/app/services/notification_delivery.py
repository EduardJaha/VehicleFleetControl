"""Durable, retryable delivery of notification channels."""

from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings, get_settings
from app.models import Notification, NotificationDelivery, User
from app.services.audit import record_audit
from app.services.email import EmailService, render_notification_email
from app.services.notifications import ACTIVE_STATUSES


def deliver_pending_emails(
    db: Session,
    *,
    now: datetime | None = None,
    email_service: EmailService | None = None,
    settings: Settings | None = None,
    batch_size: int = 100,
) -> dict[str, int]:
    now = now or datetime.utcnow()
    settings = settings or get_settings()
    email_service = email_service or EmailService(settings)
    metrics = {"sent": 0, "failed": 0, "retrying": 0, "cancelled": 0}

    inactive = db.query(NotificationDelivery).join(NotificationDelivery.notification).filter(
        NotificationDelivery.channel == "Email",
        NotificationDelivery.status.in_(["Pending", "Retrying"]),
        Notification.status.notin_(ACTIVE_STATUSES),
    ).all()
    for delivery in inactive:
        delivery.status = "Failed"
        delivery.failure_reason = "Notification resolved before delivery."
        delivery.next_attempt_at = None
        metrics["cancelled"] += 1
        record_audit(
            db, action="Notification email cancelled", entity_type="NotificationDelivery", entity_id=delivery.id,
            new_values={"status": delivery.status, "attempt_count": delivery.attempt_count},
            description=f"Email delivery for notification #{delivery.notification_id} was cancelled after resolution.",
        )

    deliveries = db.query(NotificationDelivery).options(
        joinedload(NotificationDelivery.notification)
    ).join(NotificationDelivery.notification).filter(
        NotificationDelivery.channel == "Email",
        NotificationDelivery.status.in_(["Pending", "Retrying"]),
        Notification.status.in_(ACTIVE_STATUSES),
        (NotificationDelivery.next_attempt_at.is_(None) | (NotificationDelivery.next_attempt_at <= now)),
    ).order_by(NotificationDelivery.created_at, NotificationDelivery.id).limit(batch_size).all()

    for delivery in deliveries:
        notification = delivery.notification
        user = db.query(User).execution_options(skip_tenant_scope=True).filter(
            User.id == notification.user_id,
            User.is_active.is_(True),
        ).first()
        if user is None:
            delivery.status = "Failed"
            delivery.failure_reason = "Notification recipient is inactive or missing."
            delivery.next_attempt_at = None
            metrics["failed"] += 1
            record_audit(
                db, action="Notification email failed", entity_type="NotificationDelivery", entity_id=delivery.id,
                new_values={"status": delivery.status, "attempt_count": delivery.attempt_count},
                description=f"Email delivery for notification #{notification.id}: Failed.",
            )
            continue
        delivery.attempt_count += 1
        delivery.last_attempt = now
        try:
            subject, text_body, html_body = render_notification_email(
                notification,
                user.preferred_language or "en",
                settings.frontend_url,
            )
            email_service.send(
                recipient=delivery.recipient,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                message_id=f"<{sha256(notification.deduplication_key.encode()).hexdigest()}@vehiclefleetcontrol>",
            )
            delivery.status = "Sent"
            delivery.sent_at = now
            delivery.next_attempt_at = None
            delivery.failure_reason = None
            metrics["sent"] += 1
        except Exception as exc:  # transport failures must remain durable and retryable
            delivery.failure_reason = str(exc)[:1000]
            if delivery.attempt_count >= settings.email_max_attempts:
                delivery.status = "Failed"
                delivery.next_attempt_at = None
                metrics["failed"] += 1
            else:
                delivery.status = "Retrying"
                delay = settings.email_retry_base_minutes * (2 ** (delivery.attempt_count - 1))
                delivery.next_attempt_at = now + timedelta(minutes=delay)
                metrics["retrying"] += 1
        record_audit(
            db,
            action=f"Notification email {delivery.status.lower()}",
            entity_type="NotificationDelivery",
            entity_id=delivery.id,
            new_values={"status": delivery.status, "attempt_count": delivery.attempt_count},
            description=f"Email delivery for notification #{notification.id}: {delivery.status}.",
        )
    db.flush()
    return metrics
