from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.authorization import has_permission, require_permission
from app.core.security import get_current_user
from app.db.session import get_db
from app.maintenance_supply_schemas import (
    ClockInIn,
    PartReturnIn,
    InventorySettingsIn,
    VendorChargeOut,
    InventoryBalanceOut,
    InventoryTransactionIn,
    InventoryTransactionOut,
    InventoryTransactionType,
    LaborEntryIn,
    LaborEntryOut,
    PartCategoryIn,
    PartCategoryOut,
    PartIn,
    PartOut,
    PurchaseOrderIn,
    PurchaseOrderItemOut,
    PurchaseOrderOut,
    PurchaseOrderReceiveIn,
    PurchaseOrderStatus,
    PurchaseOrderStatusIn,
    TechnicianIn,
    TechnicianOut,
    VendorChargeIn,
    VendorIn,
    VendorOut,
    WorkOrderCostAdjustmentsIn,
    WorkOrderCostBreakdownOut,
    WorkOrderPartIssueIn,
    WorkOrderPartOut,
    WorkOrderTechnicianIn,
    WorkOrderTechnicianOut,
)
from app.models import (
    Attachment,
    AuditLog,
    CompanyUser,
    InventoryTransaction,
    LaborEntry,
    Location,
    Part,
    PartCategory,
    PartInventory,
    PurchaseOrder,
    PurchaseOrderItem,
    Technician,
    User,
    Vendor,
    WorkOrder,
    WorkOrderPart,
    WorkOrderTechnician,
    WorkOrderVendorCharge,
    VehicleService,
)
from app.services.audit import record_audit, snapshot
from app.services.maintenance_supply import (
    active_row,
    editable_order,
    lock_row,
    return_part,
    refresh_low_stock,
    validate_clock_overlap,
    locked_balance,
    add_labor_entry,
    create_inventory_transaction,
    decimal,
    issue_part_to_work_order,
    money,
    recalculate_work_order_costs,
)
from app.services.notifications import notify_roles

from fastapi.routing import APIRoute


class SupplyRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def transaction_handler(request):
            try:
                return await handler(request)
            except IntegrityError as exc:
                raise HTTPException(
                    status_code=409, detail={"code": "supply_conflict"}
                ) from exc
            except OperationalError as exc:
                if "locked" in str(exc).lower() or "deadlock" in str(exc).lower():
                    raise HTTPException(
                        status_code=409, detail={"code": "supply_concurrent"}
                    ) from exc
                raise

        return transaction_handler


router = APIRouter(route_class=SupplyRoute)


def commit_or_conflict(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from exc


def require_row(db: Session, model, row_id: int, label: str):
    row = db.query(model).filter(model.id == row_id).first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "supply_missing"})
    return row


def part_out(part: Part) -> PartOut:
    inventory = [
        InventoryBalanceOut(
            location_id=row.location_id,
            location_name=row.location.name,
            quantity_on_hand=row.quantity_on_hand,
            reserved_quantity=row.reserved_quantity,
            available_quantity=row.quantity_on_hand - row.reserved_quantity,
            minimum_stock=row.minimum_stock,
        )
        for row in part.inventories
    ]
    return PartOut(
        id=part.id,
        company_id=part.company_id,
        manufacturer=part.manufacturer,
        part_number=part.part_number,
        name=part.name,
        description=part.description,
        category_id=part.category_id,
        category_name=part.category.name,
        unit=part.unit,
        unit_cost=part.unit_cost,
        supplier_id=part.supplier_id,
        supplier_name=part.supplier.name if part.supplier else None,
        barcode=part.barcode,
        minimum_stock=part.minimum_stock,
        is_active=part.is_active,
        archived=part.archived,
        total_stock=sum(decimal(row.quantity_on_hand) for row in part.inventories),
        inventory=inventory,
        created_at=part.created_at,
        updated_at=part.updated_at,
    )


def purchase_order_out(order: PurchaseOrder) -> PurchaseOrderOut:
    return PurchaseOrderOut(
        id=order.id,
        company_id=order.company_id,
        created_by=order.created_by,
        approved_by=order.approved_by,
        order_number=order.order_number,
        vendor_id=order.vendor_id,
        vendor_name=order.vendor.name,
        storage_location_id=order.storage_location_id,
        status=PurchaseOrderStatus(order.status),
        order_date=order.order_date,
        expected_date=order.expected_date,
        notes=order.notes,
        subtotal=order.subtotal,
        tax_amount=order.tax_amount,
        discount_amount=order.discount_amount,
        total_amount=order.total_amount,
        archived=order.archived,
        items=[
            PurchaseOrderItemOut(
                id=item.id,
                part_id=item.part_id,
                part_number=item.part.part_number,
                part_name=item.part.name,
                quantity_ordered=item.quantity_ordered,
                quantity_received=item.quantity_received,
                unit_cost=item.unit_cost,
                line_total=item.line_total,
            )
            for item in order.items
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def order_query(db: Session):
    return db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.vendor),
        selectinload(PurchaseOrder.items).joinedload(PurchaseOrderItem.part),
    )


def work_order_part_out(row: WorkOrderPart) -> WorkOrderPartOut:
    return WorkOrderPartOut(
        id=row.id,
        work_order_id=row.work_order_id,
        part_id=row.part_id,
        part_number=row.part.part_number,
        part_name=row.part.name,
        location_id=row.location_id,
        quantity=row.quantity,
        quantity_returned=row.quantity_returned,
        unit_cost=row.unit_cost,
        total_cost=row.total_cost,
        archived=row.archived,
    )


def labor_out(row: LaborEntry) -> LaborEntryOut:
    return LaborEntryOut(
        id=row.id,
        work_order_id=row.work_order_id,
        technician_id=row.technician_id,
        technician_name=row.technician.full_name,
        actual_hours=row.actual_hours,
        clock_in=row.clock_in,
        clock_out=row.clock_out,
        hourly_rate=row.hourly_rate,
        labor_cost=row.labor_cost,
        notes=row.notes,
        task_description=row.task_description,
        archived=row.archived,
    )


@router.get(
    "/storage-locations", dependencies=[Depends(require_permission("inventory.view"))]
)
def list_storage_locations(db: Session = Depends(get_db)):
    return [
        {"id": row.id, "code": row.code, "name": row.name, "is_active": row.is_active}
        for row in db.query(Location)
        .filter(Location.is_active.is_(True))
        .order_by(Location.name)
        .all()
    ]


@router.get(
    "/vendors",
    response_model=list[VendorOut],
    dependencies=[Depends(require_permission("vendors.view"))],
)
def list_vendors(include_archived: bool = False, db: Session = Depends(get_db)):
    query = db.query(Vendor)
    if not include_archived:
        query = query.filter(Vendor.archived.is_(False))
    return query.order_by(Vendor.name).all()


@router.post("/vendors", response_model=VendorOut, status_code=201)
def create_vendor(
    payload: VendorIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("vendors.manage")),
):
    vendor = Vendor(
        **payload.model_dump(mode="json", exclude={"vendor_type"}),
        vendor_type=payload.vendor_type.value,
    )
    db.add(vendor)
    flush_or_conflict(db)
    record_audit(
        db,
        action="Vendor created",
        entity_type="Vendor",
        entity_id=vendor.id,
        user=actor,
        new_values=snapshot(vendor),
    )
    commit_or_conflict(db, "A vendor with this name and type already exists.")
    db.refresh(vendor)
    return vendor


@router.put("/vendors/{vendor_id}", response_model=VendorOut)
def update_vendor(
    vendor_id: int,
    payload: VendorIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("vendors.manage")),
):
    vendor = require_row(db, Vendor, vendor_id, "Vendor")
    old = snapshot(vendor)
    for key, value in payload.model_dump(mode="json").items():
        setattr(vendor, key, value)
    vendor.vendor_type = payload.vendor_type.value
    vendor.updated_at = datetime.utcnow()
    record_audit(
        db,
        action="Vendor updated",
        entity_type="Vendor",
        entity_id=vendor.id,
        user=actor,
        old_values=old,
        new_values=snapshot(vendor),
    )
    commit_or_conflict(db, "A vendor with this name and type already exists.")
    return vendor


