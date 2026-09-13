from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    AliasChoices,
    computed_field,
    field_validator,
    field_serializer,
    model_validator,
)


class SupplyModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)


class InventoryTransactionType(str, Enum):
    purchase = "Purchase"
    issue = "Issue to Work Order"
    return_ = "Return from Work Order"
    opening = "Opening Balance"

    @classmethod
    def _missing_(cls, value):
        return cls.return_ if value == "Return" else None

    adjustment = "Adjustment"
    transfer = "Transfer"
    write_off = "Write-Off"


class VendorType(str, Enum):
    workshop = "Workshop"
    parts_supplier = "Parts Supplier"
    fuel_station = "Fuel Station"
    charging_provider = "Charging Provider"
    insurance_company = "Insurance Company"
    tire_supplier = "Tire Supplier"
    towing_company = "Towing Company"
    vehicle_dealer = "Vehicle Dealer"
    other = "Other"


class PurchaseOrderStatus(str, Enum):
    draft = "Draft"
    submitted = "Submitted"
    approved = "Approved"
    ordered = "Ordered"
    partially_received = "Partially Received"
    received = "Received"
    cancelled = "Cancelled"


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class VendorIn(SupplyModel):
    name: str = Field(min_length=1, max_length=200)
    vendor_type: VendorType
    contact_name: str | None = Field(
        default=None,
        max_length=150,
        validation_alias=AliasChoices("contact_name", "contact_person"),
    )
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    payment_terms: str | None = Field(default=None, max_length=150)
    tax_number: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=150)
    country: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    is_active: bool = True
    supported_services: list[str] = Field(default_factory=list)
    status: str = Field(default="Active", max_length=30)
    rating: Decimal | None = Field(default=None, ge=0, le=5)

    @field_validator(
        "name",
        "contact_name",
        "email",
        "phone",
        "address",
        "payment_terms",
        "tax_number",
        "status",
    )
    @classmethod
    def strip_text(cls, value):
        return clean(value)


class VendorOut(VendorIn):
    company_id: int

    @computed_field
    @property
    def contact_person(self) -> str | None:
        return self.contact_name

    id: int
    archived: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PartCategoryIn(SupplyModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    is_active: bool = True

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value):
        return clean(value)


class PartCategoryOut(PartCategoryIn):
    id: int
    archived: bool
    model_config = ConfigDict(from_attributes=True)


class PartIn(SupplyModel):
    part_number: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category_id: int
    unit: str = Field(min_length=1, max_length=30)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=4)
    supplier_id: int | None = Field(
        default=None, validation_alias=AliasChoices("supplier_id", "default_vendor_id")
    )
    manufacturer: str | None = Field(default=None, max_length=200)
    barcode: str | None = Field(default=None, max_length=100)
    minimum_stock: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=3)
    is_active: bool = True

    @field_validator("part_number", "name", "description", "unit", "barcode")
    @classmethod
    def strip_text(cls, value):
        return clean(value)


class InventoryBalanceOut(SupplyModel):
    location_id: int
    location_name: str
    quantity_on_hand: Decimal
    reserved_quantity: Decimal = Decimal("0")
    minimum_stock: Decimal | None = None
    available_quantity: Decimal = Decimal("0")


