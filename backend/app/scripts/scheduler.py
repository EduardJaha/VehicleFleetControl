"""Dedicated APScheduler process. Run exactly one replica in production."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import get_settings
from app.services.scheduled_jobs import run_scheduled_job


from app.core.observability import configure_logging
configure_logging()


def build_scheduler() -> BlockingScheduler:
    settings = get_settings()
    scheduler = BlockingScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300})
    jobs = (
        ("notification_scan", settings.notification_scan_interval_minutes),
        ("maintenance_reminder_scan", settings.maintenance_scan_interval_minutes),
        ("overdue_return_scan", settings.overdue_return_scan_interval_minutes),
        ("low_stock_scan", settings.low_stock_scan_interval_minutes),
        ("insurance_claim_scan", settings.claim_scan_interval_minutes),
        ("email_delivery", settings.email_delivery_interval_minutes),
    )
    for job_name, minutes in jobs:
        scheduler.add_job(run_scheduled_job, "interval", minutes=minutes, args=[job_name], id=job_name, replace_existing=True)
    scheduler.add_job(
        run_scheduled_job, "interval", hours=settings.document_scan_interval_hours,
        args=["document_compliance_scan"], id="document_compliance_scan", replace_existing=True,
    )
    return scheduler


def main() -> None:
    from app.core.deployment import validate_deployment
    validate_deployment()
    scheduler = build_scheduler()
    for job_name in (
        "notification_scan", "document_compliance_scan", "maintenance_reminder_scan",
        "overdue_return_scan", "low_stock_scan", "insurance_claim_scan", "email_delivery",
    ):
        run_scheduled_job(job_name)
    scheduler.start()


if __name__ == "__main__":
    main()