@router.put("/vendors/{vendor_id}/archive", response_model=VendorOut)
def archive_vendor(
    vendor_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("vendors.manage")),
):
    vendor = require_row(db, Vendor, vendor_id, "Vendor")
    vendor.archived, vendor.archived_at, vendor.archived_by = (
        True,
        datetime.utcnow(),
        actor.id,
    )
    record_audit(
        db,
        action="Vendor archived",
        entity_type="Vendor",
        entity_id=vendor.id,
        user=actor,
        new_values={"archived": True},
    )
    db.commit()
    return vendor


@router.post("/vendors/{vendor_id}/restore", response_model=VendorOut)
def restore_vendor(
    vendor_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("vendors.manage")),
):
    vendor = require_row(db, Vendor, vendor_id, "Vendor")
    vendor.archived, vendor.archived_at, vendor.archived_by = False, None, None
    record_audit(
        db,
        action="Vendor restored",
        entity_type="Vendor",
        entity_id=vendor.id,
        user=actor,
        new_values={"archived": False},
    )
    db.commit()
    return vendor


@router.get(
    "/part-categories",
    response_model=list[PartCategoryOut],
    dependencies=[Depends(require_permission("parts.view"))],
)
def list_part_categories(include_archived: bool = False, db: Session = Depends(get_db)):
    query = db.query(PartCategory)
    if not include_archived:
        query = query.filter(PartCategory.archived.is_(False))
    return query.order_by(PartCategory.name).all()


@router.post("/part-categories", response_model=PartCategoryOut, status_code=201)
def create_part_category(
    payload: PartCategoryIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    row = PartCategory(**payload.model_dump())
    db.add(row)
    flush_or_conflict(db)
    record_audit(
        db,
        action="Part category created",
        entity_type="PartCategory",
        entity_id=row.id,
        user=actor,
        new_values=snapshot(row),
    )
    commit_or_conflict(db, "Part category name already exists.")
    return row


@router.put("/part-categories/{category_id}/archive", response_model=PartCategoryOut)
def archive_part_category(
    category_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    row = require_row(db, PartCategory, category_id, "Part category")
    if (
        db.query(Part)
        .filter(Part.category_id == row.id, Part.archived.is_(False))
        .first()
    ):
        raise HTTPException(
            status_code=409, detail="A category with active parts cannot be archived."
        )
    row.archived, row.archived_at, row.archived_by, row.is_active = (
        True,
        datetime.utcnow(),
        actor.id,
        False,
    )
    record_audit(
        db,
        action="Part category archived",
        entity_type="PartCategory",
        entity_id=row.id,
        user=actor,
        new_values={"archived": True},
    )
    db.commit()
    return row


@router.get(
    "/parts",
    response_model=list[PartOut],
    dependencies=[Depends(require_permission("parts.view"))],
)
def list_parts(
    include_archived: bool = False,
    low_stock_only: bool = False,
    db: Session = Depends(get_db),
    search: str | None = None,
    category_id: int | None = None,
    vendor_id: int | None = None,
):
    query = db.query(Part).options(
        joinedload(Part.category),
        joinedload(Part.supplier),
        joinedload(Part.inventories).joinedload(PartInventory.location),
    )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Part.part_number.ilike(pattern),
                Part.name.ilike(pattern),
                Part.barcode.ilike(pattern),
                Part.category.has(PartCategory.name.ilike(pattern)),
                Part.supplier.has(Vendor.name.ilike(pattern)),
            )
        )
    if category_id is not None:
        query = query.filter(Part.category_id == category_id)
    if vendor_id is not None:
        query = query.filter(Part.supplier_id == vendor_id)
    if not include_archived:
        query = query.filter(Part.archived.is_(False))
    rows = query.order_by(Part.part_number).all()
    if low_stock_only:
        rows = [
            row
            for row in rows
            if sum(decimal(item.quantity_on_hand) for item in row.inventories)
            <= decimal(row.minimum_stock)
        ]
    return [part_out(row) for row in rows]


@router.get(
    "/parts/{part_id}",
    response_model=PartOut,
    dependencies=[Depends(require_permission("parts.view"))],
)
def get_part(part_id: int, db: Session = Depends(get_db)):
    part = (
        db.query(Part)
        .options(
            joinedload(Part.category),
            joinedload(Part.supplier),
            joinedload(Part.inventories).joinedload(PartInventory.location),
        )
        .filter(Part.id == part_id)
        .first()
    )
    if not part:
        raise HTTPException(status_code=404, detail="Part not found.")
    return part_out(part)


def validate_part_links(db: Session, category_id: int, supplier_id: int | None):
    active_row(
        require_row(db, PartCategory, category_id, "Part category"), "Part category"
    )
    if supplier_id is not None:
        supplier = require_row(db, Vendor, supplier_id, "Supplier")
        active_row(supplier, "Vendor")


