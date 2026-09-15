"""Tenant-scoped, idempotent scans used by both CLI and the scheduler process."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.api.v1.endpoints.services import current_reminder_status
from app.core.config import get_settings
from app.models import (
    AccidentClaim, CompanySettings, Driver, Inspection, Notification, Part, PartInventory,
    Vehicle, VehicleAccident, VehicleAssignment, VehicleReservation, VehicleService, WorkOrder,
)
from app.schemas import ReminderStatus
from app.services.audit import record_audit
from app.services.document_compliance import compliance_dashboard
from app.services.notifications import ACTIVE_STATUSES, notify_roles, resolve_by_prefix, transition


RECIPIENT_ROLES = {"admin", "fleet_manager"}


def _enabled(db: Session, name: str) -> bool:
    company_id = db.info.get("company_id")
    settings = db.query(CompanySettings).filter(CompanySettings.company_id == company_id).first() if company_id else None
    rules = settings.notification_rules if settings and settings.notification_rules else {}
    return rules.get(name, True) is not False


def scan_maintenance(db: Session, now: datetime) -> None:
    from app.services.service_programs import synchronize_all

    synchronize_all(db, today=now.date())
    if not _enabled(db, "service_reminders"):
        return
    reminders = db.query(VehicleService).options(joinedload(VehicleService.vehicle)).join(Vehicle).filter(
        VehicleService.archived.is_(False), Vehicle.archived.is_(False),
        (VehicleService.next_service_date.isnot(None) | VehicleService.next_service_odometer_km.isnot(None)),
    ).all()
    for reminder in reminders:
        status = current_reminder_status(reminder)
        prefix = f"service-reminder:{reminder.id}:"
        if status not in {ReminderStatus.overdue, ReminderStatus.due, ReminderStatus.due_soon}:
            resolve_by_prefix(db, prefix)
            continue
        overdue = status == ReminderStatus.overdue
        notify_roles(
            db, roles=RECIPIENT_ROLES | {"mechanic"},
            notification_type="Service overdue" if overdue else "Service due soon",
            title=f"{reminder.service_type} {status.value.lower()}",
            message=f"{reminder.vehicle.license_plate} requires {reminder.service_type}.",
            priority="Critical" if overdue else "High" if status == ReminderStatus.due else "Medium",
            entity_type="VehicleService", entity_id=reminder.id,
            deduplication_key=f"{prefix}{status.value.lower().replace(' ', '-')}",
            title_key="modules:notificationContent.service_reminder.title",
            message_key="modules:notificationContent.service_reminder.message",
            message_params={
                "service_type": reminder.service_type, "status": status.value,
                "plate": reminder.vehicle.license_plate,
                "date": reminder.next_service_date.date().isoformat() if reminder.next_service_date else None,
            },
        )


def scan_documents(db: Session, now: datetime) -> None:
    if _enabled(db, "document_expiry"):
        compliance = compliance_dashboard(db, today=now.date())
        active_prefixes: set[str] = set()
        for item in compliance["items"]:
            prefix = f"document-compliance:{item['requirement_id']}:{item['owner_type'].lower()}:{item['owner_id']}:"
            if item["status"] not in {"Missing", "Expired", "Expiring Soon", "Renewal In Progress", "Rejected"}:
                resolve_by_prefix(db, prefix)
                continue
            active_prefixes.add(prefix)
            status = item["status"]
            expiry_message = f" Expiry date: {item['expiry_date']}." if item["expiry_date"] else ""
            priority = "Critical" if status in {"Missing", "Expired", "Rejected"} else "High" if status == "Expiring Soon" else "Medium"
            notify_roles(
                db, roles=RECIPIENT_ROLES, notification_type=f"Document compliance {status.lower()}",
                title=f"{item['document_type']}: {status}", message=f"{item['owner_name']}.{expiry_message}",
                priority=priority, entity_type="VehiclePaper" if item["document_id"] else "DocumentRequirement",
                entity_id=item["document_id"] or item["requirement_id"], deduplication_key=f"{prefix}alert",
                title_key="modules:notificationContent.document_compliance.title",
                message_key="modules:notificationContent.document_compliance.message",
                message_params={
                    "document_type": item["document_type"], "status": status,
                    "owner": item["owner_name"], "date": item["expiry_date"] or "-",
                },
            )
        for notification in db.query(Notification).filter(
            Notification.deduplication_key.like("document-compliance:%"), Notification.status.in_(ACTIVE_STATUSES),
        ).all():
            if not any(notification.deduplication_key.startswith(prefix) for prefix in active_prefixes):
                transition(notification, "Resolved")

    if not _enabled(db, "driver_license_expiry"):
        return
    for driver in db.query(Driver).filter(Driver.archived.is_(False)).all():
        days = (driver.license_expiry_date.date() - now.date()).days
        if days > 30:
            resolve_by_prefix(db, f"driver-license:{driver.id}:")
            continue
        expired = days < 0
        notify_roles(
            db, roles=RECIPIENT_ROLES,
            notification_type="Driver licence expired" if expired else "Driver licence expiring",
            title=f"{driver.full_name}'s licence {'expired' if expired else 'expires soon'}",
            message=driver.license_expiry_date.date().isoformat(), priority="Critical" if expired else "High",
            entity_type="Driver", entity_id=driver.id,
            deduplication_key=f"driver-license:{driver.id}:{'expired' if expired else 'expires-30-days'}",
            title_key="modules:notificationContent.driver_licence.title",
            message_key="modules:notificationContent.driver_licence.message",
            message_params={
                "name": driver.full_name, "status": "Overdue" if expired else "Due Soon",
                "date": driver.license_expiry_date.date().isoformat(),
            },
        )


def scan_work_and_reservations(db: Session, now: datetime) -> None:
    from app.services.inspection_templates import generate_scheduled

    generate_scheduled(db, now)
    failed_inspections = db.query(Inspection).filter(Inspection.archived.is_(False), Inspection.overall_status == "Failed").all()
    failed_ids = {row.id for row in failed_inspections}
    for inspection in failed_inspections:
        notify_roles(
            db, roles=RECIPIENT_ROLES | {"mechanic"}, notification_type="Inspection failed",
            title=f"Inspection #{inspection.id} failed", message=f"Vehicle #{inspection.vehicle_id} requires attention.",
            priority="High", entity_type="Inspection", entity_id=inspection.id,
            deduplication_key=f"inspection:{inspection.id}:failed",
            message_params={"id": inspection.id, "vehicle_id": inspection.vehicle_id},
        )
    for notification in db.query(Notification).filter(
        Notification.deduplication_key.like("inspection:%:failed:user:%"), Notification.status.in_(ACTIVE_STATUSES),
    ).all():
        parts = notification.deduplication_key.split(":")
        if len(parts) > 1 and parts[1].isdigit() and int(parts[1]) not in failed_ids:
            transition(notification, "Resolved")

    open_statuses = ["Open", "Assigned", "In Progress", "Waiting for Parts"]
    active_orders = db.query(WorkOrder).filter(WorkOrder.archived.is_(False), WorkOrder.status.in_(open_statuses)).all()
    active_order_ids = {order.id for order in active_orders}
    for order in active_orders:
        if order.priority == "Critical":
            notify_roles(
                db, roles=RECIPIENT_ROLES | {"mechanic"}, notification_type="Critical Work Order created",
                title=f"Critical Work Order #{order.id}", message=order.title, priority="Critical",
                entity_type="WorkOrder", entity_id=order.id, deduplication_key=f"work-order:{order.id}:critical",
                message_params={"id": order.id, "title": order.title},
            )
        if order.expected_completion_date and order.expected_completion_date < now and _enabled(db, "work_order_overdue"):
            notify_roles(
                db, roles=RECIPIENT_ROLES | {"mechanic"}, notification_type="Work Order overdue",
                title=f"Work Order #{order.id} is overdue", message=order.title,
                priority="Critical" if order.priority == "Critical" else "High",
                entity_type="WorkOrder", entity_id=order.id, deduplication_key=f"work-order:{order.id}:overdue",
                title_key="modules:notificationContent.work_order_overdue.title",
                message_key="modules:notificationContent.work_order_overdue.message",
                message_params={"id": order.id, "title": order.title, "date": order.expected_completion_date.date().isoformat()},
            )
    for order in db.query(WorkOrder).filter(~WorkOrder.id.in_(active_order_ids or {-1})).all():
        resolve_by_prefix(db, f"work-order:{order.id}:overdue")
        resolve_by_prefix(db, f"work-order:{order.id}:critical")

    if not _enabled(db, "reservations"):
        return
    reservations = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle)).join(Vehicle).filter(
        VehicleReservation.archived.is_(False), Vehicle.archived.is_(False),
    ).all()
    for reservation in reservations:
        if reservation.status == 0:
            notify_roles(
                db, roles=RECIPIENT_ROLES, notification_type="Reservation pending approval",
                title=f"Reservation #{reservation.id} awaits approval",
                message=f"{reservation.vehicle.license_plate} for {reservation.reserved_by}", priority="Medium",
                entity_type="VehicleReservation", entity_id=reservation.id,
                deduplication_key=f"reservation:{reservation.id}:pending",
                title_key="modules:notificationContent.reservation_pending.title",
                message_key="modules:notificationContent.reservation.message",
                message_params={
                    "id": reservation.id, "plate": reservation.vehicle.license_plate,
                    "reserved_by": reservation.reserved_by, "date": reservation.start_date.isoformat(),
                },
            )
        if reservation.status == 1 and now <= reservation.start_date <= now + timedelta(hours=24):
            notify_roles(
                db, roles=RECIPIENT_ROLES, notification_type="Reservation starting soon",
                title=f"Reservation #{reservation.id} starts soon",
                message=f"{reservation.vehicle.license_plate} for {reservation.reserved_by}", priority="Medium",
                entity_type="VehicleReservation", entity_id=reservation.id,
                deduplication_key=f"reservation:{reservation.id}:starts-24-hours",
                title_key="modules:notificationContent.reservation_starting.title",
                message_key="modules:notificationContent.reservation.message",
                message_params={
                    "id": reservation.id, "plate": reservation.vehicle.license_plate,
                    "reserved_by": reservation.reserved_by, "date": reservation.start_date.isoformat(),
                },
            )
        if reservation.status == 1 and reservation.end_date < now:
            notify_roles(
                db, roles=RECIPIENT_ROLES, notification_type="Reservation overdue for return",
                title=f"Reservation #{reservation.id} is overdue",
                message=f"{reservation.vehicle.license_plate} should have been returned.", priority="High",
                entity_type="VehicleReservation", entity_id=reservation.id,
                deduplication_key=f"reservation:{reservation.id}:overdue-return",
                title_key="modules:notificationContent.reservation_overdue.title",
                message_key="modules:notificationContent.reservation_return.message",
                message_params={"id": reservation.id, "plate": reservation.vehicle.license_plate, "date": reservation.end_date.isoformat()},
            )


def scan_overdue_returns(db: Session, now: datetime) -> None:
    if not _enabled(db, "overdue_assignments"):
        return
    overdue = db.query(VehicleAssignment).options(
        joinedload(VehicleAssignment.vehicle), joinedload(VehicleAssignment.driver),
    ).join(VehicleAssignment.vehicle).join(VehicleAssignment.driver).filter(
        VehicleAssignment.archived.is_(False), VehicleAssignment.status == "Active",
        VehicleAssignment.end_datetime.isnot(None), VehicleAssignment.end_datetime < now,
        Vehicle.archived.is_(False), Driver.archived.is_(False),
    ).all()
    for assignment in overdue:
        assignment.status = "Overdue"
        assignment.updated_at = now
        record_audit(
            db, action="Vehicle Assignment overdue", entity_type="VehicleAssignment", entity_id=assignment.id,
            new_values={"status": "Overdue"}, description=f"Assignment #{assignment.id} is overdue for return.",
        )
        notify_roles(
            db, roles=RECIPIENT_ROLES, notification_type="Vehicle return overdue",
            title=f"Assignment #{assignment.id} is overdue",
            message=f"{assignment.vehicle.license_plate} · {assignment.driver.full_name}", priority="High",
            entity_type="VehicleAssignment", entity_id=assignment.id,
            deduplication_key=f"vehicle-usage:{assignment.id}:return-overdue",
            title_key="modules:notificationContent.vehicle_return_overdue.title",
            message_key="modules:notificationContent.vehicle_return_overdue.message",
            message_params={
                "id": assignment.id, "plate": assignment.vehicle.license_plate,
                "driver": assignment.driver.full_name, "date": assignment.end_datetime.isoformat(),
            },
        )


def scan_low_stock(db: Session, _now: datetime) -> None:
    if not _enabled(db, "low_stock"):
        return
    from app.services.maintenance_supply import refresh_low_stock

    balances = db.query(PartInventory).options(
        joinedload(PartInventory.part), joinedload(PartInventory.location),
    ).join(Part).filter(Part.archived.is_(False), Part.is_active.is_(True)).all()
    for balance in balances:
        refresh_low_stock(db, balance.part, balance)


def scan_claims(db: Session, now: datetime) -> None:
    if not _enabled(db, "insurance_claims"):
        return
    threshold = now - timedelta(days=get_settings().claim_reminder_after_days)
    claims = db.query(AccidentClaim).options(
        joinedload(AccidentClaim.accident).joinedload(VehicleAccident.vehicle),
    ).join(AccidentClaim.accident).filter(
        AccidentClaim.claim_status.notin_(["Closed", "Rejected"]),
        AccidentClaim.claim_opened_date <= threshold, VehicleAccident.archived.is_(False),
    ).all()
    active_ids = {claim.id for claim in claims}
    for claim in claims:
        notify_roles(
            db, roles=RECIPIENT_ROLES | {"finance"}, notification_type="Insurance claim reminder",
            title=f"Insurance claim {claim.claim_number} needs attention",
            message=f"Accident #{claim.accident_id} · {claim.claim_status}", priority="High",
            entity_type="VehicleAccident", entity_id=claim.accident_id,
            deduplication_key=f"claim:{claim.id}:open-reminder",
            message_params={
                "id": claim.accident_id, "plate": claim.accident.vehicle.license_plate,
                "date": claim.claim_opened_date.date().isoformat(),
            },
        )
    for notification in db.query(Notification).filter(
        Notification.deduplication_key.like("claim:%:open-reminder:user:%"), Notification.status.in_(ACTIVE_STATUSES),
    ).all():
        parts = notification.deduplication_key.split(":")
        if len(parts) > 1 and parts[1].isdigit() and int(parts[1]) not in active_ids:
            transition(notification, "Resolved")


SCAN_FUNCTIONS = {
    "notification_scan": scan_work_and_reservations,
    "document_compliance_scan": scan_documents,
    "maintenance_reminder_scan": scan_maintenance,
    "overdue_return_scan": scan_overdue_returns,
    "low_stock_scan": scan_low_stock,
    "insurance_claim_scan": scan_claims,
}


def generate_time_based_notifications(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    before = db.query(Notification).count()
    for scan in SCAN_FUNCTIONS.values():
        scan(db, now)
    db.flush()
    return db.query(Notification).count() - before
