from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.api.v1.endpoints.services import current_reminder_status
from app.models import Driver, Notification, VehiclePaper, VehicleReservation, VehicleService, WorkOrder
from app.schemas import ReminderStatus
from app.services.notifications import notify_roles, resolve_by_prefix

RECIPIENT_ROLES = {"admin", "fleet_manager"}


def generate_time_based_notifications(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()

    reminders = db.query(VehicleService).options(joinedload(VehicleService.vehicle)).filter(
        VehicleService.archived.is_(False),
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
            message_params={"service_type": reminder.service_type, "status": status.value, "plate": reminder.vehicle.license_plate},
        )

    for paper in db.query(VehiclePaper).options(joinedload(VehiclePaper.vehicle)).filter(VehiclePaper.archived.is_(False)).all():
        days = (paper.expiry_date.date() - now.date()).days
        if days > 30:
            resolve_by_prefix(db, f"document:{paper.id}:")
            continue
        expired = days < 0
        notify_roles(
            db, roles=RECIPIENT_ROLES,
            notification_type="Document expired" if expired else "Document expiring soon",
            title=f"{paper.document_type} {'expired' if expired else 'expires soon'}",
            message=f"{paper.vehicle.license_plate}: {paper.expiry_date.date().isoformat()}",
            priority="Critical" if expired else "High",
            entity_type="VehiclePaper", entity_id=paper.id,
            deduplication_key=f"document:{paper.id}:{'expired' if expired else 'expires-30-days'}",
            title_key="modules:notificationContent.document_expiry.title",
            message_key="modules:notificationContent.document_expiry.message",
            message_params={"document_type": paper.document_type, "status": "Overdue" if expired else "Due Soon", "plate": paper.vehicle.license_plate, "date": paper.expiry_date.date().isoformat()},
        )

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
    ).all()
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

    reservations = db.query(VehicleReservation).options(joinedload(VehicleReservation.vehicle)).filter(
        VehicleReservation.archived.is_(False)
    ).all()
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

    created = sum(1 for item in db.new if isinstance(item, Notification))
    db.flush()
    return created
