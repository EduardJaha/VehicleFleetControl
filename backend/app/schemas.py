from decimal import Decimal
from enum import Enum, IntEnum
from pydantic import BaseModel, Field, ConfigDict, field_validator
import re
from app.utils.vehicle_catalog import clean_catalog_name

LICENSE_PLATE_REGEX = re.compile(r"^(0[1-7])-[0-9]{3}-[A-Z]{2}$")


class VehicleStatus(IntEnum):
    active = 0
    in_service = 1
    sold = 2
    out_of_use = 3


class VehicleReservationStatus(IntEnum):
    pending = 0
    approved = 1
    rejected = 2
    cancelled = 3


class UserRole(str, Enum):
    admin = "admin"
    fleet_manager = "fleet_manager"
    mechanic = "mechanic"
    driver = "driver"
    finance = "finance"
    viewer = "viewer"


class DriverStatus(str, Enum):
    active = "Active"
    suspended = "Suspended"
    left_company = "Left Company"


class InspectionType(str, Enum):
    daily = "Daily"
    weekly = "Weekly"
    before_trip = "Before Trip"
    after_trip = "After Trip"
    return_inspection = "Return Inspection"


class InspectionItemStatus(str, Enum):
    pass_ = "Pass"
    fail = "Fail"
    not_checked = "Not Checked"


class InspectionOverallStatus(str, Enum):
    passed = "Passed"
    failed = "Failed"
    needs_review = "Needs Review"


class WorkOrderStatus(str, Enum):
    open = "Open"
    assigned = "Assigned"
    in_progress = "In Progress"
    waiting_for_parts = "Waiting for Parts"
    completed = "Completed"
    cancelled = "Cancelled"