@router.post("/parts", response_model=PartOut, status_code=201)
def create_part(
    payload: PartIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    validate_part_links(db, payload.category_id, payload.supplier_id)
    part = Part(**payload.model_dump())
    db.add(part)
    flush_or_conflict(db)
    record_audit(
        db,
        action="Part created",
        entity_type="Part",
        entity_id=part.id,
        user=actor,
        new_values=snapshot(part),
    )
    commit_or_conflict(db, "Part number or barcode already exists.")
    return get_part(part.id, db)


@router.put("/parts/{part_id}", response_model=PartOut)
def update_part(
    part_id: int,
    payload: PartIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    part = require_row(db, Part, part_id, "Part")
    validate_part_links(db, payload.category_id, payload.supplier_id)
    old = snapshot(part)
    for key, value in payload.model_dump().items():
        setattr(part, key, value)
    part.updated_at = datetime.utcnow()
    record_audit(
        db,
        action="Part updated",
        entity_type="Part",
        entity_id=part.id,
        user=actor,
        old_values=old,
        new_values=snapshot(part),
    )
    db.flush()
    for balance in part.inventories:
        refresh_low_stock(db, part, balance)
    commit_or_conflict(db, "Part number or barcode already exists.")
    return get_part(part.id, db)


@router.put("/parts/{part_id}/archive", response_model=PartOut)
def archive_part(
    part_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    part = require_row(db, Part, part_id, "Part")
    if any(decimal(row.quantity_on_hand) for row in part.inventories):
        raise HTTPException(status_code=409, detail={"code": "supply_stock_archive"})
    part.archived, part.archived_at, part.archived_by, part.is_active = (
        True,
        datetime.utcnow(),
        actor.id,
        False,
    )
    record_audit(
        db,
        action="Part archived",
        entity_type="Part",
        entity_id=part.id,
        user=actor,
        new_values={"archived": True},
    )
    db.commit()
    return get_part(part.id, db)


@router.post("/parts/{part_id}/restore", response_model=PartOut)
def restore_part(
    part_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    part = require_row(db, Part, part_id, "Part")
    part.archived, part.archived_at, part.archived_by, part.is_active = (
        False,
        None,
        None,
        True,
    )
    record_audit(
        db,
        action="Part restored",
        entity_type="Part",
        entity_id=part.id,
        user=actor,
        new_values={"archived": False},
    )
    db.commit()
    return get_part(part.id, db)


@router.post(
    "/inventory-transactions", response_model=InventoryTransactionOut, status_code=201
)
def transact_inventory(
    payload: InventoryTransactionIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("inventory.manage")),
):
    if (
        payload.transaction_type == InventoryTransactionType.issue
        and payload.unit_cost is not None
        and not has_permission(db, actor, "maintenance.manage_costs")
    ):
        raise HTTPException(
            status_code=403,
            detail="maintenance.manage_costs is required to override part costs.",
        )
    part = require_row(db, Part, payload.part_id, "Part")
    work_order = (
        require_row(db, WorkOrder, payload.work_order_id, "Work Order")
        if payload.work_order_id is not None
        else None
    )
    try:
        if payload.transaction_type == InventoryTransactionType.issue and work_order:
            line = issue_part_to_work_order(
                db,
                work_order=work_order,
                part=part,
                location_id=payload.from_location_id or 0,
                issue_quantity=payload.quantity,
                actor=actor,
                unit_cost=payload.unit_cost,
                notes=payload.notes,
            )
            transaction = line.inventory_transaction
        else:
            transaction = create_inventory_transaction(
                db,
                part=part,
                transaction_type=payload.transaction_type,
                transaction_quantity=payload.quantity,
                actor=actor,
                from_location_id=payload.from_location_id,
                to_location_id=payload.to_location_id,
                unit_cost=payload.unit_cost,
                work_order_id=payload.work_order_id,
                notes=payload.notes,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return transaction


@router.get(
    "/inventory-transactions",
    response_model=list[InventoryTransactionOut],
    dependencies=[Depends(require_permission("inventory.view"))],
)
def list_inventory_transactions(
    part_id: int | None = None,
    location_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(InventoryTransaction)
    if part_id is not None:
        query = query.filter(InventoryTransaction.part_id == part_id)
    if location_id is not None:
        query = query.filter(
            (InventoryTransaction.from_location_id == location_id)
            | (InventoryTransaction.to_location_id == location_id)
        )
    return query.order_by(
        InventoryTransaction.created_at.desc(), InventoryTransaction.id.desc()
    ).all()


@router.post(
    "/work-orders/{work_order_id}/parts",
    response_model=WorkOrderPartOut,
    status_code=201,
)
def add_work_order_part(
    work_order_id: int,
    payload: WorkOrderPartIssueIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("inventory.manage")),
):
    if payload.unit_cost is not None and not has_permission(
        db, actor, "maintenance.manage_costs"
    ):
        raise HTTPException(
            status_code=403,
            detail="maintenance.manage_costs is required to override part costs.",
        )
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    part = require_row(db, Part, payload.part_id, "Part")
    try:
        row = issue_part_to_work_order(
            db,
            work_order=order,
            part=part,
            location_id=payload.location_id,
            issue_quantity=payload.quantity,
            actor=actor,
            unit_cost=payload.unit_cost,
            notes=payload.notes,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return work_order_part_out(row)


@router.get(
    "/work-orders/{work_order_id}/parts",
    response_model=list[WorkOrderPartOut],
    dependencies=[Depends(require_permission("maintenance.view"))],
)
def list_work_order_parts(work_order_id: int, db: Session = Depends(get_db)):
    require_row(db, WorkOrder, work_order_id, "Work Order")
    return [
        work_order_part_out(row)
        for row in db.query(WorkOrderPart)
        .options(joinedload(WorkOrderPart.part))
        .filter(
            WorkOrderPart.work_order_id == work_order_id,
            WorkOrderPart.archived.is_(False),
        )
        .all()
    ]


@router.delete(
    "/work-orders/{work_order_id}/parts/{line_id}",
    response_model=WorkOrderCostBreakdownOut,
)
def return_work_order_part(
    work_order_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("inventory.manage")),
):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    try:
        return_part(db, order=order, line_id=line_id, amount=None, actor=actor)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return cost_breakdown(order)


@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201)
def create_purchase_order(
    payload: PurchaseOrderIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("purchase_orders.create")),
):
    if payload.status not in {
        PurchaseOrderStatus.draft,
        PurchaseOrderStatus.submitted,
        PurchaseOrderStatus.approved,
    }:
        raise HTTPException(
            status_code=422,
            detail="A new Purchase Order must be Draft, Submitted, or Approved.",
        )
    if payload.status == PurchaseOrderStatus.approved and not has_permission(
        db, actor, "purchase_orders.approve"
    ):
        raise HTTPException(
            status_code=403,
            detail="purchase_orders.approve is required to create an approved Purchase Order.",
        )
    vendor = require_row(db, Vendor, payload.vendor_id, "Vendor")
    require_row(db, Location, payload.storage_location_id, "Storage location")
    active_row(vendor, "Vendor")
    parts = {
        row.id: row
        for row in db.query(Part)
        .filter(Part.id.in_([item.part_id for item in payload.items]))
        .all()
    }
    if len(parts) != len(payload.items):
        raise HTTPException(status_code=404, detail="One or more parts were not found.")
    for part in parts.values():
        active_row(part, "Part")
    subtotal = money(
        sum(money(item.quantity_ordered * item.unit_cost) for item in payload.items)
    )
    if payload.discount_amount > subtotal + payload.tax_amount:
        raise HTTPException(status_code=422, detail={"code": "supply_discount"})
    order = PurchaseOrder(
        order_number=payload.order_number,
        vendor_id=payload.vendor_id,
        storage_location_id=payload.storage_location_id,
        status=payload.status.value,
        order_date=payload.order_date,
        expected_date=payload.expected_date,
        notes=payload.notes,
        subtotal=subtotal,
        tax_amount=payload.tax_amount,
        discount_amount=payload.discount_amount,
        total_amount=money(
            max(Decimal("0"), subtotal + payload.tax_amount - payload.discount_amount)
        ),
        created_by=actor.id,
        approved_by=(
            actor.id if payload.status == PurchaseOrderStatus.approved else None
        ),
        approved_at=(
            datetime.utcnow()
            if payload.status == PurchaseOrderStatus.approved
            else None
        ),
    )
    order.items = [
        PurchaseOrderItem(
            part_id=item.part_id,
            quantity_ordered=item.quantity_ordered,
            quantity_received=0,
            unit_cost=item.unit_cost,
            line_total=money(item.quantity_ordered * item.unit_cost),
        )
        for item in payload.items
    ]
    db.add(order)
    flush_or_conflict(db)
    record_audit(
        db,
        action="Purchase Order created",
        entity_type="PurchaseOrder",
        entity_id=order.id,
        user=actor,
        new_values=snapshot(order),
    )
    commit_or_conflict(
        db, "Purchase Order number or part lines conflict with an existing record."
    )
    return purchase_order_out(
        order_query(db).filter(PurchaseOrder.id == order.id).one()
    )


@router.get(
    "/purchase-orders",
    response_model=list[PurchaseOrderOut],
    dependencies=[Depends(require_permission("purchase_orders.view"))],
)
def list_purchase_orders(
    status: PurchaseOrderStatus | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
):
    query = order_query(db)
    if status:
        query = query.filter(PurchaseOrder.status == status.value)
    if not include_archived:
        query = query.filter(PurchaseOrder.archived.is_(False))
    return [
        purchase_order_out(row)
        for row in query.order_by(PurchaseOrder.created_at.desc()).all()
    ]


@router.put("/purchase-orders/{order_id}/status", response_model=PurchaseOrderOut)
def update_purchase_order_status(
    order_id: int,
    payload: PurchaseOrderStatusIn,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    order = lock_row(db, PurchaseOrder, order_id)
    permission = (
        "purchase_orders.approve"
        if payload.status == PurchaseOrderStatus.approved
        else "purchase_orders.create"
    )
    if not has_permission(db, actor, permission):
        raise HTTPException(status_code=403, detail=f"{permission} is required.")
    if order.archived or order.status in {
        PurchaseOrderStatus.received.value,
        PurchaseOrderStatus.cancelled.value,
    }:
        raise HTTPException(status_code=409, detail={"code": "supply_status"})
    allowed = {
        "Draft": {"Submitted", "Cancelled"},
        "Submitted": {"Approved", "Cancelled"},
        "Approved": {"Ordered", "Cancelled"},
        "Ordered": {"Cancelled"},
        "Partially Received": {"Cancelled"},
    }
    if payload.status.value not in allowed.get(order.status, set()):
        raise HTTPException(status_code=409, detail={"code": "supply_status"})
    old = order.status
    order.status = payload.status.value
    if payload.status == PurchaseOrderStatus.approved:
        order.approved_by, order.approved_at = actor.id, datetime.utcnow()
    record_audit(
        db,
        action="Purchase Order status changed",
        entity_type="PurchaseOrder",
        entity_id=order.id,
        user=actor,
        old_values={"status": old},
        new_values={"status": order.status},
    )
    db.commit()
    return purchase_order_out(
        order_query(db).filter(PurchaseOrder.id == order.id).one()
    )


@router.post("/purchase-orders/{order_id}/receive", response_model=PurchaseOrderOut)
def receive_purchase_order(
    order_id: int,
    payload: PurchaseOrderReceiveIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("inventory.manage")),
):
    lock_row(db, PurchaseOrder, order_id)
    order = (
        order_query(db).filter(PurchaseOrder.id == order_id).populate_existing().first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Purchase Order not found.")
    if order.archived or order.status not in {
        "Approved",
        "Ordered",
        "Partially Received",
    }:
        raise HTTPException(status_code=409, detail={"code": "supply_receipt_status"})
    location_id = payload.storage_location_id or order.storage_location_id
    require_row(db, Location, location_id, "Storage location")
    by_id = {item.id: item for item in order.items}
    seen: set[int] = set()
    for receipt in payload.items:
        if receipt.item_id in seen:
            raise HTTPException(
                status_code=422, detail="Receipt item ids must be unique."
            )
        seen.add(receipt.item_id)
        item = by_id.get(receipt.item_id)
        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Purchase Order item {receipt.item_id} not found.",
            )
        if decimal(item.quantity_received) + receipt.quantity > decimal(
            item.quantity_ordered
        ):
            raise HTTPException(
                status_code=409, detail={"code": "supply_receipt_exceeded"}
            )
    try:
        for receipt in payload.items:
            item = by_id[receipt.item_id]
            create_inventory_transaction(
                db,
                part=item.part,
                transaction_type=InventoryTransactionType.purchase,
                transaction_quantity=receipt.quantity,
                actor=actor,
                to_location_id=location_id,
                unit_cost=item.unit_cost,
                purchase_order_item_id=item.id,
                notes=payload.notes or f"Received against {order.order_number}",
            )
            item.quantity_received = decimal(item.quantity_received) + receipt.quantity
            item.part.unit_cost = item.unit_cost
        complete = all(
            decimal(item.quantity_received) >= decimal(item.quantity_ordered)
            for item in order.items
        )
        order.status = (
            PurchaseOrderStatus.received.value
            if complete
            else PurchaseOrderStatus.partially_received.value
        )
        order.updated_at = datetime.utcnow()
        record_audit(
            db,
            action="Purchase Order received",
            entity_type="PurchaseOrder",
            entity_id=order.id,
            user=actor,
            new_values={
                "status": order.status,
                "items": [item.model_dump(mode="json") for item in payload.items],
            },
        )
        if complete:
            notify_roles(
                db,
                roles={"admin", "fleet_manager", "finance"},
                notification_type="Purchase Order received",
                title=f"Purchase Order {order.order_number} received",
                message="All ordered parts have been received.",
                priority="Medium",
                entity_type="PurchaseOrder",
                entity_id=order.id,
                deduplication_key=f"purchase-order:{order.id}:received",
                message_params={"order_number": order.order_number},
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return purchase_order_out(
        order_query(db).filter(PurchaseOrder.id == order.id).one()
    )


@router.put("/purchase-orders/{order_id}/archive", response_model=PurchaseOrderOut)
def archive_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("purchase_orders.create")),
):
    order = require_row(db, PurchaseOrder, order_id, "Purchase Order")
    if order.status not in {"Received", "Cancelled"}:
        raise HTTPException(
            status_code=409,
            detail="Only received or cancelled Purchase Orders can be archived.",
        )
    order.archived, order.archived_at, order.archived_by = (
        True,
        datetime.utcnow(),
        actor.id,
    )
    record_audit(
        db,
        action="Purchase Order archived",
        entity_type="PurchaseOrder",
        entity_id=order.id,
        user=actor,
        new_values={"archived": True},
    )
    db.commit()
    return purchase_order_out(
        order_query(db).filter(PurchaseOrder.id == order.id).one()
    )


@router.post("/purchase-orders/{order_id}/restore", response_model=PurchaseOrderOut)
def restore_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("purchase_orders.create")),
):
    order = require_row(db, PurchaseOrder, order_id, "Purchase Order")
    order.archived, order.archived_at, order.archived_by = False, None, None
    record_audit(
        db,
        action="Purchase Order restored",
        entity_type="PurchaseOrder",
        entity_id=order.id,
        user=actor,
        new_values={"archived": False},
    )
    db.commit()
    return purchase_order_out(
        order_query(db).filter(PurchaseOrder.id == order.id).one()
    )


