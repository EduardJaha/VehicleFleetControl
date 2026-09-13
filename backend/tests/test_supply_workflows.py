"""HTTP-level supply regression tests with real tenancy and SQL constraints."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
from fastapi import Depends, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.security import get_current_user
from app.db.session import Base, TenantSession, get_db, set_tenant_context
from app.main import app
from app.models import (
    Company,
    CompanyUser,
    User,
    Vehicle,
    WorkOrder,
    Location,
    AuditLog,
    Notification,
    LaborEntry,
    InventoryTransaction,
    PartInventory,
    Part,
)


@pytest.fixture()
def api(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'supply.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(
        engine, class_=TenantSession, expire_on_commit=False, autoflush=False
    )
    with factory() as db:
        for company_id in (1, 2):
            db.add(
                Company(
                    id=company_id, name=f"Company {company_id}", slug=f"c{company_id}"
                )
            )
            db.flush()
            for role in ("admin", "mechanic", "finance", "viewer"):
                user = User(
                    company_id=company_id,
                    email=f"{company_id}-{role}@example.com",
                    full_name=role,
                    hashed_password="unused",
                    role=role,
                )
                db.add(user)
                db.flush()
                db.add(CompanyUser(company_id=company_id, user_id=user.id, role=role))
            vehicle = Vehicle(
                company_id=company_id,
                brand="Ford",
                model="Transit",
                fuel_type="Diesel",
                vehicle_location="Depot",
                license_plate=f"01-00{company_id}-AA",
                registration_country="XK",
                license_plate_normalized=f"0100{company_id}AA",
                odometer_km=100,
            )
            db.add(vehicle)
            db.flush()
            db.add(
                WorkOrder(
                    id=company_id,
                    company_id=company_id,
                    vehicle_id=vehicle.id,
                    title="Repair",
                    status="Open",
                    created_at=datetime.utcnow() - timedelta(days=2),
                )
            )
            db.add(
                Location(
                    id=company_id,
                    company_id=company_id,
                    code="MAIN",
                    name=f"Store {company_id}",
                )
            )
        db.commit()

    def database():
        with factory() as db:
            yield db

    def actor(
        db=Depends(get_db),
        x_test_company: int = Header(1),
        x_test_role: str = Header("admin"),
    ):
        set_tenant_context(db, x_test_company)
        db.info["company_role"] = x_test_role
        return (
            db.query(User)
            .filter(User.email == f"{x_test_company}-{x_test_role}@example.com")
            .one()
        )

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    client = TestClient(app)
    yield client, factory
    app.dependency_overrides.clear()
    client.close()
    engine.dispose()


def call(api, method, path, payload=None, expected=200, company=1, role="admin"):
    client, _ = api
    r = client.request(
        method,
        "/api/v1" + path,
        json=payload,
        headers={"x-test-company": str(company), "x-test-role": role},
    )
    assert r.status_code == expected, (method, path, r.status_code, r.text)
    return r.json()


def masters(api, company=1):
    vendor = call(
        api,
        "POST",
        "/vendors",
        {
            "name": "Supply Co",
            "vendor_type": "Parts Supplier",
            "contact_person": "Arta",
            "city": "Prishtina",
        },
        201,
        company,
    )
    category = call(api, "POST", "/part-categories", {"name": "Filters"}, 201, company)
    part = call(
        api,
        "POST",
        "/parts",
        {
            "part_number": "OF-1",
            "name": "Oil Filter",
            "unit": "piece",
            "category_id": category["id"],
            "default_vendor_id": vendor["id"],
            "barcode": "12345",
            "manufacturer": "Fleet",
            "unit_cost": "12.3456",
            "minimum_stock": "2",
        },
        201,
        company,
    )
    tech = call(
        api,
        "POST",
        "/technicians",
        {
            "employee_number": "T1",
            "full_name": "Teknik",
            "hourly_rate": "30",
            "specialization": "Engine",
        },
        201,
        company,
    )
    return vendor, category, part, tech


def movement(api, part, amount="10", company=1, **overrides):
    return call(
        api,
        "POST",
        "/inventory-transactions",
        {
            "part_id": part["id"],
            "transaction_type": "Opening Balance",
            "quantity": amount,
            "to_location_id": company,
            **overrides,
        },
        201,
        company,
    )


def test_vendor_crud_aliases_uniqueness_archive_restore_and_tenant_scope(api):
    v, cat, p, _ = masters(api)
    v2, _, _, _ = masters(api, 2)
    assert v["contact_person"] == "Arta" and v["company_id"] == 1
    assert v2["company_id"] == 2
    call(api, "POST", "/vendors", {"name": "Supply Co", "vendor_type": "Workshop"}, 409)
    changed = call(
        api,
        "PUT",
        f'/vendors/{v["id"]}',
        {
            "name": "Updated",
            "vendor_type": "Other",
            "contact_person": "Besa",
            "rating": "4.5",
            "notes": "Reviewed",
        },
    )
    assert changed["contact_person"] == "Besa" and changed["rating"] == "4.5"
    call(api, "DELETE", f'/vendors/{v["id"]}')
    assert call(api, "GET", "/vendors") == []
    assert call(api, "GET", f'/vendors/{v["id"]}')["archived"]
    assert not call(api, "POST", f'/vendors/{v["id"]}/restore', {})["archived"]
    for method, payload in [
        ("GET", None),
        ("DELETE", None),
        ("PUT", {"name": "Bad", "vendor_type": "Other"}),
    ]:
        call(api, method, f'/vendors/{v2["id"]}', payload, 404)
    call(api, "POST", f'/vendors/{v2["id"]}/restore', {}, 404)


def test_part_search_uniqueness_and_reference_validation(api):
    _, category, part, _ = masters(api)
    vendor2, category2, _, _ = masters(api, 2)
    for search in ("OF-1", "Oil", "12345", "Filters", "Supply Co"):
        assert len(call(api, "GET", f"/parts?search={search}")) == 1
    payload = {
        "part_number": "OF-1",
        "name": "Another",
        "unit": "piece",
        "category_id": category["id"],
    }
    call(api, "POST", "/parts", payload, 409)
    call(
        api,
        "POST",
        "/parts",
        {**payload, "part_number": "OTHER", "barcode": "12345"},
        409,
    )
    call(
        api,
        "POST",
        "/parts",
        {**payload, "part_number": "OTHER", "category_id": category2["id"]},
        404,
    )
    call(
        api,
        "POST",
        "/parts",
        {**payload, "part_number": "OTHER", "default_vendor_id": vendor2["id"]},
        404,
    )
    assert part["default_vendor_id"] == part["supplier_id"]
    call(api, "DELETE", f'/parts/{part["id"]}')
    assert call(api, "GET", "/parts") == []
    call(api, "POST", f'/parts/{part["id"]}/restore', {})
    assert len(call(api, "GET", "/parts")) == 1


def test_inventory_reservations_negative_stock_and_failed_transfer_roll_back(api):
    _, _, part, _ = masters(api)
    movement(api, part, "5")
    call(
        api,
        "PUT",
        f'/inventory/{part["id"]}/1',
        {"reserved_quantity": "4", "minimum_stock": "2"},
    )
    before = call(api, "GET", "/inventory-transactions")
    call(
        api,
        "POST",
        "/work-orders/1/parts",
        {"part_id": part["id"], "location_id": 1, "quantity": "2"},
        409,
    )
    call(
        api,
        "POST",
        "/inventory-transactions",
        {
            "part_id": part["id"],
            "transaction_type": "Transfer",
            "from_location_id": 1,
            "to_location_id": 2,
            "quantity": "1",
        },
        404,
    )
    assert call(api, "GET", "/inventory-transactions") == before
    stock = call(api, "GET", "/inventory")[0]
    assert (
        Decimal(stock["quantity_on_hand"]) == 5
        and Decimal(stock["available_quantity"]) == 1
    )
    with api[1]() as db:
        assert db.query(InventoryTransaction).count() == 1
        assert (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "InventoryTransaction")
            .count()
            == 1
        )
        assert (
            db.query(Notification).filter(Notification.status == "Unread").count() == 2
        )  # admin+mechanic


def test_issue_partial_return_full_return_and_server_costs(api):
    _, _, p, _ = masters(api)
    movement(api, p)
    line = call(
        api,
        "POST",
        "/work-orders/1/parts",
        {
            "part_id": p["id"],
            "location_id": 1,
            "quantity": "3",
            "total_cost": "0",
            "line_total": "9999",
        },
        201,
    )
    assert Decimal(line["total_cost"]) == Decimal("37.04")
    partial = call(
        api, "POST", f'/work-orders/1/parts/{line["id"]}/return', {"quantity": "1"}
    )
    assert Decimal(partial["total_cost"]) == Decimal("24.69")
    call(
        api, "POST", f'/work-orders/1/parts/{line["id"]}/return', {"quantity": "3"}, 409
    )
    call(api, "DELETE", f'/work-orders/1/parts/{line["id"]}')
    call(api, "DELETE", f'/work-orders/1/parts/{line["id"]}', expected=409)
    assert Decimal(call(api, "GET", "/work-orders/1/cost-breakdown")["parts_cost"]) == 0
    assert Decimal(call(api, "GET", "/inventory")[0]["quantity_on_hand"]) == 10
    call(
        api,
        "POST",
        "/inventory-transactions",
        {
            "part_id": p["id"],
            "transaction_type": "Return from Work Order",
            "quantity": "1",
            "to_location_id": 1,
        },
        422,
    )


def new_po(api, vendor, part):
    return call(
        api,
        "POST",
        "/purchase-orders",
        {
            "order_number": "PO-1",
            "vendor_id": vendor["id"],
            "storage_location_id": 1,
            "items": [
                {"part_id": part["id"], "quantity_ordered": "5", "unit_cost": "10.1234"}
            ],
            "total": "0",
        },
        201,
    )


def test_purchase_workflow_partial_receipt_permissions_and_totals(api):
    vendor, _, part, _ = masters(api)
    po = new_po(api, vendor, part)
    assert Decimal(po["total_amount"]) == Decimal("50.62")
    item = po["items"][0]["id"]
    receipt = {"items": [{"item_id": item, "quantity": "2"}]}
    call(api, "POST", f'/purchase-orders/{po["id"]}/receive', receipt, 409)
    call(api, "PUT", f'/purchase-orders/{po["id"]}/status', {"status": "Submitted"})
    call(
        api,
        "PUT",
        f'/purchase-orders/{po["id"]}/status',
        {"status": "Approved"},
        403,
        role="mechanic",
    )
    approved = call(
        api,
        "PUT",
        f'/purchase-orders/{po["id"]}/status',
        {"status": "Approved"},
        role="finance",
    )
    assert approved["approved_by"] is not None
    partial = call(
        api, "POST", f'/purchase-orders/{po["id"]}/receive', receipt, role="mechanic"
    )
    assert partial["status"] == "Partially Received"
    call(
        api,
        "POST",
        f'/purchase-orders/{po["id"]}/receive',
        {"items": [{"item_id": item, "quantity": "4"}]},
        409,
    )
    call(
        api,
        "POST",
        f'/purchase-orders/{po["id"]}/receive',
        {"items": [{"item_id": item, "quantity": "1"}] * 2},
        422,
    )
    done = call(
        api,
        "POST",
        f'/purchase-orders/{po["id"]}/receive',
        {"items": [{"item_id": item, "quantity": "3"}]},
    )
    assert done["status"] == "Received"
    assert Decimal(call(api, "GET", "/inventory")[0]["quantity_on_hand"]) == 5
    call(api, "POST", f'/purchase-orders/{po["id"]}/receive', receipt, 409)
    call(api, "PUT", f'/purchase-orders/{po["id"]}/archive', {})
    call(api, "POST", f'/purchase-orders/{po["id"]}/restore', {})
    with api[1]() as db:
        assert db.query(InventoryTransaction).count() == 2
        assert (
            db.query(Notification)
            .filter(Notification.notification_type == "Purchase Order received")
            .count()
            == 2
        )


def test_labor_clocking_calculation_overlap_and_closure(api):
    _, _, _, tech = masters(api)
    now = datetime.utcnow()
    entry = call(
        api,
        "POST",
        "/work-orders/1/labor",
        {
            "technician_id": tech["id"],
            "actual_hours": "999",
            "clock_in": (now - timedelta(hours=4)).isoformat() + "Z",
            "clock_out": (now - timedelta(hours=2)).isoformat() + "Z",
            "task_description": "Repair",
        },
        201,
    )
    assert Decimal(entry["hours"]) == 2 and Decimal(entry["labor_cost"]) == 60
    call(
        api,
        "POST",
        "/work-orders/1/labor",
        {
            "technician_id": tech["id"],
            "clock_in": (now - timedelta(hours=3)).isoformat(),
            "clock_out": (now - timedelta(hours=1)).isoformat(),
        },
        409,
    )
    active = call(
        api,
        "POST",
        "/work-orders/1/labor/clock-in",
        {"technician_id": tech["id"]},
        201,
        role="mechanic",
    )
    call(
        api, "POST", "/work-orders/1/labor/clock-in", {"technician_id": tech["id"]}, 409
    )
    call(api, "DELETE", f'/technicians/{tech["id"]}', expected=409)
    for changes in ({"status": "Cancelled"}, {"archived": True}):
        call(
            api,
            "PUT",
            "/work-orders/1",
            {"vehicle_id": 1, "title": "Repair", **changes},
            409,
        )
    call(api, "PUT", "/work-orders/1/status", {"status": "Cancelled"}, 409)
    call(api, "PUT", "/work-orders/1/archive", {}, 409)
    call(api, "DELETE", "/work-orders/1", expected=409)
    call(
        api,
        "POST",
        "/services",
        {
            "license_plate": "01-001-AA",
            "service_type": "Repair",
            "service_date": now.strftime("%d-%m-%Y"),
            "work_order_id": 1,
        },
        409,
    )
    call(
        api,
        "POST",
        "/work-orders/1/complete",
        {
            "actual_completion_date": now.strftime("%d-%m-%Y"),
            "completed_odometer_km": 100,
            "create_service_record": False,
        },
        409,
    )
    with api[1]() as db:
        row = db.get(LaborEntry, active["id"])
        row.clock_in = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    done = call(
        api,
        "POST",
        f'/work-orders/1/labor/{active["id"]}/clock-out',
        {},
        role="mechanic",
    )
    assert Decimal(done["labor_cost"]) == 30
    call(api, "POST", f'/work-orders/1/labor/{active["id"]}/clock-out', {}, 409)
    assert (
        Decimal(call(api, "GET", "/work-orders/1/cost-breakdown")["labor_cost"]) == 90
    )


def test_work_order_completion_preserves_breakdown_and_service_cost_rule(api):
    vendor, _, part, tech = masters(api)
    movement(api, part)
    call(
        api,
        "POST",
        "/work-orders/1/parts",
        {"part_id": part["id"], "location_id": 1, "quantity": "2", "unit_cost": "125"},
        201,
    )
    call(
        api,
        "POST",
        "/work-orders/1/labor",
        {"technician_id": tech["id"], "hours": "4"},
        201,
    )
    call(
        api,
        "POST",
        "/work-orders/1/vendor-charges",
        {
            "vendor_id": vendor["id"],
            "description": "Towing",
            "amount": "180",
            "invoice_number": "INV-1",
        },
        201,
    )
    call(
        api,
        "PUT",
        "/work-orders/1/cost-adjustments",
        {"other_cost": "20", "tax_amount": "10", "discount_amount": "10"},
    )
    assert (
        Decimal(call(api, "GET", "/work-orders/1/cost-breakdown")["total_actual_cost"])
        == 570
    )
    completed = call(
        api,
        "POST",
        "/work-orders/1/complete",
        {
            "actual_completion_date": datetime.utcnow().strftime("%d-%m-%Y"),
            "completed_odometer_km": 100,
            "service_type": "General Service",
            "next_service_km_interval": 10000,
            "labor_cost": "0",
            "parts_cost": "0",
        },
    )
    assert Decimal(completed["service"]["total_cost"]) == 570
    service = call(api, "GET", f'/services/id/{completed["service"]["id"]}')
    assert Decimal(service["total_cost"]) == 570
    report = call(api, "GET", "/maintenance/reports/cost-breakdown")
    assert Decimal(report["total_actual_cost"]) == 570
    assert Decimal(report["parts_cost"]) == 250
    call(api, "PUT", "/work-orders/1/cost-adjustments", {"other_cost": "999"}, 409)
    call(
        api,
        "POST",
        "/work-orders/1/labor",
        {"technician_id": tech["id"], "hours": "1"},
        409,
    )
    assert len(call(api, "GET", "/work-orders/1/timeline")) >= 6


@pytest.mark.parametrize(
    "path",
    [
        "/vendors",
        "/parts",
        "/part-categories",
        "/inventory",
        "/inventory-transactions",
        "/purchase-orders",
        "/technicians",
        "/maintenance/reports/inventory-value",
    ],
)
def test_read_permissions(api, path):
    call(api, "GET", path, expected=403, role="viewer")


def test_write_permissions_and_cross_tenant_cost_lines(api):
    v, _, p, tech = masters(api)
    v2, _, p2, tech2 = masters(api, 2)
    for path, payload in [
        ("/vendors", {"name": "No", "vendor_type": "Other"}),
        (
            "/parts",
            {"part_number": "No", "name": "No", "category_id": 1, "unit": "piece"},
        ),
        ("/technicians", {"employee_number": "No", "full_name": "No"}),
        (
            "/work-orders/1/vendor-charges",
            {"vendor_id": v["id"], "description": "No", "amount": "1"},
        ),
        ("/work-orders/1/cost-adjustments", {"other_cost": "1"}),
    ]:
        call(
            api,
            "POST" if "adjustments" not in path else "PUT",
            path,
            payload,
            403,
            role="mechanic",
        )
    call(
        api,
        "POST",
        "/work-orders/1/parts",
        {"part_id": p2["id"], "location_id": 1, "quantity": "1"},
        404,
    )
    call(
        api,
        "POST",
        "/work-orders/1/labor",
        {"technician_id": tech2["id"], "hours": "1"},
        404,
    )
    call(
        api,
        "POST",
        "/work-orders/1/vendor-charges",
        {"vendor_id": v2["id"], "description": "No", "amount": "1"},
        404,
    )
    for suffix in (
        "parts",
        "labor",
        "technicians",
        "vendor-charges",
        "cost-breakdown",
        "timeline",
    ):
        call(api, "GET", f"/work-orders/2/{suffix}", expected=404)
    assert len(call(api, "GET", "/vendors")) == 1
    assert call(api, "GET", "/inventory-transactions") == []


def test_concurrent_issues_cannot_oversell(api):
    _, _, part, _ = masters(api)
    movement(api, part, "1")
    client, _ = api

    def issue(_):
        return client.post(
            "/api/v1/work-orders/1/parts",
            json={"part_id": part["id"], "location_id": 1, "quantity": "1"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(issue, range(2)))
    assert sorted(statuses) == [201, 409]
    assert Decimal(call(api, "GET", "/inventory")[0]["quantity_on_hand"]) == 0
    with api[1]() as db:
        assert db.query(InventoryTransaction).count() == 2


def test_active_clock_database_constraint(api):
    _, _, _, tech = masters(api)
    call(
        api, "POST", "/work-orders/1/labor/clock-in", {"technician_id": tech["id"]}, 201
    )
    with api[1]() as db:
        db.add(
            LaborEntry(
                company_id=1,
                work_order_id=1,
                technician_id=tech["id"],
                clock_in=datetime.utcnow(),
                actual_hours=0,
                hourly_rate=30,
                labor_cost=0,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_translation_coverage():
    root = Path(__file__).resolve().parents[2] / "frontend/src/i18n/locales"
    en = json.loads((root / "en/modules.json").read_text())
    sq = json.loads((root / "sq/modules.json").read_text())
    assert en["supply"].keys() == sq["supply"].keys()
    for key in [
        "Opening Balance",
        "Return from Work Order",
        "Parts",
        "Labor",
        "Attachments",
        "Timeline",
        "clockIn",
        "clockOut",
        "parts-consumption",
        "vendor-spend",
    ]:
        assert (
            en["supply"][key]
            and sq["supply"][key]
            and en["supply"][key] != sq["supply"][key]
        )
    assert en["supplyEvents"].keys() == sq["supplyEvents"].keys()
    assert "{{location}}" in sq["notificationContent"]["part_low_stock"]["message"]


def test_low_stock_notification_resolves_and_reopens_after_threshold_update(api):
    _, _, part, _ = masters(api)
    movement(api, part, "1")
    with api[1]() as db:
        assert (
            db.query(Notification).filter(Notification.status == "Unread").count() == 2
        )
    movement(api, part, "9", transaction_type="Purchase")
    with api[1]() as db:
        assert (
            db.query(Notification).filter(Notification.status == "Resolved").count()
            == 2
        )
    call(
        api,
        "PUT",
        f'/inventory/{part["id"]}/1',
        {"minimum_stock": "10", "reserved_quantity": "0"},
    )
    with api[1]() as db:
        assert (
            db.query(Notification).filter(Notification.status == "Unread").count() == 2
        )
        assert db.query(Notification).count() == 2


def test_supply_business_errors_are_localized(api):
    _, _, part, _ = masters(api)
    response = api[0].post(
        "/api/v1/work-orders/1/parts",
        json={"part_id": part["id"], "location_id": 1, "quantity": "1"},
        headers={"Accept-Language": "sq"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "negative_stock"
    assert "pamjaftueshëm" in response.json()["message"]


def test_fractional_stock_arithmetic_does_not_accumulate_sqlite_rounding_error(api):
    _, _, part, _ = masters(api)
    movement(api, part, "0.3")
    for _ in range(3):
        call(
            api,
            "POST",
            "/work-orders/1/parts",
            {"part_id": part["id"], "location_id": 1, "quantity": "0.1"},
            201,
        )
    assert Decimal(call(api, "GET", "/inventory")[0]["quantity_on_hand"]) == 0


def test_concurrent_receipts_cannot_receive_twice(api):
    vendor, _, part, _ = masters(api)
    po = new_po(api, vendor, part)
    call(api, "PUT", f'/purchase-orders/{po["id"]}/status', {"status": "Submitted"})
    call(api, "PUT", f'/purchase-orders/{po["id"]}/status', {"status": "Approved"})

    def receive(_):
        return (
            api[0]
            .post(
                f'/api/v1/purchase-orders/{po["id"]}/receive',
                json={"items": [{"item_id": po["items"][0]["id"], "quantity": "5"}]},
            )
            .status_code
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(receive, range(2))) == [200, 409]
    assert Decimal(call(api, "GET", "/inventory")[0]["quantity_on_hand"]) == 5
