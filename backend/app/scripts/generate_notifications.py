"""Generate deduplicated in-app notifications for time-based fleet conditions."""

from app.db.session import SessionLocal, clear_tenant_context, set_tenant_context
from app.models import Company
from app.services.notification_generation import generate_time_based_notifications


def main() -> None:
    db = SessionLocal()
    try:
        companies = db.query(Company).filter(Company.is_active.is_(True)).order_by(Company.id).all()
        count = 0
        for company in companies:
            set_tenant_context(db, company.id)
            count += generate_time_based_notifications(db)
            db.commit()
            db.expunge_all()
        clear_tenant_context(db)
        print(f"Notification generation completed for {len(companies)} company(s); {count} new notification(s) created.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