@router.get(
    "/technicians",
    response_model=list[TechnicianOut],
    dependencies=[Depends(require_permission("technicians.view"))],
)
def list_technicians(include_archived: bool = False, db: Session = Depends(get_db)):
    query = db.query(Technician)
    if not include_archived:
        query = query.filter(Technician.archived.is_(False))
    return query.order_by(Technician.full_name).all()


@router.post("/technicians", response_model=TechnicianOut, status_code=201)
def create_technician(
    payload: TechnicianIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("technicians.manage")),
):
    validate_technician_user(db, payload.user_id)
    row = Technician(**payload.model_dump())
    db.add(row)
    flush_or_conflict(db)
    record_audit(
        db,
        action="Technician created",
        entity_type="Technician",
        entity_id=row.id,
        user=actor,
        new_values=snapshot(row),
    )
    commit_or_conflict(db, "Technician employee number already exists.")
    return row


@router.put("/technicians/{technician_id}/archive", response_model=TechnicianOut)
def archive_technician(
    technician_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("technicians.manage")),
):
    row = lock_row(db, Technician, technician_id)
    ensure_no_clock(db, row.id)
    row.is_active = False
    row.archived, row.archived_at, row.archived_by, row.status = (
        True,
        datetime.utcnow(),
        actor.id,
        "Inactive",
    )
    record_audit(
        db,
        action="Technician archived",
        entity_type="Technician",
        entity_id=row.id,
        user=actor,
        new_values={"archived": True},
    )
    db.commit()
    return row


@router.post("/technicians/{technician_id}/restore", response_model=TechnicianOut)
def restore_technician(
    technician_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("technicians.manage")),
):
    row = require_row(db, Technician, technician_id, "Technician")
    row.is_active = True
    row.archived, row.archived_at, row.archived_by, row.status = (
        False,
        None,
        None,
        "Active",
    )
    record_audit(
        db,
        action="Technician restored",
        entity_type="Technician",
        entity_id=row.id,
        user=actor,
        new_values={"archived": False},
    )
    db.commit()
    return row


@router.post(
    "/work-orders/{work_order_id}/technicians",
    response_model=WorkOrderTechnicianOut,
    status_code=201,
)
def assign_technician(
    work_order_id: int,
    payload: WorkOrderTechnicianIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("maintenance.assign_work_order")),
):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    technician = require_row(db, Technician, payload.technician_id, "Technician")
    editable_order(db, order)
    active_row(technician, "Technician")
    if order.archived or technician.archived:
        raise HTTPException(
            status_code=409, detail="Archived records cannot be assigned."
        )
    row = WorkOrderTechnician(work_order_id=order.id, **payload.model_dump())
    db.add(row)
    flush_or_conflict(db)
    record_audit(
        db,
        action="Technician assigned",
        entity_type="WorkOrderTechnician",
        entity_id=row.id,
        user=actor,
        new_values=snapshot(row),
    )
    commit_or_conflict(db, "Technician is already assigned to this Work Order.")
    return WorkOrderTechnicianOut(
        id=row.id,
        work_order_id=row.work_order_id,
        technician_id=row.technician_id,
        technician_name=technician.full_name,
        estimated_hours=row.estimated_hours,
        task_description=row.task_description,
    )


