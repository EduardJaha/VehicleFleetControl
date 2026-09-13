from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.api.v1.endpoints.services import current_reminder_status
from app.models import Part, PartInventory, CompanySettings, Driver, Notification, VehicleAssignment, VehiclePaper, VehicleReservation, VehicleService, WorkOrder
from app.schemas import ReminderStatus
from app.services.audit import record_audit
from app.services.notifications import ACTIVE_STATUSES, notify_roles, resolve_by_prefix, transition
from app.services.document_compliance import compliance_dashboard

RECIPIENT_ROLES = {"admin", "fleet_manager"}


def generate_time_based_notifications(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    notification_count_before = db.query(Notification).count()
    settings = None
    if db.info.get("company_id") is not None:
        settings = db.query(CompanySettings).filter(CompanySettings.company_id == db.info["company_id"]).first()
    rules = settings.notification_rules if settings and settings.notification_rules else {}

    def enabled(name: str) -> bool:
        return rules.get(name, True) is not False

    if enabled("low_stock"):
        from app.services.maintenance_supply import refresh_low_stock
        balances = db.query(PartInventory).options(joinedload(PartInventory.part), joinedload(PartInventory.location)).join(Part).filter(Part.archived.is_(False), Part.is_active.is_(True)).all()
        for balance in balances:
            refresh_low_stock(db, balance.part, balance)

    reminders = db.query(VehicleService).options(joinedload(VehicleService.vehicle)).filter(
        VehicleService.archived.is_(False),
        (VehicleService.next_service_date.isnot(None) | VehicleService.next_service_odometer_km.isnot(None)),
    ).all() if enabled("service_reminders") else []
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
            message_params={"service_type": reminder.service_type, "status": status.value, "plate": reminder.vehicle.license_plate},
        )

    compliance = compliance_dashboard(db, today=now.date()) if enabled("document_expiry") else {"items": []}
    active_compliance_keys: set[str] = set()
    for item in compliance["items"]:
        prefix = (
            f"document-compliance:{item['requirement_id']}:"
            f"{item['owner_type'].lower()}:{item['owner_id']}:"
        )
        if item["status"] not in {"Missing", "Expired", "Expiring Soon", "Renewal In Progress", "Rejected"}:
            resolve_by_prefix(db, prefix)
            continue
        active_compliance_keys.add(f"{prefix}alert")
        status = item["status"]
        expiry_message = f" Expiry date: {item['expiry_date']}." if item["expiry_date"] else ""
        priority = "Critical" if status in {"Missing", "Expired", "Rejected"} else "High" if status == "Expiring Soon" else "Medium"
        notify_roles(
            db, roles=RECIPIENT_ROLES,
            notification_type=f"Document compliance {status.lower()}",
            title=f"{item['document_type']}: {status}",
            message=f"{item['owner_name']}.{expiry_message}",
            priority=priority,
            entity_type="VehiclePaper" if item["document_id"] else "DocumentRequirement",
            entity_id=item["document_id"] or item["requirement_id"],
            deduplication_key=f"{prefix}alert",
            title_key="modules:notificationContent.document_compliance.title",
            message_key="modules:notificationContent.document_compliance.message",
            message_params={
                "document_type": item["document_type"],
                "status": status,
                "owner": item["owner_name"],
                "date": item["expiry_date"] or "-",
            },
        )
    for notification in db.query(Notification).filter(
        Notification.deduplication_key.like("document-compliance:%"),
        Notification.status.in_(ACTIVE_STATUSES),
    ).all():
        if not any(notification.deduplication_key.startswith(key) for key in active_compliance_keys):
            transition(notification, "Resolved")

    for driver in (db.query(Driver).filter(Driver.archived.is_(False)).all() if enabled("driver_license_expiry") else []):
        days = (driver.license_expiry_date.date() - now.date()).days
        if days > 30:
            resolve_by_prefix(db, f"driver-license:{driver.id}:")
            continue
        expired = days < 0
        notify_roles(
            db, roles=RECIPIENT_ROLES,
            notification_type="Driver licence expired" if expired else "Driver licence expiring",
            title=f"{driver.full_name}'s licence {'expired' if expired else 'expires soon'}",
            message=driver.license_expiry_date.date().isoformat(),
            priority="Critical" if expired else "High",
            entity_type="Driver", entity_id=driver.id,
            deduplication_key=f"driver-license:{driver.id}:{'expired' if expired else 'expires-30-days'}",
            title_key="modules:notificationContent.driver_licence.title",
            message_key="modules:notificationContent.driver_licence.message",
            message_params={"name": driver.full_name, "status": "Overdue" if expired else "Due Soon", "date": driver.license_expiry_date.date().isoformat()},
        )

    active_orders = db.query(WorkOrder).filter(
        WorkOrder.archived.is_(False),
        WorkOrder.expected_completion_date < now,
        WorkOrder.status.in_(["Open", "Assigned", "In Progress", "Waiting for Parts"]),
    ).all() if enabled("work_order_overdue") else []
    active_order_ids = {order.id for order in active_orders}
    for order in active_orders:
        notify_roles(
            db, roles=RECIPIENT_ROLES | {"mechanic"}, notification_type="Work Order overdue",
            title=f"Work Order #{order.id} is overdue", message=order.title,
            priority="Critical" if order.priority == "Critical" else "High",
            entity_type="WorkOrder", entity_id=order.id,
            deduplication_key=f"work-order:{order.id}:overdue",
            title_key="modules:notificationContent.work_order_overdue.title",
            message_key="modules:notificationContent.work_order_overdue.message",
            message_params={"id": order.id, "title": order.title},
        )
    for order in db.query(WorkOrder).filter(~WorkOrder.id.in_(active_order_ids or {-1})).all():
        resolve_by_prefix(db, f"work-order:{order.id}:overdue")

    overdue_assignments = db.query(VehicleAssignment).options(
        joinedload(VehicleAssignment.vehicle),
        joinedload(VehicleAssignment.driver),
        joinedload(VehicleAssignment.reservation),
    ).join(VehicleAssignment.reservation).filter(
        VehicleAssignment.archived.is_(False),
        VehicleAssignment.status == "Active",
        VehicleReservation.end_date < now,
    ).all() if enabled("overdue_assignments") else []
    for assignment in overdue_assignments:
        assignment.status = "Overdue"
        assignment.updated_at = now
        record_audit(
            db,
            action="Vehicle Assignment overdue",
            entity_type="VehicleAssignment",
            entity_id=assignment.id,
            new_values={"status": "Overdue"},
            description=f"Assignment #{assignment.id} is overdue for return.",
        )
        notify_roles(
            db,
            roles=RECIPIENT_ROLES,
            notification_type="Vehicle return overdue",
            title=f"Assignment #{assignment.id} is overdue",
            message=f"{assignment.vehicle.license_plate} · {assignment.driver.full_name}",
            priority="High",
            entity_type="VehicleAssignment",
            entity_id=assignment.id,
            deduplication_key=f"vehicle-usage:{assignment.id}:return-overdue",
            title_key="modules:notificationContent.vehicle_return_overdue.title",
            message_key="modules:notificationContent.vehicle_return_overdue.message",
            message_params={
                "id": assignment.id,
                "plate": assignment.vehicle.license_plate,
                "driver": assignment.driver.full_name,
            },
        )

    reservations = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle)).filter(
        VehicleReservation.archived.is_(False)
    ).all() if enabled("reservations") else []
    for reservation in reservations:
        if reservation.status == 0:
            notify_roles(
                db, roles=RECIPIENT_ROLES, notification_type="Reservation pending approval",
                title=f"Reservation #{reservation.id} awaits approval",
                message=f"{reservation.vehicle.license_plate} for {reservation.reserved_by}",
                priority="Medium", entity_type="VehicleReservation", entity_id=reservation.id,
                deduplication_key=f"reservation:{reservation.id}:pending",
                title_key="modules:notificationContent.reservation_pending.title",
                message_key="modules:notificationContent.reservation.message",
                message_params={"id": reservation.id, "plate": reservation.vehicle.license_plate, "reserved_by": reservation.reserved_by},
            )
        if reservation.status == 1 and now <= reservation.start_date <= now + timedelta(hours=24):
            notify_roles(
                db, roles=RECIPIENT_ROLES, notification_type="Reservation starting soon",
                title=f"Reservation #{reservation.id} starts soon",
                message=f"{reservation.vehicle.license_plate} for {reservation.reserved_by}",
                priority="Medium", entity_type="VehicleReservation", entity_id=reservation.id,
                deduplication_key=f"reservation:{reservation.id}:starts-24-hours",
                title_key="modules:notificationContent.reservation_starting.title",
                message_key="modules:notificationContent.reservation.message",
                message_params={"id": reservation.id, "plate": reservation.vehicle.license_plate, "reserved_by": reservation.reserved_by},
            )
        if reservation.status == 1 and reservation.end_date < now:
            notify_roles(
                db, roles=RECIPIENT_ROLES, notification_type="Reservation overdue for return",
                title=f"Reservation #{reservation.id} is overdue",
                message=f"{reservation.vehicle.license_plate} should have been returned.",
                priority="High", entity_type="VehicleReservation", entity_id=reservation.id,
                deduplication_key=f"reservation:{reservation.id}:overdue-return",
                title_key="modules:notificationContent.reservation_overdue.title",
                message_key="modules:notificationContent.reservation_return.message",
                message_params={"id": reservation.id, "plate": reservation.vehicle.license_plate},
            )

    db.flush()
    return db.query(Notification).count() - notification_count_before
