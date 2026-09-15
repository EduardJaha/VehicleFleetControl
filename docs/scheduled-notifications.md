# Scheduled notifications and email delivery

VehicleFleetControl runs recurring notification work in a dedicated process:

```text
API process(es) -> Notifications + durable delivery rows -> database
Scheduler (one replica) -> tenant scans + email delivery/retry -> SMTP or console
```

The API never starts a scheduler. This prevents every API worker from registering the same jobs. Production must run exactly one `scheduler` container/process (`python -m app.scripts.scheduler`). Notification and delivery unique constraints remain the final defense against duplicate work. The Compose configuration includes this separate service and waits for migrations/API health before starting it.

Jobs are isolated by active company. Each company uses a fresh tenant-scoped database session and transaction; one tenant failure does not stop another tenant. Successful and failed company runs are written to the audit log. Scans ignore archived operational entities, update existing notifications by stable deduplication key, and resolve alerts when their underlying condition clears.

Default schedules:

- operational notification scan: 15 minutes
- document and driver-licence compliance: 24 hours
- service and maintenance-program reminders: 60 minutes
- overdue vehicle return: 15 minutes
- low stock: 60 minutes
- insurance claim reminders: 24 hours
- pending email delivery: 1 minute

All intervals and retry limits are configured in `backend/.env.example`. Event-driven alerts such as failed inspections and critical work orders are still created immediately by the API; the same email delivery queue handles them. Scheduled scans also reconcile these conditions in case an event was imported or missed.

Email defaults to `EMAIL_BACKEND=console` for development. `mock` keeps messages in an in-memory outbox for tests. Set `EMAIL_BACKEND=smtp` and the `SMTP_*` values for production. Secrets belong in deployment environment variables, never source control. Email preferences default to in-app enabled and email disabled, so users opt into external delivery. The delivery table records Pending, Sent, Retrying, and Failed states with bounded exponential backoff. Each logical email has one database delivery row and a deterministic SMTP `Message-ID` derived from the notification deduplication key. The channel field is intentionally extensible for future Push/SMS implementations.

The legacy one-shot command remains available for maintenance and creates the same deduplicated records:

```bash
cd backend
python -m app.scripts.generate_notifications
```