@router.post(
    "/work-orders/{work_order_id}/labor", response_model=LaborEntryOut, status_code=201
)
def create_labor_entry(
    work_order_id: int,
    payload: LaborEntryIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("labor.manage")),
):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    technician = require_row(db, Technician, payload.technician_id, "Technician")
    active_row(technician, "Technician")
    if payload.hourly_rate is not None and not has_permission(
        db, actor, "maintenance.manage_costs"
    ):
        raise HTTPException(
            status_code=403,
            detail="maintenance.manage_costs is required to override labor rates.",
        )
    hours = payload.actual_hours
    if hours is None and payload.clock_in and payload.clock_out:
        hours = Decimal(
            str((payload.clock_out - payload.clock_in).total_seconds() / 3600)
        ).quantize(Decimal("0.01"))
    rate = (
        payload.hourly_rate
        if payload.hourly_rate is not None
        else decimal(technician.hourly_rate)
    )
    try:
        row = add_labor_entry(
            db,
            work_order=order,
            technician=technician,
            actual_hours=hours or Decimal("0"),
            hourly_rate=rate,
            actor=actor,
            clock_in=payload.clock_in,
            clock_out=payload.clock_out,
            task_description=payload.task_description,
            notes=payload.notes,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return labor_out(row)


@router.get(
    "/work-orders/{work_order_id}/labor",
    response_model=list[LaborEntryOut],
    dependencies=[Depends(require_permission("maintenance.view"))],
)
def list_labor_entries(work_order_id: int, db: Session = Depends(get_db)):
    require_row(db, WorkOrder, work_order_id, "Work Order")
    rows = (
        db.query(LaborEntry)
        .options(joinedload(LaborEntry.technician))
        .filter(
            LaborEntry.work_order_id == work_order_id, LaborEntry.archived.is_(False)
        )
        .all()
    )
    return [labor_out(row) for row in rows]


@router.delete(
    "/work-orders/{work_order_id}/labor/{entry_id}",
    response_model=WorkOrderCostBreakdownOut,
)
def archive_labor_entry(
    work_order_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("labor.manage")),
):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    row = (
        db.query(LaborEntry)
        .filter(LaborEntry.id == entry_id, LaborEntry.work_order_id == work_order_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Labor entry not found.")
    editable_order(db, order)
    if row.clock_in and not row.clock_out:
        raise HTTPException(status_code=409, detail={"code": "supply_clock_active"})
    row.archived = True
    record_audit(
        db,
        action="Labor entry archived",
        entity_type="LaborEntry",
        entity_id=row.id,
        user=actor,
        new_values={"archived": True},
    )
    recalculate_work_order_costs(db, order)
    db.commit()
    return cost_breakdown(order)


@router.post(
    "/work-orders/{work_order_id}/vendor-charges",
    response_model=WorkOrderCostBreakdownOut,
    status_code=201,
)
def add_vendor_charge(
    work_order_id: int,
    payload: VendorChargeIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("maintenance.manage_costs")),
):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    require_row(db, Vendor, payload.vendor_id, "Vendor")
    editable_order(db, order)
    active_row(require_row(db, Vendor, payload.vendor_id, "Vendor"), "Vendor")
    validate_charge_attachment(db, order, payload.attachment_id)
    row = WorkOrderVendorCharge(work_order_id=order.id, **payload.model_dump())
    db.add(row)
    flush_or_conflict(db)
    record_audit(
        db,
        action="Vendor charge created",
        entity_type="WorkOrderVendorCharge",
        entity_id=row.id,
        user=actor,
        new_values=snapshot(row),
    )
    recalculate_work_order_costs(db, order)
    db.commit()
    return cost_breakdown(order)


@router.delete(
    "/work-orders/{work_order_id}/vendor-charges/{charge_id}",
    response_model=WorkOrderCostBreakdownOut,
)
def archive_vendor_charge(
    work_order_id: int,
    charge_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("maintenance.manage_costs")),
):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    row = (
        db.query(WorkOrderVendorCharge)
        .filter(
            WorkOrderVendorCharge.id == charge_id,
            WorkOrderVendorCharge.work_order_id == work_order_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Vendor charge not found.")
    editable_order(db, order)
    row.archived = True
    record_audit(
        db,
        action="Vendor charge archived",
        entity_type="WorkOrderVendorCharge",
        entity_id=row.id,
        user=actor,
        new_values={"archived": True},
    )
    recalculate_work_order_costs(db, order)
    db.commit()
    return cost_breakdown(order)


@router.put(
    "/work-orders/{work_order_id}/cost-adjustments",
    response_model=WorkOrderCostBreakdownOut,
)
def update_cost_adjustments(
    work_order_id: int,
    payload: WorkOrderCostAdjustmentsIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("maintenance.manage_costs")),
):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    old = {"tax_amount": order.tax_amount, "discount_amount": order.discount_amount}
    editable_order(db, order)
    if "vendor_id" in payload.model_fields_set:
        if payload.vendor_id is not None:
            active_row(require_row(db, Vendor, payload.vendor_id, "Vendor"), "Vendor")
        order.vendor_id = payload.vendor_id
    order.other_cost = payload.other_cost
    order.tax_amount, order.discount_amount = (
        payload.tax_amount,
        payload.discount_amount,
    )
    recalculate_work_order_costs(db, order)
    record_audit(
        db,
        action="Work Order costs adjusted",
        entity_type="WorkOrder",
        entity_id=order.id,
        user=actor,
        old_values=old,
        new_values=payload.model_dump(mode="json"),
    )
    db.commit()
    return cost_breakdown(order)


def cost_breakdown(order: WorkOrder) -> WorkOrderCostBreakdownOut:
    return WorkOrderCostBreakdownOut(
        other_cost=decimal(order.other_cost),
        labor_cost=decimal(order.labor_cost),
        parts_cost=decimal(order.parts_cost),
        external_vendor_cost=decimal(order.external_vendor_cost),
        tax_amount=decimal(order.tax_amount),
        discount_amount=decimal(order.discount_amount),
        total_actual_cost=decimal(order.total_cost),
    )


@router.get(
    "/work-orders/{work_order_id}/cost-breakdown",
    response_model=WorkOrderCostBreakdownOut,
    dependencies=[Depends(require_permission("maintenance.view"))],
)
def get_cost_breakdown(work_order_id: int, db: Session = Depends(get_db)):
    return cost_breakdown(require_row(db, WorkOrder, work_order_id, "Work Order"))


@router.get(
    "/maintenance/reports/parts-by-vehicle",
    dependencies=[Depends(require_permission("reports.view"))],
)
def parts_by_vehicle(vehicle_id: int | None = None, db: Session = Depends(get_db)):
    query = (
        db.query(
            WorkOrder.vehicle_id,
            Part.id,
            Part.part_number,
            Part.name,
            func.sum(WorkOrderPart.quantity - WorkOrderPart.quantity_returned),
            func.sum(WorkOrderPart.total_cost),
        )
        .join(WorkOrderPart, WorkOrderPart.work_order_id == WorkOrder.id)
        .join(Part, Part.id == WorkOrderPart.part_id)
        .filter(WorkOrderPart.archived.is_(False), WorkOrder.archived.is_(False))
    )
    if vehicle_id is not None:
        query = query.filter(WorkOrder.vehicle_id == vehicle_id)
    return [
        {
            "vehicle_id": row[0],
            "part_id": row[1],
            "part_number": row[2],
            "part_name": row[3],
            "quantity": decimal(row[4]),
            "cost": decimal(row[5]),
        }
        for row in query.group_by(
            WorkOrder.vehicle_id, Part.id, Part.part_number, Part.name
        ).all()
    ]


@router.get(
    "/maintenance/reports/low-stock",
    dependencies=[Depends(require_permission("reports.view"))],
)
def low_stock_report(db: Session = Depends(get_db)):
    return list_inventory(low_stock_only=True, db=db)


@router.get(
    "/maintenance/reports/inventory-value",
    dependencies=[Depends(require_permission("reports.view"))],
)
def inventory_value_report(db: Session = Depends(get_db)):
    rows = (
        db.query(
            PartInventory.location_id,
            func.sum(PartInventory.quantity_on_hand * Part.unit_cost),
        )
        .join(Part, Part.id == PartInventory.part_id)
        .filter(Part.archived.is_(False))
        .group_by(PartInventory.location_id)
        .all()
    )
    return {
        "locations": [{"location_id": row[0], "value": money(row[1])} for row in rows],
        "total_value": money(sum(decimal(row[1]) for row in rows)),
    }


@router.get(
    "/maintenance/reports/vendor-spend",
    dependencies=[Depends(require_permission("reports.view"))],
)
def vendor_spend_report(db: Session = Depends(get_db)):
    # Procurement spend is received stock (including partial receipts), never
    # Work Order part consumption of that same stock. Services linked to an
    # itemized Work Order do not duplicate the vendor-charge ledger.
    received = (
        db.query(
            PurchaseOrder.vendor_id,
            func.sum(PurchaseOrderItem.quantity_received * PurchaseOrderItem.unit_cost),
        )
        .join(
            PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id
        )
        .group_by(PurchaseOrder.vendor_id)
        .all()
    )
    services = (
        db.query(VehicleService.vendor_id, func.sum(VehicleService.cost))
        .filter(
            VehicleService.archived.is_(False),
            VehicleService.vendor_id.isnot(None),
            VehicleService.work_order_id.is_(None),
        )
        .group_by(VehicleService.vendor_id)
        .all()
    )
    charges = (
        db.query(
            WorkOrderVendorCharge.vendor_id, func.sum(WorkOrderVendorCharge.amount)
        )
        .join(WorkOrder, WorkOrder.id == WorkOrderVendorCharge.work_order_id)
        .filter(
            WorkOrderVendorCharge.archived.is_(False),
            WorkOrder.archived.is_(False),
            WorkOrder.status != "Cancelled",
        )
        .group_by(WorkOrderVendorCharge.vendor_id)
        .all()
    )
    totals = {}
    for label, rows in [
        ("received_parts", received),
        ("standalone_services", services),
        ("external_charges", charges),
    ]:
        for vendor_id, amount in rows:
            totals.setdefault(
                vendor_id,
                {
                    "received_parts": Decimal("0"),
                    "standalone_services": Decimal("0"),
                    "external_charges": Decimal("0"),
                },
            )[label] = money(amount)
    vendors = {r.id: r.name for r in db.query(Vendor).all()}
    return [
        {
            "vendor_id": key,
            "vendor_name": vendors.get(key),
            **values,
            "spend": money(sum(values.values())),
        }
        for key, values in sorted(totals.items())
    ]


@router.get(
    "/maintenance/reports/purchase-order-status",
    dependencies=[Depends(require_permission("reports.view"))],
)
def purchase_order_status_report(db: Session = Depends(get_db)):
    return [
        {"status": status, "count": count, "value": money(value)}
        for status, count, value in db.query(
            PurchaseOrder.status,
            func.count(PurchaseOrder.id),
            func.sum(PurchaseOrder.total_amount),
        )
        .filter(PurchaseOrder.archived.is_(False))
        .group_by(PurchaseOrder.status)
        .all()
    ]


@router.get(
    "/maintenance/reports/technician-utilization",
    dependencies=[Depends(require_permission("reports.view"))],
)
def technician_utilization_report(db: Session = Depends(get_db)):
    estimated = (
        db.query(
            WorkOrderTechnician.technician_id.label("technician_id"),
            func.sum(WorkOrderTechnician.estimated_hours).label("hours"),
        )
        .group_by(WorkOrderTechnician.technician_id)
        .subquery()
    )
    actual = (
        db.query(
            LaborEntry.technician_id.label("technician_id"),
            func.sum(LaborEntry.actual_hours).label("hours"),
        )
        .filter(LaborEntry.archived.is_(False))
        .group_by(LaborEntry.technician_id)
        .subquery()
    )
    rows = (
        db.query(
            Technician.id,
            Technician.full_name,
            func.coalesce(estimated.c.hours, 0),
            func.coalesce(actual.c.hours, 0),
        )
        .outerjoin(estimated, estimated.c.technician_id == Technician.id)
        .outerjoin(actual, actual.c.technician_id == Technician.id)
        .filter(Technician.archived.is_(False))
        .all()
    )
    return [
        {
            "technician_id": row[0],
            "technician_name": row[1],
            "estimated_hours": decimal(row[2]),
            "actual_hours": decimal(row[3]),
            "utilization_percent": (
                money(decimal(row[3]) / decimal(row[2]) * 100)
                if decimal(row[2])
                else Decimal("0")
            ),
        }
        for row in rows
    ]


@router.get(
    "/maintenance/reports/estimated-vs-actual-labor",
    dependencies=[Depends(require_permission("reports.view"))],
)
def estimated_vs_actual_labor(db: Session = Depends(get_db)):
    estimated = dict(
        db.query(
            WorkOrderTechnician.work_order_id,
            func.sum(WorkOrderTechnician.estimated_hours),
        )
        .group_by(WorkOrderTechnician.work_order_id)
        .all()
    )
    actual = dict(
        db.query(LaborEntry.work_order_id, func.sum(LaborEntry.actual_hours))
        .filter(LaborEntry.archived.is_(False))
        .group_by(LaborEntry.work_order_id)
        .all()
    )
    return [
        {
            "work_order_id": order_id,
            "estimated_hours": decimal(estimated.get(order_id)),
            "actual_hours": decimal(actual.get(order_id)),
            "variance_hours": decimal(actual.get(order_id))
            - decimal(estimated.get(order_id)),
        }
        for order_id in sorted(set(estimated) | set(actual))
    ]


@router.get(
    "/maintenance/reports/cost-breakdown",
    dependencies=[Depends(require_permission("reports.view"))],
)
def maintenance_cost_breakdown(db: Session = Depends(get_db)):
    from app.services.maintenance_metrics import actual_maintenance_cost

    orders = (
        db.query(WorkOrder)
        .filter(WorkOrder.archived.is_(False), WorkOrder.status == "Completed")
        .all()
    )
    fields = [
        "labor_cost",
        "parts_cost",
        "external_vendor_cost",
        "tax_amount",
        "discount_amount",
        "other_cost",
    ]
    components = {
        field: money(sum(decimal(getattr(order, field)) for order in orders))
        for field in fields
    }
    unlinked = money(
        sum(decimal(order.total_cost) for order in orders if not order.linked_service)
    )
    service_total = money(
        db.query(func.sum(VehicleService.cost))
        .filter(VehicleService.archived.is_(False))
        .scalar()
    )
    total = money(actual_maintenance_cost(db))
    return {
        **components,
        "unlinked_work_order_total": unlinked,
        "service_total": service_total,
        "total_actual_cost": total,
        "service_adjustments": money(
            total
            - sum(components[f] for f in fields if f != "discount_amount")
            + components["discount_amount"]
        ),
        "work_orders": [
            {
                "work_order_id": order.id,
                "vehicle_id": order.vehicle_id,
                "linked_service_id": (
                    order.linked_service.id if order.linked_service else None
                ),
                **cost_breakdown(order).model_dump(),
            }
            for order in orders
        ],
    }


def flush_or_conflict(db: Session):
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "supply_conflict"}
        ) from exc


