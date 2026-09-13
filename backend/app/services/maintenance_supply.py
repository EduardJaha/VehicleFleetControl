"""Transactional supply operations. Callers commit once, including audit and notifications."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.maintenance_supply_schemas import InventoryTransactionType
from app.models import (
    InventoryTransaction,
    LaborEntry,
    Location,
    Part,
    PartInventory,
    Technician,
    User,
    WorkOrder,
    WorkOrderPart,
    WorkOrderVendorCharge,
)
from app.services.audit import record_audit, snapshot
from app.services.notifications import notify_roles, resolve_by_prefix


def decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def money(value) -> Decimal:
    return decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def quantity(value) -> Decimal:
    return decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def lock_row(db: Session, model, row_id: int):
    # UPDATE takes a write lock on SQLite as well as PostgreSQL. A SELECT FOR
    # UPDATE alone has no effect on SQLite. Always scope bulk statements explicitly.
    query = db.query(model).filter(model.id == row_id)
    if db.info.get("company_id") is not None:
        query = query.filter(model.company_id == db.info["company_id"])
    if query.update({model.id: model.id}, synchronize_session=False) != 1:
        raise HTTPException(status_code=404, detail="Record not found.")
    row = query.populate_existing().one()
    return row


def editable_order(db: Session, order: WorkOrder) -> WorkOrder:
    order = lock_row(db, WorkOrder, order.id)
    if (
        order.archived
        or order.status in {"Completed", "Cancelled"}
        or order.linked_service
    ):
        raise HTTPException(status_code=409, detail={"code": "supply_locked"})
    return order


def require_no_active_clock(db: Session, work_order_id: int) -> None:
    # Call while holding the WorkOrder lock shared with clock-in/clock-out.
    if (
        db.query(LaborEntry)
        .filter(
            LaborEntry.work_order_id == work_order_id,
            LaborEntry.clock_in.isnot(None),
            LaborEntry.clock_out.is_(None),
            LaborEntry.archived.is_(False),
        )
        .first()
    ):
        raise HTTPException(status_code=409, detail={"code": "supply_clock_active"})


def active_row(row, label: str):
    if (
        getattr(row, "archived", False)
        or not getattr(row, "is_active", True)
        or getattr(row, "status", "Active") == "Inactive"
    ):
        raise HTTPException(status_code=409, detail={"code": "supply_inactive"})
    return row


def locked_balance(db: Session, part_id: int, location_id: int) -> PartInventory:
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(status_code=404, detail="Storage location not found.")
    active_row(location, "Storage location")
    query = db.query(PartInventory).filter(
        PartInventory.part_id == part_id, PartInventory.location_id == location_id
    )
    balance = query.with_for_update().first()
    if not balance:
        try:
            with db.begin_nested():
                balance = PartInventory(
                    part_id=part_id,
                    location_id=location_id,
                    quantity_on_hand=0,
                    reserved_quantity=0,
                )
                db.add(balance)
                db.flush()
        except IntegrityError:
            balance = query.with_for_update().one()
    return balance


def _change_balance(
    db: Session, part_id: int, location_id: int, delta: Decimal
) -> PartInventory:
    balance = locked_balance(db, part_id, location_id)
    # Arithmetic and availability guard run inside ONE UPDATE. Reserved stock is
    # unavailable to issues, transfers, negative adjustments, and write-offs.
    predicate = [
        PartInventory.id == balance.id,
        PartInventory.company_id == balance.company_id,
    ]
    if delta < 0:
        predicate.append(
            func.round(
                PartInventory.quantity_on_hand - PartInventory.reserved_quantity, 3
            )
            >= -delta
        )
    result = db.execute(
        update(PartInventory)
        .where(*predicate)
        .values(
            quantity_on_hand=func.round(PartInventory.quantity_on_hand + delta, 3),
            updated_at=datetime.utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "negative_stock",
                "message": "Insufficient available stock.",
                "params": {"part_id": part_id, "location_id": location_id},
            },
        )
    db.refresh(balance)
    return balance


def refresh_low_stock(db: Session, part: Part, balance: PartInventory):
    minimum = (
        balance.minimum_stock
        if balance.minimum_stock is not None
        else decimal(part.minimum_stock)
    )
    available = quantity(balance.quantity_on_hand - balance.reserved_quantity)
    key = f"part:{part.id}:location:{balance.location_id}:low-stock"
    if available <= minimum:
        notify_roles(
            db,
            roles={"admin", "fleet_manager", "mechanic"},
            notification_type="Part low stock",
            title=f"Low stock: {part.part_number}",
            message=f"{part.name}: {available} {part.unit} at {balance.location.name}.",
            priority="High",
            entity_type="Part",
            entity_id=part.id,
            deduplication_key=key,
            message_params={
                "part_number": part.part_number,
                "quantity": str(available),
                "unit": part.unit,
                "location": balance.location.name,
            },
        )
    else:
        resolve_by_prefix(db, key + ":")


def create_inventory_transaction(
    db: Session,
    *,
    part: Part,
    transaction_type: InventoryTransactionType,
    transaction_quantity: Decimal,
    actor: User,
    from_location_id=None,
    to_location_id=None,
    unit_cost=None,
    work_order_id=None,
    purchase_order_item_id=None,
    notes=None,
) -> InventoryTransaction:
    amount = quantity(transaction_quantity)
    if not amount or (
        amount < 0 and transaction_type != InventoryTransactionType.adjustment
    ):
        raise HTTPException(status_code=422, detail="Invalid movement quantity.")
    if transaction_type != InventoryTransactionType.return_:
        active_row(part, "Part")
    balances = []
    if transaction_type in {
        InventoryTransactionType.issue,
        InventoryTransactionType.write_off,
    }:
        balances.append(_change_balance(db, part.id, from_location_id or 0, -amount))
    elif transaction_type in {
        InventoryTransactionType.purchase,
        InventoryTransactionType.return_,
        InventoryTransactionType.opening,
    }:
        balances.append(_change_balance(db, part.id, to_location_id or 0, amount))
    elif transaction_type == InventoryTransactionType.transfer:
        if from_location_id == to_location_id:
            raise HTTPException(
                status_code=422, detail="A transfer requires different locations."
            )
        # Consistent lock order avoids opposite-transfer deadlocks.
        for location, delta in sorted(
            [(from_location_id or 0, -amount), (to_location_id or 0, amount)]
        ):
            balances.append(_change_balance(db, part.id, location, delta))
    elif transaction_type == InventoryTransactionType.adjustment:
        location = to_location_id or from_location_id or 0
        balances.append(_change_balance(db, part.id, location, amount))
        to_location_id, from_location_id = (
            (location, None) if amount > 0 else (None, location)
        )
    transaction = InventoryTransaction(
        part_id=part.id,
        transaction_type=transaction_type.value,
        quantity=amount,
        unit_cost=unit_cost if unit_cost is not None else part.unit_cost,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        work_order_id=work_order_id,
        purchase_order_item_id=purchase_order_item_id,
        notes=notes,
        performed_by=actor.id,
    )
    db.add(transaction)
    db.flush()
    record_audit(
        db,
        action="Inventory transaction created",
        entity_type="InventoryTransaction",
        entity_id=transaction.id,
        user=actor,
        new_values=snapshot(transaction),
        description=f"{transaction_type.value}: {part.part_number}.",
    )
    for balance in balances:
        refresh_low_stock(db, part, balance)
    return transaction


def recalculate_work_order_costs(db: Session, work_order: WorkOrder) -> WorkOrder:
    db.flush()
    # Query rows instead of relationship collections which may have been loaded
    # before an issue/return. Retain legacy manual subtotals only when that
    # category has never had line items, including archived line items.
    for model, column, attribute in [
        (WorkOrderPart, WorkOrderPart.total_cost, "parts_cost"),
        (LaborEntry, LaborEntry.labor_cost, "labor_cost"),
        (WorkOrderVendorCharge, WorkOrderVendorCharge.amount, "external_vendor_cost"),
    ]:
        q = db.query(model).filter(model.work_order_id == work_order.id)
        if q.count():
            value = (
                db.query(func.sum(column))
                .filter(model.work_order_id == work_order.id, model.archived.is_(False))
                .scalar()
            )
            setattr(work_order, attribute, money(value))
    total = sum(
        decimal(getattr(work_order, field))
        for field in [
            "parts_cost",
            "labor_cost",
            "external_vendor_cost",
            "tax_amount",
            "other_cost",
        ]
    ) - decimal(work_order.discount_amount)
    if total < 0:
        raise HTTPException(status_code=422, detail={"code": "supply_discount"})
    work_order.total_cost = money(total)
    work_order.updated_at = datetime.utcnow()
    db.flush()
    return work_order


def issue_part_to_work_order(
    db: Session,
    *,
    work_order: WorkOrder,
    part: Part,
    location_id: int,
    issue_quantity: Decimal,
    actor: User,
    unit_cost=None,
    notes=None,
) -> WorkOrderPart:
    editable_order(db, work_order)
    cost = decimal(unit_cost if unit_cost is not None else part.unit_cost)
    transaction = create_inventory_transaction(
        db,
        part=part,
        transaction_type=InventoryTransactionType.issue,
        transaction_quantity=issue_quantity,
        actor=actor,
        from_location_id=location_id,
        unit_cost=cost,
        work_order_id=work_order.id,
        notes=notes,
    )
    line = WorkOrderPart(
        work_order_id=work_order.id,
        part_id=part.id,
        location_id=location_id,
        inventory_transaction_id=transaction.id,
        quantity=quantity(issue_quantity),
        quantity_returned=0,
        unit_cost=cost,
        total_cost=money(decimal(issue_quantity) * cost),
    )
    db.add(line)
    db.flush()
    record_audit(
        db,
        action="Part issued to Work Order",
        entity_type="WorkOrderPart",
        entity_id=line.id,
        user=actor,
        new_values=snapshot(line),
    )
    recalculate_work_order_costs(db, work_order)
    return line


def return_part(
    db: Session, *, order: WorkOrder, line_id: int, amount, actor: User, notes=None
):
    editable_order(db, order)
    line = (
        db.query(WorkOrderPart)
        .filter(WorkOrderPart.id == line_id, WorkOrderPart.work_order_id == order.id)
        .first()
    )
    if not line:
        raise HTTPException(status_code=404, detail="Work Order part line not found.")
    remaining = decimal(line.quantity) - decimal(line.quantity_returned)
    amount = remaining if amount is None else quantity(amount)
    if line.archived or amount <= 0 or amount > remaining:
        raise HTTPException(status_code=409, detail={"code": "supply_return_exceeded"})
    create_inventory_transaction(
        db,
        part=line.part,
        transaction_type=InventoryTransactionType.return_,
        transaction_quantity=amount,
        actor=actor,
        to_location_id=line.location_id,
        unit_cost=line.unit_cost,
        work_order_id=order.id,
        notes=notes or f"Return of Work Order part line {line.id}",
    )
    old = snapshot(line)
    line.quantity_returned = decimal(line.quantity_returned) + amount
    line.total_cost = money(
        (decimal(line.quantity) - line.quantity_returned) * decimal(line.unit_cost)
    )
    line.archived = line.quantity_returned == line.quantity
    record_audit(
        db,
        action="Work Order part returned",
        entity_type="WorkOrderPart",
        entity_id=line.id,
        user=actor,
        old_values=old,
        new_values=snapshot(line),
    )
    recalculate_work_order_costs(db, order)
    return line


def validate_clock_overlap(
    db: Session, technician_id: int, clock_in, clock_out=None, exclude_id=None
):
    query = db.query(LaborEntry).filter(
        LaborEntry.technician_id == technician_id,
        LaborEntry.archived.is_(False),
        LaborEntry.clock_in.isnot(None),
    )
    if exclude_id:
        query = query.filter(LaborEntry.id != exclude_id)
    if clock_out:
        query = query.filter(LaborEntry.clock_in < clock_out)
    query = query.filter(
        or_(LaborEntry.clock_out.is_(None), LaborEntry.clock_out > clock_in)
    )
    if query.first():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "clock_overlap",
                "message": "Technician has an overlapping clock session.",
            },
        )


def add_labor_entry(
    db: Session,
    *,
    work_order: WorkOrder,
    technician: Technician,
    actual_hours: Decimal,
    hourly_rate: Decimal,
    actor: User,
    clock_in=None,
    clock_out=None,
    task_description=None,
    notes=None,
) -> LaborEntry:
    editable_order(db, work_order)
    active_row(lock_row(db, Technician, technician.id), "Technician")
    if clock_in:
        if clock_out is None or clock_out <= clock_in or clock_out > datetime.utcnow():
            raise HTTPException(
                status_code=422, detail={"code": "supply_clock_interval"}
            )
        validate_clock_overlap(db, technician.id, clock_in, clock_out)
        actual_hours = money(
            Decimal(str((clock_out - clock_in).total_seconds())) / Decimal("3600")
        )
    if actual_hours <= 0:
        raise HTTPException(status_code=422, detail="Labor hours must be positive.")
    entry = LaborEntry(
        work_order_id=work_order.id,
        technician_id=technician.id,
        actual_hours=actual_hours,
        clock_in=clock_in,
        clock_out=clock_out,
        hourly_rate=hourly_rate,
        labor_cost=money(actual_hours * hourly_rate),
        task_description=task_description,
        notes=notes,
    )
    db.add(entry)
    db.flush()
    record_audit(
        db,
        action="Labor entry created",
        entity_type="LaborEntry",
        entity_id=entry.id,
        user=actor,
        new_values=snapshot(entry),
    )
    recalculate_work_order_costs(db, work_order)
    return entry
