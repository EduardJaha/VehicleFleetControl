"""Generate deduplicated in-app notifications for time-based fleet conditions."""

from app.db.session import SessionLocal
from app.services.notification_generation import generate_time_based_notifications


def main() -> None:
    db = SessionLocal()
    try:
        count = generate_time_based_notifications(db)
        db.commit()
        print(f"Notification generation completed; {count} new notification(s) created.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