def validate_charge_attachment(
    db: Session, order: WorkOrder, attachment_id: int | None
):
    if attachment_id is not None:
        attachment = require_row(db, Attachment, attachment_id, "Attachment")
        if (
            attachment.entity_type != "WorkOrder"
            or attachment.entity_id != order.id
            or attachment.archived
        ):
            raise HTTPException(status_code=422, detail={"code": "supply_attachment"})


@router.get(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    dependencies=[Depends(require_permission("vendors.view"))],
)
def get_vendor(vendor_id: int, db: Session = Depends(get_db)):
    return require_row(db, Vendor, vendor_id, "Vendor")


@router.delete("/vendors/{vendor_id}", response_model=VendorOut)
def delete_vendor(
    vendor_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("vendors.manage")),
):
    return archive_vendor(vendor_id, db, actor)


@router.delete("/parts/{part_id}", response_model=PartOut)
def delete_part(
    part_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    return archive_part(part_id, db, actor)


@router.put("/part-categories/{category_id}", response_model=PartCategoryOut)
def update_category(
    category_id: int,
    payload: PartCategoryIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    row = require_row(db, PartCategory, category_id, "Category")
    old = snapshot(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    record_audit(
        db,
        action="Part category updated",
        entity_type="PartCategory",
        entity_id=row.id,
        user=actor,
        old_values=old,
        new_values=snapshot(row),
    )
    commit_or_conflict(db, "Category name already exists.")
    return row


@router.post("/part-categories/{category_id}/restore", response_model=PartCategoryOut)
def restore_category(
    category_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("parts.manage")),
):
    row = require_row(db, PartCategory, category_id, "Category")
    row.archived, row.archived_at, row.archived_by, row.is_active = (
        False,
        None,
        None,
        True,
    )
    record_audit(
        db,
        action="Part category restored",
        entity_type="PartCategory",
        entity_id=row.id,
        user=actor,
        new_values={"archived": False},
    )
    db.commit()
    return row


@router.get("/inventory", dependencies=[Depends(require_permission("inventory.view"))])
def list_inventory(
    location_id: int | None = None,
    low_stock_only: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(PartInventory).options(
        joinedload(PartInventory.part), joinedload(PartInventory.location)
    )
    if location_id is not None:
        query = query.filter(PartInventory.location_id == location_id)
    rows = []
    for row in query.order_by(PartInventory.part_id, PartInventory.location_id).all():
        minimum = (
            row.minimum_stock
            if row.minimum_stock is not None
            else row.part.minimum_stock
        )
        available = row.quantity_on_hand - row.reserved_quantity
        low = available <= minimum
        if low_stock_only and not low:
            continue
        rows.append(
            {
                "id": row.id,
                "part_id": row.part_id,
                "part_number": row.part.part_number,
                "part_name": row.part.name,
                "location_id": row.location_id,
                "location_name": row.location.name,
                "quantity_on_hand": row.quantity_on_hand,
                "reserved_quantity": row.reserved_quantity,
                "available_quantity": available,
                "minimum_stock": minimum,
                "low_stock": low,
                "inventory_value": money(row.quantity_on_hand * row.part.unit_cost),
            }
        )
    return rows


@router.put("/inventory/{part_id}/{location_id}")
def inventory_settings(
    part_id: int,
    location_id: int,
    payload: InventorySettingsIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("inventory.manage")),
):
    part = require_row(db, Part, part_id, "Part")
    row = locked_balance(db, part_id, location_id)
    row = lock_row(db, PartInventory, row.id)
    if payload.reserved_quantity > row.quantity_on_hand:
        raise HTTPException(status_code=409, detail={"code": "supply_reservation"})
    old = snapshot(row)
    row.minimum_stock, row.reserved_quantity = (
        payload.minimum_stock,
        payload.reserved_quantity,
    )
    record_audit(
        db,
        action="Inventory reservation and threshold updated",
        entity_type="PartInventory",
        entity_id=row.id,
        user=actor,
        old_values=old,
        new_values=snapshot(row),
    )
    refresh_low_stock(db, part, row)
    db.commit()
    return {
        "id": row.id,
        "reserved_quantity": row.reserved_quantity,
        "minimum_stock": row.minimum_stock,
    }


@router.post(
    "/work-orders/{work_order_id}/parts/{line_id}/return",
    response_model=WorkOrderPartOut,
)
def partial_part_return(
    work_order_id: int,
    line_id: int,
    payload: PartReturnIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("inventory.manage")),
):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    try:
        line = return_part(
            db,
            order=order,
            line_id=line_id,
            amount=payload.quantity,
            actor=actor,
            notes=payload.notes,
        )
        db.commit()
        return work_order_part_out(line)
    except Exception:
        db.rollback()
        raise


def validate_technician_user(db: Session, user_id: int | None):
    if user_id is None:
        return
    if db.info.get("company_id") is not None:
        if (
            not db.query(CompanyUser)
            .filter(CompanyUser.user_id == user_id, CompanyUser.is_active.is_(True))
            .first()
        ):
            raise HTTPException(status_code=404, detail="Company user not found.")
    else:
        require_row(db, User, user_id, "User")


@router.get(
    "/technicians/{technician_id}",
    response_model=TechnicianOut,
    dependencies=[Depends(require_permission("technicians.view"))],
)
def get_technician(technician_id: int, db: Session = Depends(get_db)):
    return require_row(db, Technician, technician_id, "Technician")


@router.put("/technicians/{technician_id}", response_model=TechnicianOut)
def update_technician(
    technician_id: int,
    payload: TechnicianIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("technicians.manage")),
):
    row = lock_row(db, Technician, technician_id)
    validate_technician_user(db, payload.user_id)
    if not payload.is_active or payload.status == "Inactive":
        ensure_no_clock(db, row.id)
    old = snapshot(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    record_audit(
        db,
        action="Technician updated",
        entity_type="Technician",
        entity_id=row.id,
        user=actor,
        old_values=old,
        new_values=snapshot(row),
    )
    commit_or_conflict(db, "Employee number already exists.")
    return row


def ensure_no_clock(db: Session, technician_id: int):
    if (
        db.query(LaborEntry)
        .filter(
            LaborEntry.technician_id == technician_id,
            LaborEntry.clock_in.isnot(None),
            LaborEntry.clock_out.is_(None),
            LaborEntry.archived.is_(False),
        )
        .first()
    ):
        raise HTTPException(status_code=409, detail={"code": "supply_clock_active"})


@router.delete("/technicians/{technician_id}", response_model=TechnicianOut)
def delete_technician(
    technician_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("technicians.manage")),
):
    return archive_technician(technician_id, db, actor)