class PartOut(PartIn):
    company_id: int

    @computed_field
    @property
    def default_vendor_id(self) -> int | None:
        return self.supplier_id

    id: int
    category_name: str
    supplier_name: str | None = None
    archived: bool
    total_stock: Decimal = Decimal("0")
    inventory: list[InventoryBalanceOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class InventoryTransactionIn(SupplyModel):
    part_id: int
    transaction_type: InventoryTransactionType
    quantity: Decimal = Field(decimal_places=3)
    unit_cost: Decimal | None = Field(default=None, ge=0, decimal_places=4)
    from_location_id: int | None = None
    to_location_id: int | None = None
    work_order_id: int | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_locations(self):
        kind = self.transaction_type
        if self.quantity == 0:
            raise ValueError("quantity must not be zero")
        if kind != InventoryTransactionType.adjustment and self.quantity < 0:
            raise ValueError("quantity must be positive except for adjustments")
        if (
            kind in {InventoryTransactionType.issue, InventoryTransactionType.write_off}
            and not self.from_location_id
        ):
            raise ValueError("from_location_id is required")
        if (
            kind
            in {
                InventoryTransactionType.purchase,
                InventoryTransactionType.return_,
                InventoryTransactionType.opening,
            }
            and not self.to_location_id
        ):
            raise ValueError("to_location_id is required")
        if kind == InventoryTransactionType.transfer and (
            not self.from_location_id
            or not self.to_location_id
            or self.from_location_id == self.to_location_id
        ):
            raise ValueError("a transfer requires different from and to locations")
        if kind == InventoryTransactionType.adjustment and not (
            self.from_location_id or self.to_location_id
        ):
            raise ValueError("an adjustment requires a location")
        if kind == InventoryTransactionType.issue and not self.work_order_id:
            raise ValueError("work_order_id is required when issuing parts")
        if kind == InventoryTransactionType.return_:
            raise ValueError(
                "Use the Work Order part return endpoint to return issued stock"
            )
        if kind not in {InventoryTransactionType.issue} and self.work_order_id:
            raise ValueError("work_order_id is only valid when issuing parts")
        if (
            kind
            in {InventoryTransactionType.purchase, InventoryTransactionType.opening}
            and self.from_location_id
        ):
            raise ValueError("Incoming stock cannot have a source location")
        if (
            kind in {InventoryTransactionType.issue, InventoryTransactionType.write_off}
            and self.to_location_id
        ):
            raise ValueError("Outgoing stock cannot have a destination location")
        if (
            kind == InventoryTransactionType.adjustment
            and self.from_location_id
            and self.to_location_id
        ):
            raise ValueError("An adjustment must specify exactly one location")
        return self


class InventoryTransactionOut(SupplyModel):
    id: int
    part_id: int
    transaction_type: InventoryTransactionType
    quantity: Decimal
    unit_cost: Decimal | None
    from_location_id: int | None
    to_location_id: int | None
    work_order_id: int | None
    purchase_order_item_id: int | None
    notes: str | None
    performed_by: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WorkOrderPartIssueIn(SupplyModel):
    part_id: int
    location_id: int
    quantity: Decimal = Field(gt=0, decimal_places=3)
    unit_cost: Decimal | None = Field(default=None, ge=0, decimal_places=4)
    notes: str | None = None


class WorkOrderPartOut(SupplyModel):
    quantity_returned: Decimal = Decimal("0")
    id: int
    work_order_id: int
    part_id: int
    part_number: str
    part_name: str
    location_id: int
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    archived: bool


class PurchaseOrderItemIn(SupplyModel):
    part_id: int
    quantity_ordered: Decimal = Field(gt=0, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, decimal_places=4)


class PurchaseOrderIn(SupplyModel):
    order_number: str = Field(min_length=1, max_length=100)
    vendor_id: int
    storage_location_id: int
    status: PurchaseOrderStatus = PurchaseOrderStatus.draft
    order_date: datetime | None = None
    expected_date: datetime | None = None
    notes: str | None = None
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    items: list[PurchaseOrderItemIn] = Field(min_length=1)

    @field_validator("order_number", "notes")
    @classmethod
    def strip_text(cls, value):
        return clean(value)

    @model_validator(mode="after")
    def unique_parts(self):
        ids = [item.part_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("purchase order parts must be unique")
        return self


class PurchaseOrderItemOut(SupplyModel):
    id: int
    part_id: int
    part_number: str
    part_name: str
    quantity_ordered: Decimal
    quantity_received: Decimal
    unit_cost: Decimal
    line_total: Decimal


class PurchaseOrderOut(SupplyModel):
    company_id: int
    created_by: int | None
    approved_by: int | None
    id: int
    order_number: str
    vendor_id: int
    vendor_name: str
    storage_location_id: int
    status: PurchaseOrderStatus
    order_date: datetime | None
    expected_date: datetime | None
    notes: str | None
    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    archived: bool
    items: list[PurchaseOrderItemOut]
    created_at: datetime
    updated_at: datetime


class PurchaseOrderStatusIn(SupplyModel):
    status: PurchaseOrderStatus


class ReceiveItemIn(SupplyModel):
    item_id: int
    quantity: Decimal = Field(gt=0, decimal_places=3)


class PurchaseOrderReceiveIn(SupplyModel):
    items: list[ReceiveItemIn] = Field(min_length=1)
    storage_location_id: int | None = None
    notes: str | None = None


class TechnicianIn(SupplyModel):
    user_id: int | None = None
    specialization: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    employee_number: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    hourly_rate: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    status: str = Field(default="Active", max_length=30)

    @field_validator("employee_number", "full_name", "email", "phone", "status")
    @classmethod
    def strip_text(cls, value):
        return clean(value)


class TechnicianOut(TechnicianIn):
    company_id: int
    id: int
    archived: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WorkOrderTechnicianIn(SupplyModel):
    technician_id: int
    estimated_hours: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    task_description: str | None = None


class WorkOrderTechnicianOut(WorkOrderTechnicianIn):
    id: int
    work_order_id: int
    technician_name: str


class LaborEntryIn(SupplyModel):
    notes: str | None = None
    technician_id: int
    actual_hours: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2,
        validation_alias=AliasChoices("actual_hours", "hours"),
    )
    clock_in: datetime | None = None
    clock_out: datetime | None = None
    hourly_rate: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    task_description: str | None = None

    @field_validator("clock_in", "clock_out")
    @classmethod
    def utc_timestamp(cls, value):
        return (
            value.astimezone(timezone.utc).replace(tzinfo=None)
            if value and value.tzinfo
            else value
        )

    @model_validator(mode="after")
    def calculate_hours_contract(self):
        if bool(self.clock_in) != bool(self.clock_out):
            raise ValueError(
                "Both clock timestamps are required for a manual timed entry"
            )
        if self.clock_out and not self.clock_in:
            raise ValueError("clock_in is required with clock_out")
        if self.clock_in and self.clock_out and self.clock_out < self.clock_in:
            raise ValueError("clock_out cannot be before clock_in")
        if self.actual_hours is None and not (self.clock_in and self.clock_out):
            raise ValueError("actual_hours or both clock timestamps are required")
        return self


class LaborEntryOut(SupplyModel):
    notes: str | None = None

    @computed_field
    @property
    def hours(self) -> Decimal:
        return self.actual_hours

    id: int
    work_order_id: int
    technician_id: int
    technician_name: str
    actual_hours: Decimal
    clock_in: datetime | None
    clock_out: datetime | None
    hourly_rate: Decimal
    labor_cost: Decimal
    task_description: str | None
    archived: bool

    @field_serializer("clock_in", "clock_out")
    def serialize_clock(self, value):
        return value.replace(tzinfo=timezone.utc).isoformat() if value else None


class VendorChargeIn(SupplyModel):
    invoice_number: str | None = Field(default=None, max_length=150)
    attachment_id: int | None = None
    vendor_id: int
    description: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(ge=0, decimal_places=2)


class WorkOrderCostAdjustmentsIn(SupplyModel):
    vendor_id: int | None = None
    other_cost: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)


class WorkOrderCostBreakdownOut(SupplyModel):
    other_cost: Decimal = Decimal("0")
    labor_cost: Decimal
    parts_cost: Decimal
    external_vendor_cost: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_actual_cost: Decimal


class ReportRow(SupplyModel):
    model_config = ConfigDict(extra="allow")


class ClockInIn(SupplyModel):
    technician_id: int
    task_description: str | None = None
    notes: str | None = None


class PartReturnIn(SupplyModel):
    quantity: Decimal = Field(gt=0, decimal_places=3)
    notes: str | None = None


class InventorySettingsIn(SupplyModel):
    minimum_stock: Decimal | None = Field(default=None, ge=0, decimal_places=3)
    reserved_quantity: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=3)


class VendorChargeOut(VendorChargeIn):
    id: int
    work_order_id: int
    vendor_name: str
    archived: bool