class WorkOrderPriority(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"
    critical = "Critical"


class WorkOrderSource(str, Enum):
    manual = "Manual"
    inspection = "Inspection"
    service_reminder = "Service Reminder"
    breakdown = "Breakdown"
    other = "Other"


class ServiceSource(str, Enum):
    manual = "Manual"
    work_order = "Work Order"
    imported = "Imported"


class ReminderStatus(str, Enum):
    upcoming = "Upcoming"
    due_soon = "Due Soon"
    due = "Due"
    overdue = "Overdue"
    resolved = "Resolved"
    dismissed = "Dismissed"


class ReminderStatusUpdate(BaseModel):
    status: ReminderStatus


class UserBase(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.viewer
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address.")
        return email

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Full name is required.")
        return name


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class FirstAdminCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return UserBase.normalize_email(value)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return UserBase.normalize_full_name(value)


class UserOut(UserBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class DriverBase(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    employee_number: str = Field(min_length=1, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    license_number: str = Field(min_length=1, max_length=100)
    license_category: str = Field(min_length=1, max_length=50)
    license_expiry_date: str
    assigned_vehicle_id: int | None = None
    assigned_license_plate: str | None = None
    user_id: int | None = None
    status: DriverStatus = DriverStatus.active
    notes: str | None = None

    @field_validator("full_name", "employee_number", "license_number", "license_category")
    @classmethod
    def required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text

    @field_validator("email")
    @classmethod
    def normalize_optional_email(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        return UserBase.normalize_email(value)

    @field_validator("phone_number", "department", "assigned_license_plate", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class DriverCreate(DriverBase):
    pass


class DriverUpdate(DriverBase):
    pass


class DriverOut(DriverBase):
    id: int
    created_at: str
    updated_at: str
    model_config = ConfigDict(from_attributes=True)


class InspectionItemBase(BaseModel):
    item_name: str = Field(min_length=1, max_length=150)
    status: InspectionItemStatus = InspectionItemStatus.not_checked
    comment: str | None = None

    @field_validator("item_name")
    @classmethod
    def normalize_item_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Item name is required.")
        return text

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class InspectionItemCreate(InspectionItemBase):
    pass


class InspectionItemOut(InspectionItemBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class InspectionBase(BaseModel):
    vehicle_id: int | None = None
    license_plate: str | None = None
    driver_id: int | None = None
    inspection_type: InspectionType
    inspection_date: str
    overall_status: InspectionOverallStatus | None = None
    notes: str | None = None
    inspector: str | None = Field(default=None, max_length=150)
    archived: bool = False
    items: list[InspectionItemCreate] = Field(default_factory=list)

    @field_validator("license_plate", "notes", "inspector")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class InspectionCreate(InspectionBase):
    pass


class InspectionUpdate(InspectionBase):
    pass


class InspectionOut(BaseModel):
    id: int
    vehicle_id: int
    license_plate: str
    vehicle_name: str
    driver_id: int | None = None
    driver_name: str | None = None
    inspection_type: InspectionType
    inspection_date: str
    overall_status: InspectionOverallStatus
    notes: str | None = None
    items: list[InspectionItemOut]
    failed_item_count: int = 0
    inspector: str | None = None
    archived: bool = False
    linked_work_order: "LinkedWorkOrder | None" = None
    created_at: str
    updated_at: str
    model_config = ConfigDict(from_attributes=True)


class WorkOrderBase(BaseModel):
    vehicle_id: int | None = None
    license_plate: str | None = None
    driver_id: int | None = None
    inspection_id: int | None = None
    reminder_service_id: int | None = None
    source: WorkOrderSource = WorkOrderSource.manual
    title: str = Field(min_length=1, max_length=150)
    description: str | None = None
    reported_issue: str | None = None
    priority: WorkOrderPriority = WorkOrderPriority.medium
    status: WorkOrderStatus = WorkOrderStatus.open
    requested_by: str | None = Field(default=None, max_length=150)
    assigned_to: str | None = Field(default=None, max_length=150)
    workshop: str | None = Field(default=None, max_length=150)
    expected_completion_date: str | None = None
    actual_completion_date: str | None = None
    labor_cost: Decimal | None = Field(default=None, ge=0)
    parts_cost: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None
    completed_odometer_km: int | None = Field(default=None, ge=0)
    completion_notes: str | None = None
    completed_by: str | None = Field(default=None, max_length=150)
    archived: bool = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Title is required.")
        return text

    @field_validator("license_plate", "description", "reported_issue", "requested_by", "assigned_to", "workshop", "notes", "completion_notes", "completed_by")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class WorkOrderCreate(WorkOrderBase):
    pass


class WorkOrderUpdate(WorkOrderBase):
    pass


class WorkOrderStatusUpdate(BaseModel):
    status: WorkOrderStatus
    actual_completion_date: str | None = None


class WorkOrderOut(WorkOrderBase):
    id: int
    vehicle_id: int
    license_plate: str
    vehicle_name: str
    driver_name: str | None = None
    total_cost: Decimal | None = None
    created_by: str | None = None
    source_inspection: "LinkedInspection | None" = None
    source_reminder: "LinkedServiceReminder | None" = None
    linked_service: "LinkedService | None" = None
    created_at: str
    updated_at: str
    model_config = ConfigDict(from_attributes=True)


class VehicleFields(BaseModel):
    fuel_type: str
    vehicle_location: str
    license_plate: str
    year: int | None = Field(default=None, ge=1900, le=2100)
    vin_number: str | None = Field(default=None, max_length=50)
    engine_cc: int | None = Field(default=None, ge=50, le=10000)
    odometer_km: int | None = Field(default=None, ge=0, le=2_000_000)
    status: int = 0

    @field_validator("license_plate")
    @classmethod
    def validate_plate(cls, value: str) -> str:
        plate = value.strip().upper().replace(" ", "")
        if not LICENSE_PLATE_REGEX.match(plate):
            raise ValueError("License plate must be in format 01-123-AB.")
        return plate


class VehicleWriteBase(VehicleFields):
    brand_id: int = Field(gt=0)
    model_id: int = Field(gt=0)


class VehicleCreate(VehicleWriteBase):
    pass


class VehicleUpdate(VehicleWriteBase):
    pass


class VehicleOut(VehicleFields):
    id: int
    brand_id: int | None = None
    model_id: int | None = None
    brand: str
    model: str
    status_name: str
    model_config = ConfigDict(from_attributes=True)


class VehicleBrandBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = clean_catalog_name(value)
        if not name:
            raise ValueError("Brand name is required.")
        return name


class VehicleBrandCreate(VehicleBrandBase):
    pass


class VehicleBrandUpdate(VehicleBrandBase):
    pass


class VehicleBrandOut(VehicleBrandBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class VehicleModelBase(BaseModel):
    brand_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = clean_catalog_name(value)
        if not name:
            raise ValueError("Model name is required.")
        return name


class VehicleModelCreate(VehicleModelBase):
    pass


class VehicleModelUpdate(VehicleModelBase):
    pass


class VehicleModelOut(VehicleModelBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class UpdateStatus(BaseModel):
    status: str


class UpdateLocation(BaseModel):
    new_location: str


class AddService(BaseModel):
    license_plate: str
    service_type: str
    description: str | None = None
    service_date: str
    odometer_km: int | None = None
    cost: Decimal | None = None
    workshop: str | None = None
    next_service_date: str | None = None
    next_service_km_interval: int | None = None
    work_order_id: int | None = None
    labor_cost: Decimal | None = Field(default=None, ge=0)
    parts_cost: Decimal | None = Field(default=None, ge=0)
    source: ServiceSource = ServiceSource.manual


class VehicleServiceListOut(BaseModel):
    id: int
    license_plate: str
    vehicle_name: str
    service_type: str
    service_date: str
    odometer_km: int | None = None
    cost: Decimal | None = None
    workshop: str | None = None
    description: str | None = None
    bill_file_path: str | None = None
    next_service_date: str | None = None
    next_service_km_interval: int | None = None
    next_service_odometer_km: int | None = None
    vehicle_id: int
    labor_cost: Decimal | None = None
    parts_cost: Decimal | None = None
    total_cost: Decimal | None = None
    source: ServiceSource = ServiceSource.manual
    status: str = "Completed"
    archived: bool = False
    linked_work_order: "LinkedWorkOrder | None" = None
    reminder_status: ReminderStatus | None = None
    bills: list["ServiceAttachment"] = []


class VehicleServiceOverviewOut(BaseModel):
    id: int
    license_plate: str
    vehicle_name: str
    service_type: str
    service_date: str
    odometer_km: int | None = None
    workshop: str | None = None
    cost: Decimal | None = None
    description: str | None = None
    bill_file_path: str | None = None
    next_service_date: str | None = None
    next_service_km_interval: int | None = None
    next_service_odometer_km: int | None = None
    vehicle_id: int
    labor_cost: Decimal | None = None
    parts_cost: Decimal | None = None
    total_cost: Decimal | None = None
    source: ServiceSource = ServiceSource.manual
    status: str = "Completed"
    archived: bool = False
    linked_work_order: "LinkedWorkOrder | None" = None
    reminder_status: ReminderStatus | None = None


class ServiceReminderOut(BaseModel):
    id: int
    vehicle_id: int
    license_plate: str
    vehicle_name: str
    service_type: str
    service_date: str
    reminder_mode: str
    next_service_date: str | None = None
    days_left: int | None = None
    current_odometer_km: int | None = None
    next_service_odometer_km: int | None = None
    next_service_km_interval: int | None = None
    km_left: int | None = None
    status: ReminderStatus
    priority: WorkOrderPriority
    linked_work_order: "LinkedWorkOrder | None" = None


class LinkedWorkOrder(BaseModel):
    id: int
    title: str
    status: WorkOrderStatus
    priority: WorkOrderPriority


class LinkedService(BaseModel):
    id: int
    service_type: str
    service_date: str
    total_cost: Decimal | None = None


class LinkedInspection(BaseModel):
    id: int
    inspection_type: InspectionType
    inspection_date: str
    overall_status: InspectionOverallStatus


class LinkedServiceReminder(BaseModel):
    id: int
    service_type: str
    due_date: str | None = None
    due_odometer_km: int | None = None
    status: ReminderStatus


class ServiceAttachment(BaseModel):
    id: int
    file_path: str
    uploaded_at: str
    attachment_type: str = "Bill"


class WorkOrderPage(BaseModel):
    items: list[WorkOrderOut]
    page: int
    page_size: int
    total: int
    pages: int


class ServicePage(BaseModel):
    items: list[VehicleServiceOverviewOut]
    page: int
    page_size: int
    total: int
    pages: int


class ReminderPage(BaseModel):
    items: list[ServiceReminderOut]
    page: int
    page_size: int
    total: int
    pages: int


class InspectionPage(BaseModel):
    items: list[InspectionOut]
    page: int
    page_size: int
    total: int
    pages: int


class MaintenanceRecordSummary(BaseModel):
    id: int
    record_type: str
    vehicle_id: int
    vehicle: str
    license_plate: str
    title: str
    status: str
    priority: str | None = None
    date: str | None = None
    due_date: str | None = None
    assigned_to: str | None = None
    cost: Decimal | None = None
    href: str
    description: str | None = None


class MaintenanceSummaryOut(BaseModel):
    work_orders_by_status: dict[str, int]
    work_orders_by_priority: dict[str, int]
    open_work_orders: int
    assigned_work_orders: int
    in_progress_work_orders: int
    waiting_for_parts_work_orders: int
    critical_work_orders_count: int
    overdue_work_orders_count: int
    completed_work_orders_this_month: int
    services_completed_this_month: int
    upcoming_reminders_count: int
    overdue_reminders_count: int
    failed_inspections_count: int
    inspections_needing_review_count: int
    vehicles_in_service_count: int
    monthly_maintenance_cost: Decimal
    critical_work_orders: list[MaintenanceRecordSummary]
    overdue_work_orders: list[MaintenanceRecordSummary]
    overdue_service_reminders: list[MaintenanceRecordSummary]
    failed_inspections: list[MaintenanceRecordSummary]
    vehicles_in_service: list[MaintenanceRecordSummary]
    recently_created_work_orders: list[MaintenanceRecordSummary]
    recently_completed_work_orders: list[MaintenanceRecordSummary]
    recent_services: list[MaintenanceRecordSummary]
    recent_inspections: list[MaintenanceRecordSummary]


class VehicleMaintenanceSummaryOut(BaseModel):
    vehicle_id: int
    license_plate: str
    open_work_orders: int
    critical_work_orders: int
    last_service: LinkedService | None = None
    next_service: LinkedServiceReminder | None = None
    overdue_reminders: int
    failed_inspections: int
    maintenance_cost_this_month: Decimal
    maintenance_cost_this_year: Decimal
    lifetime_maintenance_cost: Decimal


class MaintenanceTimelineEvent(BaseModel):
    id: str
    occurred_at: str
    event_type: str
    title: str
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    actor: str | None = None
    related_record_type: str
    related_record_id: int
    href: str


class MaintenanceTimelinePage(BaseModel):
    items: list[MaintenanceTimelineEvent]
    page: int
    page_size: int
    total: int
    pages: int


class FuelUpdate(BaseModel):
    refuel_date: str
    fuel_type: str
    liters: Decimal
    cost_per_liter: Decimal | None = None
    location: str | None = None
    station_name: str | None = None
    odometer_km: int | None = None


class FuelRecordOut(BaseModel):
    id: int
    license_plate: str
    brand: str
    model: str
    refuel_date: str
    fuel_type: str
    liters: Decimal
    cost_per_liter: Decimal
    total_cost: Decimal
    location: str
    station_name: str
    bill_file_path: str | None = None
    odometer_km: int


class FuelOverviewOut(BaseModel):
    license_plate: str
    brand: str
    model: str
    total_liters: Decimal
    total_cost: Decimal
    refuel_count: int


class VehiclePaperListOut(BaseModel):
    id: int
    license_plate: str
    vehicle_location: str
    brand: str
    model: str
    document_type: str
    issue_date: str
    expiry_date: str
    file_path: str


class AccidentOut(BaseModel):
    id: int
    accident_date: str
    location: str | None = None
    description: str | None = None
    license_plate: str | None = None
    brand: str | None = None
    model: str | None = None
    files: list[str] = []


class AddReservation(BaseModel):
    license_plate: str
    reserved_by: str
    reservation_type: str
    start_date: str
    end_date: str
    notes: str | None = None


class ReservationStatusUpdate(BaseModel):
    status: str


class VehicleReservationListOut(BaseModel):
    id: int
    license_plate: str
    reserved_by: str
    reservation_type: str
    start_date: str
    end_date: str
    notes: str | None = ""
    status: int
    status_name: str


class DashboardStatusItem(BaseModel):
    status: int
    count: int


class DashboardLocationItem(BaseModel):
    location: str
    count: int


class DashboardReservationStatusItem(BaseModel):
    status: str
    count: int


class DashboardSummaryOut(BaseModel):
    total_vehicles: int
    status_summary: list[DashboardStatusItem]
    location_summary: list[DashboardLocationItem]
    reservation_status_summary: list[DashboardReservationStatusItem] = []