@router.get(
    "/work-orders/{work_order_id}/technicians",
    response_model=list[WorkOrderTechnicianOut],
    dependencies=[Depends(require_permission("maintenance.view"))],
)
def list_assignments(work_order_id: int, db: Session = Depends(get_db)):
    require_row(db, WorkOrder, work_order_id, "Work Order")
    return [
        WorkOrderTechnicianOut(
            id=r.id,
            work_order_id=r.work_order_id,
            technician_id=r.technician_id,
            technician_name=r.technician.full_name,
            estimated_hours=r.estimated_hours,
            task_description=r.task_description,
        )
        for r in db.query(WorkOrderTechnician)
        .filter(WorkOrderTechnician.work_order_id == work_order_id)
        .all()
    ]


@router.post(
    "/work-orders/{work_order_id}/labor/clock-in",
    response_model=LaborEntryOut,
    status_code=201,
)
def clock_in(
    work_order_id: int,
    payload: ClockInIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("labor.manage")),
):
    order = editable_order(db, require_row(db, WorkOrder, work_order_id, "Work Order"))
    tech = active_row(lock_row(db, Technician, payload.technician_id), "Technician")
    now = datetime.utcnow()
    validate_clock_overlap(db, tech.id, now)
    row = LaborEntry(
        work_order_id=order.id,
        technician_id=tech.id,
        clock_in=now,
        actual_hours=0,
        hourly_rate=tech.hourly_rate,
        labor_cost=0,
        task_description=payload.task_description,
        notes=payload.notes,
    )
    db.add(row)
    flush_or_conflict(db)
    record_audit(
        db,
        action="Technician clocked in",
        entity_type="LaborEntry",
        entity_id=row.id,
        user=actor,
        new_values=snapshot(row),
    )
    recalculate_work_order_costs(db, order)
    commit_or_conflict(db, "Technician already has an active session.")
    return labor_out(row)


@router.post(
    "/work-orders/{work_order_id}/labor/{entry_id}/clock-out",
    response_model=LaborEntryOut,
)
def clock_out(
    work_order_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("labor.manage")),
):
    order = editable_order(db, require_row(db, WorkOrder, work_order_id, "Work Order"))
    row = require_row(db, LaborEntry, entry_id, "Labor entry")
    lock_row(db, Technician, row.technician_id)
    db.refresh(row)
    if row.work_order_id != order.id:
        raise HTTPException(status_code=404, detail="Labor entry not found.")
    if row.archived or not row.clock_in or row.clock_out:
        raise HTTPException(status_code=409, detail={"code": "supply_clock_inactive"})
    old = snapshot(row)
    row.clock_out = datetime.utcnow()
    row.actual_hours = money(
        Decimal(str((row.clock_out - row.clock_in).total_seconds())) / Decimal("3600")
    )
    row.labor_cost = money(row.actual_hours * row.hourly_rate)
    record_audit(
        db,
        action="Technician clocked out",
        entity_type="LaborEntry",
        entity_id=row.id,
        user=actor,
        old_values=old,
        new_values=snapshot(row),
    )
    recalculate_work_order_costs(db, order)
    db.commit()
    return labor_out(row)


