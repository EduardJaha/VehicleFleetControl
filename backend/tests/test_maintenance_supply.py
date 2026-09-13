from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.maintenance_supply import (
    archive_part,
    create_labor_entry,
    create_purchase_order,
    receive_purchase_order,
    update_cost_adjustments,
)
from app.core.authorization import ALL_PERMISSIONS, has_permission
from app.db.session import Base
from app.maintenance_supply_schemas import (
    LaborEntryIn,
    PurchaseOrderIn,
    PurchaseOrderItemIn,
    PurchaseOrderReceiveIn,
    PurchaseOrderStatus,
    ReceiveItemIn,
    WorkOrderCostAdjustmentsIn,
)
from app.models import (
    AuditLog,
    InventoryTransaction,
    Location,
    Notification,
    Part,
    PartCategory,
    PartInventory,
    PurchaseOrder,
    Technician,
    User,
    Vendor,
    Vehicle,
    VehicleService,
    WorkOrder,
    WorkOrderVendorCharge,
)
from app.services.maintenance_supply import (
    create_inventory_transaction,
    issue_part_to_work_order,
)
from app.maintenance_supply_schemas import InventoryTransactionType
from app.api.v1.endpoints.maintenance import actual_maintenance_cost


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def records(db: Session):
    actor = User(
        email="admin@example.com",
        full_name="Admin",
        hashed_password="unused",
        role="admin",
    )
    location_a = Location(code="MAIN", name="Main Store")
    location_b = Location(code="VAN", name="Service Van")
    category = PartCategory(name="Filters")
    vendor = Vendor(
        name="Parts Co",
        vendor_type="Parts Supplier",
        supported_services=[],
        status="Active",
    )
    vehicle = Vehicle(
        brand="Ford",
        model="Transit",
        fuel_type="Diesel",
        vehicle_location="Depot",
        license_plate="01-999-AA",
        registration_country="XK",
        license_plate_normalized="01999AA",
    )
    db.add_all([actor, location_a, location_b, category, vendor, vehicle])
    db.flush()
    part = Part(
        part_number="OF-1",
        name="Oil filter",
        category_id=category.id,
        unit="piece",
        unit_cost=Decimal("12.50"),
        minimum_stock=Decimal("9"),
        supplier_id=vendor.id,
    )
    order = WorkOrder(
        vehicle_id=vehicle.id,
        title="Oil change",
        status="Open",
        priority="Medium",
        source="Manual",
        external_vendor_cost=0,
        tax_amount=0,
        discount_amount=0,
    )
    db.add_all([part, order])
    db.commit()
    return actor, location_a, location_b, vendor, part, order


def test_inventory_transactions_transfer_issue_and_prevent_negative_stock(
    db: Session, records
):
    actor, main, van, _, part, work_order = records
    create_inventory_transaction(
        db,
        part=part,
        transaction_type=InventoryTransactionType.purchase,
        transaction_quantity=Decimal("10"),
        actor=actor,
        to_location_id=main.id,
    )
    create_inventory_transaction(
        db,
        part=part,
        transaction_type=InventoryTransactionType.transfer,
        transaction_quantity=Decimal("3"),
        actor=actor,
        from_location_id=main.id,
        to_location_id=van.id,
    )
    line = issue_part_to_work_order(
        db,
        work_order=work_order,
        part=part,
        location_id=van.id,
        issue_quantity=Decimal("2"),
        actor=actor,
    )
    db.commit()

    assert db.query(PartInventory).filter_by(
        part_id=part.id, location_id=main.id
    ).one().quantity_on_hand == Decimal("7.000")
    assert db.query(PartInventory).filter_by(
        part_id=part.id, location_id=van.id
    ).one().quantity_on_hand == Decimal("1.000")
    assert line.total_cost == Decimal("25.00")
    assert work_order.parts_cost == Decimal("25.00")
    assert db.query(InventoryTransaction).count() == 3
    assert (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "InventoryTransaction")
        .count()
        == 3
    )
    assert (
        db.query(Notification)
        .filter(Notification.notification_type == "Part low stock")
        .count()
        == 2
    )

    with pytest.raises(HTTPException) as error:
        issue_part_to_work_order(
            db,
            work_order=work_order,
            part=part,
            location_id=van.id,
            issue_quantity=Decimal("2"),
            actor=actor,
        )
    db.rollback()
    assert error.value.status_code == 409
    assert db.query(PartInventory).filter_by(
        part_id=part.id, location_id=van.id
    ).one().quantity_on_hand == Decimal("1.000")


