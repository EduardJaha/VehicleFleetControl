from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import User, VehicleService, WorkOrder
from app.schemas import (
    ReminderStatus,
    ServiceSource,
    WorkOrderCompletionRequest,
    WorkOrderStatus,
)
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles, resolve_by_prefix
from app.utils.dates import parse_date

MONEY_QUANTUM = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def complete_work_order_transaction(
    db: Session,
    work_order_id: int,
    payload: WorkOrderCompletionRequest,
    current_user: User,
) -> tuple[WorkOrder, VehicleService | None, bool, bool]:
    work_order = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.vehicle),
            joinedload(WorkOrder.linked_service),
            joinedload(WorkOrder.reminder_service),
        )
        .filter(WorkOrder.id == work_order_id)
        .first()
    )
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found.")
    if work_order.archived:
        raise HTTPException(status_code=409, detail=f"Work Order #{work_order.id} is archived and cannot be completed.")
    if work_order.status == WorkOrderStatus.cancelled.value:
        raise HTTPException(status_code=409, detail=f"Cancelled Work Order #{work_order.id} cannot be completed.")
    if work_order.status == WorkOrderStatus.completed.value:
        raise HTTPException(status_code=409, detail=f"Work Order #{work_order.id} is already completed.")
    if work_order.linked_service:
        raise HTTPException(
            status_code=409,
            detail=f"Work Order #{work_order.id} is already linked to Service #{work_order.linked_service.id}.",
        )
    if payload.create_service_record and not payload.service_type:
        raise HTTPException(status_code=422, detail="service_type is required when create_service_record is true.")

    completed_at = parse_date(payload.actual_completion_date, "ActualCompletionDate")
    now = datetime.utcnow()
    if completed_at > now:
        raise HTTPException(status_code=400, detail="Completion date cannot be in the future.")
    if work_order.created_at and completed_at.date() < work_order.created_at.date():
        raise HTTPException(status_code=400, detail="Completion date cannot be before the Work Order creation date.")

    current_odometer = work_order.vehicle.odometer_km or 0
    if payload.completed_odometer_km < current_odometer:
        raise HTTPException(
            status_code=400,
            detail=f"Completed odometer cannot be lower than the vehicle's current odometer ({current_odometer} km).",
        )

    labor = money(payload.labor_cost)
    parts = money(payload.parts_cost)
    total = money(labor + parts)
    old_order = snapshot(work_order)
    old_odometer = work_order.vehicle.odometer_km

    work_order.status = WorkOrderStatus.completed.value
    work_order.actual_completion_date = completed_at
    work_order.completed_odometer_km = payload.completed_odometer_km
    work_order.workshop = payload.workshop or work_order.workshop
    work_order.labor_cost = labor
    work_order.parts_cost = parts
    work_order.total_cost = total
    work_order.completion_notes = payload.completion_notes
    work_order.completed_by = current_user.full_name
    work_order.updated_at = now
    if payload.completed_odometer_km > current_odometer:
        work_order.vehicle.odometer_km = payload.completed_odometer_km

    service: VehicleService | None = None
    reminder_resolved = False
    next_reminder_created = False
    if payload.create_service_record:
        # Reuse the existing reminder rules to keep manual and Work Order
        # service creation behavior identical.
        from app.api.v1.endpoints.services import build_reminder_values

        next_date, next_interval, next_odometer = build_reminder_values(
            payload.service_type or "",
            completed_at,
            payload.next_service_date,
            payload.completed_odometer_km,
            payload.next_service_km_interval,
        )
        service = VehicleService(
            vehicle_id=work_order.vehicle_id,
            work_order_id=work_order.id,
            service_type=payload.service_type,
            description=payload.service_description or payload.completion_notes or work_order.description,
            service_date=completed_at,
            odometer_km=payload.completed_odometer_km,
            cost=total,
            labor_cost=labor,
            parts_cost=parts,
            workshop=payload.workshop or work_order.workshop,
            next_service_date=next_date,
            next_service_km_interval=next_interval,
            next_service_odometer_km=next_odometer,
            source=ServiceSource.work_order.value,
            status="Completed",
            created_at=now,
            updated_at=now,
        )
        db.add(service)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Work Order #{work_order.id} already has a linked Service.",
            ) from exc
        next_reminder_created = next_date is not None or next_odometer is not None

    if payload.resolve_source_reminder and work_order.reminder_service:
        work_order.reminder_service.reminder_status = ReminderStatus.resolved.value
        work_order.reminder_service.updated_at = now
        reminder_resolved = True
        resolve_by_prefix(db, f"service-reminder:{work_order.reminder_service.id}:")

    record_audit(
        db,
        action="Work Order completed",
        entity_type="WorkOrder",
        entity_id=work_order.id,
        user=current_user,
        old_values=old_order,
        new_values=snapshot(work_order),
        description=f"Work Order #{work_order.id} completed with total cost {total}.",
    )
    if work_order.vehicle.odometer_km != old_odometer:
        record_audit(
            db,
            action="Vehicle odometer changed",
            entity_type="Vehicle",
            entity_id=work_order.vehicle_id,
            user=current_user,
            old_values={"odometer_km": old_odometer},
            new_values={"odometer_km": work_order.vehicle.odometer_km},
            description=f"Vehicle odometer updated while completing Work Order #{work_order.id}.",
        )
    if service:
        record_audit(
            db,
            action="Service created",
            entity_type="VehicleService",
            entity_id=service.id,
            user=current_user,
            new_values=snapshot(service),
            description=f"Service #{service.id} created from Work Order #{work_order.id}.",
        )
        record_audit(
            db,
            action="Service linked to Work Order",
            entity_type="WorkOrder",
            entity_id=work_order.id,
            user=current_user,
            new_values={"service_id": service.id},
            description=f"Work Order #{work_order.id} linked to Service #{service.id}.",
        )
    if reminder_resolved:
        record_audit(
            db,
            action="Reminder resolved",
            entity_type="VehicleService",
            entity_id=work_order.reminder_service_id,
            user=current_user,
            new_values={"reminder_status": ReminderStatus.resolved.value},
            description=f"Source reminder resolved by Work Order #{work_order.id}.",
        )
    if next_reminder_created and service:
        record_audit(
            db,
            action="Next reminder created",
            entity_type="VehicleService",
            entity_id=service.id,
            user=current_user,
            new_values={
                "next_service_date": service.next_service_date,
                "next_service_odometer_km": service.next_service_odometer_km,
            },
            description=f"Next reminder generated from Service #{service.id}.",
        )

    notify_roles(
        db,
        roles={"admin", "fleet_manager", "mechanic"},
        notification_type="Work Order completed",
        title=f"Work Order #{work_order.id} completed",
        message=f"{work_order.title} for {work_order.vehicle.license_plate} was completed.",
        priority="Medium",
        entity_type="WorkOrder",
        entity_id=work_order.id,
        deduplication_key=f"work-order:{work_order.id}:completed",
        message_params={"id": work_order.id, "title": work_order.title, "plate": work_order.vehicle.license_plate},
    )
    db.flush()
    return work_order, service, reminder_resolved, next_reminder_created