@router.get(
    "/work-orders/{work_order_id}/vendor-charges",
    response_model=list[VendorChargeOut],
    dependencies=[Depends(require_permission("maintenance.view"))],
)
def list_vendor_charges(work_order_id: int, db: Session = Depends(get_db)):
    require_row(db, WorkOrder, work_order_id, "Work Order")
    return [
        VendorChargeOut(
            id=r.id,
            work_order_id=r.work_order_id,
            vendor_id=r.vendor_id,
            vendor_name=r.vendor.name,
            description=r.description,
            amount=r.amount,
            invoice_number=r.invoice_number,
            attachment_id=r.attachment_id,
            archived=r.archived,
        )
        for r in db.query(WorkOrderVendorCharge)
        .filter(
            WorkOrderVendorCharge.work_order_id == work_order_id,
            WorkOrderVendorCharge.archived.is_(False),
        )
        .all()
    ]


@router.get(
    "/purchase-orders/{order_id}",
    response_model=PurchaseOrderOut,
    dependencies=[Depends(require_permission("purchase_orders.view"))],
)
def get_purchase_order(order_id: int, db: Session = Depends(get_db)):
    order = order_query(db).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase Order not found.")
    return purchase_order_out(order)


@router.put("/purchase-orders/{order_id}", response_model=PurchaseOrderOut)
def edit_purchase_order(
    order_id: int,
    payload: PurchaseOrderIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("purchase_orders.create")),
):
    order = lock_row(db, PurchaseOrder, order_id)
    if (
        order.archived
        or order.status != "Draft"
        or payload.status != PurchaseOrderStatus.draft
    ):
        raise HTTPException(status_code=409, detail={"code": "supply_draft_only"})
    active_row(require_row(db, Vendor, payload.vendor_id, "Vendor"), "Vendor")
    active_row(
        require_row(db, Location, payload.storage_location_id, "Location"), "Location"
    )
    for item in payload.items:
        active_row(require_row(db, Part, item.part_id, "Part"), "Part")
    old = snapshot(order)
    order.items.clear()
    db.flush()
    for key, value in payload.model_dump(exclude={"items", "status"}).items():
        setattr(order, key, value)
    order.items = [
        PurchaseOrderItem(
            part_id=i.part_id,
            quantity_ordered=i.quantity_ordered,
            quantity_received=0,
            unit_cost=i.unit_cost,
            line_total=money(i.quantity_ordered * i.unit_cost),
        )
        for i in payload.items
    ]
    order.subtotal = sum(i.line_total for i in order.items)
    order.total_amount = money(
        order.subtotal + order.tax_amount - order.discount_amount
    )
    if order.total_amount < 0:
        raise HTTPException(status_code=422, detail={"code": "supply_discount"})
    record_audit(
        db,
        action="Purchase Order updated",
        entity_type="PurchaseOrder",
        entity_id=order.id,
        user=actor,
        old_values=old,
        new_values=snapshot(order),
    )
    commit_or_conflict(db, "Order number already exists.")
    return purchase_order_out(order)


@router.get(
    "/maintenance/reports/parts-consumption",
    dependencies=[Depends(require_permission("reports.view"))],
)
def parts_consumption(db: Session = Depends(get_db)):
    rows = (
        db.query(
            Part.id,
            Part.part_number,
            Part.name,
            func.sum(WorkOrderPart.quantity - WorkOrderPart.quantity_returned),
            func.sum(WorkOrderPart.total_cost),
        )
        .join(WorkOrderPart, WorkOrderPart.part_id == Part.id)
        .join(WorkOrder, WorkOrder.id == WorkOrderPart.work_order_id)
        .filter(WorkOrderPart.archived.is_(False), WorkOrder.archived.is_(False))
        .group_by(Part.id, Part.part_number, Part.name)
        .all()
    )
    return [
        {
            "part_id": row[0],
            "part_number": row[1],
            "part_name": row[2],
            "quantity": decimal(row[3]),
            "cost": money(row[4]),
        }
        for row in rows
    ]


@router.get(
    "/maintenance/reports/labor-cost",
    dependencies=[Depends(require_permission("reports.view"))],
)
def labor_cost_report(db: Session = Depends(get_db)):
    rows = (
        db.query(
            Technician.id,
            Technician.full_name,
            func.sum(LaborEntry.actual_hours),
            func.sum(LaborEntry.labor_cost),
        )
        .join(LaborEntry, LaborEntry.technician_id == Technician.id)
        .join(WorkOrder, WorkOrder.id == LaborEntry.work_order_id)
        .filter(LaborEntry.archived.is_(False), WorkOrder.archived.is_(False))
        .group_by(Technician.id, Technician.full_name)
        .all()
    )
    return [
        {
            "technician_id": row[0],
            "technician_name": row[1],
            "hours": decimal(row[2]),
            "labor_cost": money(row[3]),
        }
        for row in rows
    ]


@router.get(
    "/work-orders/{work_order_id}/timeline",
    dependencies=[Depends(require_permission("maintenance.view"))],
)
def work_order_timeline(work_order_id: int, db: Session = Depends(get_db)):
    order = require_row(db, WorkOrder, work_order_id, "Work Order")
    related = [
        ("WorkOrder", [order.id]),
        ("WorkOrderPart", [r.id for r in order.part_lines]),
        ("LaborEntry", [r.id for r in order.labor_entries]),
        ("WorkOrderVendorCharge", [r.id for r in order.vendor_charges]),
        ("WorkOrderTechnician", [r.id for r in order.technician_assignments]),
    ]
    transactions = (
        db.query(InventoryTransaction.id)
        .filter(InventoryTransaction.work_order_id == order.id)
        .all()
    )
    related.append(("InventoryTransaction", [r[0] for r in transactions]))
    attachments = (
        db.query(Attachment.id)
        .filter(Attachment.entity_type == "WorkOrder", Attachment.entity_id == order.id)
        .all()
    )
    related.append(("Attachment", [r[0] for r in attachments]))
    if order.linked_service:
        related.append(("VehicleService", [order.linked_service.id]))
    condition = or_(
        *[
            (AuditLog.entity_type == kind) & AuditLog.entity_id.in_(ids)
            for kind, ids in related
            if ids
        ]
    )
    rows = (
        db.query(AuditLog)
        .filter(condition)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "actor": r.username,
            "created_at": r.created_at.isoformat() + "Z",
            "description": r.description,
        }
        for r in rows
    ]


@router.get("/supply-options")
def supply_options(
    db: Session = Depends(get_db), actor: User = Depends(get_current_user)
):
    # Minimal selectors, authorized for the workflows that need them.
    stock = any(
        has_permission(db, actor, p)
        for p in (
            "parts.view",
            "inventory.view",
            "inventory.manage",
            "purchase_orders.create",
            "purchase_orders.view",
        )
    )
    vendors = (
        stock
        or has_permission(db, actor, "vendors.view")
        or has_permission(db, actor, "maintenance.manage_costs")
        or has_permission(db, actor, "maintenance.assign_work_order")
    )
    labor = any(
        has_permission(db, actor, p)
        for p in ("technicians.view", "labor.manage", "maintenance.assign_work_order")
    )
    if not (stock or vendors or labor):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    return {
        "parts": (
            [
                {
                    "id": p.id,
                    "name": f"{p.part_number} — {p.name}",
                    "unit_cost": p.unit_cost,
                }
                for p in db.query(Part)
                .filter(Part.archived.is_(False), Part.is_active.is_(True))
                .order_by(Part.part_number)
                .all()
            ]
            if stock
            else []
        ),
        "categories": (
            [
                {"id": p.id, "name": p.name}
                for p in db.query(PartCategory)
                .filter(
                    PartCategory.archived.is_(False), PartCategory.is_active.is_(True)
                )
                .all()
            ]
            if stock
            else []
        ),
        "locations": (
            [
                {"id": p.id, "name": p.name}
                for p in db.query(Location).filter(Location.is_active.is_(True)).all()
            ]
            if stock
            else []
        ),
        "vendors": (
            [
                {"id": p.id, "name": p.name}
                for p in db.query(Vendor)
                .filter(
                    Vendor.archived.is_(False),
                    Vendor.is_active.is_(True),
                    Vendor.status != "Inactive",
                )
                .all()
            ]
            if vendors
            else []
        ),
        "technicians": (
            [
                {"id": p.id, "name": p.full_name}
                for p in db.query(Technician)
                .filter(
                    Technician.archived.is_(False),
                    Technician.is_active.is_(True),
                    Technician.status != "Inactive",
                )
                .all()
            ]
            if labor
            else []
        ),
    }