def test_purchase_order_receiving_is_partial_then_complete_and_updates_inventory(
    db: Session, records
):
    actor, main, _, vendor, part, _ = records
    payload = PurchaseOrderIn(
        order_number="PO-100",
        vendor_id=vendor.id,
        storage_location_id=main.id,
        status=PurchaseOrderStatus.approved,
        tax_amount=Decimal("2"),
        discount_amount=Decimal("1"),
        items=[
            PurchaseOrderItemIn(
                part_id=part.id, quantity_ordered=Decimal("5"), unit_cost=Decimal("10")
            )
        ],
    )
    created = create_purchase_order(payload, db, actor)
    item_id = created.items[0].id
    partial = receive_purchase_order(
        created.id,
        PurchaseOrderReceiveIn(
            items=[ReceiveItemIn(item_id=item_id, quantity=Decimal("2"))]
        ),
        db,
        actor,
    )
    assert partial.status == PurchaseOrderStatus.partially_received
    assert db.query(PartInventory).filter_by(
        part_id=part.id, location_id=main.id
    ).one().quantity_on_hand == Decimal("2.000")

    with pytest.raises(HTTPException):
        receive_purchase_order(
            created.id,
            PurchaseOrderReceiveIn(
                items=[ReceiveItemIn(item_id=item_id, quantity=Decimal("4"))]
            ),
            db,
            actor,
        )
    assert db.query(PartInventory).filter_by(
        part_id=part.id, location_id=main.id
    ).one().quantity_on_hand == Decimal("2.000")

    completed = receive_purchase_order(
        created.id,
        PurchaseOrderReceiveIn(
            items=[ReceiveItemIn(item_id=item_id, quantity=Decimal("3"))]
        ),
        db,
        actor,
    )
    assert completed.status == PurchaseOrderStatus.received
    assert completed.total_amount == Decimal("51.00")
    assert db.query(PartInventory).filter_by(
        part_id=part.id, location_id=main.id
    ).one().quantity_on_hand == Decimal("5.000")
    assert (
        db.query(Notification)
        .filter(Notification.notification_type == "Purchase Order received")
        .count()
        == 1
    )


def test_labor_parts_vendor_tax_discount_drive_work_order_total(db: Session, records):
    actor, main, _, vendor, part, work_order = records
    create_inventory_transaction(
        db,
        part=part,
        transaction_type=InventoryTransactionType.purchase,
        transaction_quantity=Decimal("5"),
        actor=actor,
        to_location_id=main.id,
    )
    issue_part_to_work_order(
        db,
        work_order=work_order,
        part=part,
        location_id=main.id,
        issue_quantity=Decimal("2"),
        actor=actor,
    )
    technician = Technician(
        employee_number="T-1", full_name="Tech One", hourly_rate=Decimal("40")
    )
    db.add(technician)
    db.flush()
    labor = create_labor_entry(
        work_order.id,
        LaborEntryIn(
            technician_id=technician.id,
            clock_in=datetime.utcnow() - timedelta(hours=2),
            clock_out=datetime.utcnow(),
            task_description="Replace filter",
        ),
        db,
        actor,
    )
    assert labor.actual_hours == Decimal("2.00")
    db.add(
        WorkOrderVendorCharge(
            work_order_id=work_order.id,
            vendor_id=vendor.id,
            description="Disposal",
            amount=Decimal("15"),
        )
    )
    db.flush()
    result = update_cost_adjustments(
        work_order.id,
        WorkOrderCostAdjustmentsIn(
            tax_amount=Decimal("10"), discount_amount=Decimal("5")
        ),
        db,
        actor,
    )
    # The charge endpoint normally triggers recalculation; call its equivalent after direct fixture insertion.
    from app.services.maintenance_supply import recalculate_work_order_costs

    recalculate_work_order_costs(db, work_order)
    db.commit()
    assert work_order.labor_cost == Decimal("80.00")
    assert work_order.parts_cost == Decimal("25.00")
    assert work_order.external_vendor_cost == Decimal("15.00")
    assert work_order.total_cost == Decimal("125.00")
    assert db.query(AuditLog).filter(AuditLog.entity_type == "LaborEntry").count() == 1


def test_linked_service_cost_is_not_double_counted(db: Session, records):
    _, _, _, _, _, work_order = records
    work_order.status = "Completed"
    work_order.actual_completion_date = datetime.utcnow()
    work_order.total_cost = Decimal("125")
    service = VehicleService(
        vehicle_id=work_order.vehicle_id,
        work_order_id=work_order.id,
        service_type="Repair",
        service_date=datetime.utcnow(),
        cost=Decimal("125"),
        source="Work Order",
        status="Completed",
    )
    db.add(service)
    db.commit()
    assert actual_maintenance_cost(db) == Decimal("125.00")


def test_permissions_archiving_and_translation_contract(db: Session, records):
    actor, _, _, _, part, _ = records
    mechanic = User(
        email="mechanic@example.com",
        full_name="Mechanic",
        hashed_password="unused",
        role="mechanic",
    )
    finance = User(
        email="finance@example.com",
        full_name="Finance",
        hashed_password="unused",
        role="finance",
    )
    db.add_all([mechanic, finance])
    db.commit()
    assert {"inventory.manage", "labor.manage", "purchase_orders.approve"}.issubset(
        ALL_PERMISSIONS
    )
    assert has_permission(db, mechanic, "inventory.manage")
    assert not has_permission(db, mechanic, "purchase_orders.approve")
    assert has_permission(db, finance, "purchase_orders.approve")

    archived = archive_part(part.id, db, actor)
    assert archived.archived and not archived.is_active
    assert db.query(AuditLog).filter(AuditLog.action == "Part archived").count() == 1

    root = Path(__file__).resolve().parents[2]
    for language in ("en", "sq"):
        modules = json.loads(
            (
                root
                / "frontend"
                / "src"
                / "i18n"
                / "locales"
                / language
                / "modules.json"
            ).read_text()
        )
        navigation = json.loads(
            (
                root
                / "frontend"
                / "src"
                / "i18n"
                / "locales"
                / language
                / "navigation.json"
            ).read_text()
        )
        assert modules["maintenanceSupply"]["parts"]
        assert navigation["partsInventory"]
