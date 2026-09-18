"""Process boundaries and audit records for recurring tenant jobs."""

from datetime import datetime
import logging

from app.db.session import SessionLocal, set_tenant_context
from app.models import Company, Notification
from app.services.audit import record_audit
from app.services.notification_delivery import deliver_pending_emails
from app.services.notification_generation import SCAN_FUNCTIONS


logger = logging.getLogger(__name__)


def _active_company_ids() -> list[int]:
    db = SessionLocal()
    try:
        return [company_id for (company_id,) in db.query(Company.id).filter(Company.is_active.is_(True)).order_by(Company.id).all()]
    finally:
        db.close()


def run_scheduled_job(job_name: str, now: datetime | None = None) -> dict[str, int]:
    """Run one named job independently for every active tenant."""
    if job_name not in {"email_delivery", "webhook_delivery"} and job_name not in SCAN_FUNCTIONS:
        raise ValueError(f"Unknown scheduled job: {job_name}")
    now = now or datetime.utcnow()
    summary = {"companies": 0, "created": 0, "sent": 0, "failed_companies": 0}
    for company_id in _active_company_ids():
        db = SessionLocal()
        set_tenant_context(db, company_id)
        try:
            before = db.query(Notification).count()
            details = deliver_pending_emails(db, now=now) if job_name == "email_delivery" else None
            if job_name == "webhook_delivery":
                from app.services.webhooks import deliver_pending
                details = deliver_pending(db, now=now)
            if job_name == "document_compliance_scan":
                from app.services.webhooks import scan_expiring_documents
                scan_expiring_documents(db, now)
            if job_name not in {"email_delivery", "webhook_delivery"}:
                SCAN_FUNCTIONS[job_name](db, now)
            db.flush()
            created = db.query(Notification).count() - before
            sent = (details or {}).get("sent", 0)
            record_audit(
                db, action="Scheduled notification job completed", entity_type="ScheduledJob", entity_id=None,
                new_values={"job_name": job_name, "created": created, **(details or {})},
                description=f"Scheduled job {job_name} completed for company #{company_id}.",
            )
            db.commit()
            summary["companies"] += 1
            summary["created"] += created
            summary["sent"] += sent
        except Exception as exc:
            db.rollback()
            summary["failed_companies"] += 1
            logger.exception("Scheduled job %s failed for company %s", job_name, company_id)
            try:
                record_audit(
                    db, action="Scheduled notification job failed", entity_type="ScheduledJob", entity_id=None,
                    new_values={"job_name": job_name, "error": str(exc)[:500]},
                    description=f"Scheduled job {job_name} failed for company #{company_id}.",
                )
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Could not persist failed-job audit for company %s", company_id)
        finally:
            db.close()
    return summary
