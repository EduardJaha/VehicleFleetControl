from decimal import Decimal
from enum import Enum, IntEnum
from pydantic import BaseModel, Field, ConfigDict, field_validator
import re

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
    items: list[InspectionItemCreate] = Field(default_factory=list)

    @field_validator("license_plate", "notes")
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
    driver_id: int | None = None
    driver_name: str | None = None
    inspection_type: InspectionType
    inspection_date: str
    overall_status: InspectionOverallStatus
    notes: str | None = None
    items: list[InspectionItemOut]
    created_at: str
    updated_at: str
    model_config = ConfigDict(from_attributes=True)


class WorkOrderBase(BaseModel):
    vehicle_id: int | None = None
    license_plate: str | None = None
    driver_id: int | None = None
    inspection_id: int | None = None
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

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Title is required.")
        return text

    @field_validator("license_plate", "description", "reported_issue", "requested_by", "assigned_to", "workshop", "notes")
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
    driver_name: str | None = None
    total_cost: Decimal | None = None
    created_at: str
    updated_at: str
    model_config = ConfigDict(from_attributes=True)


class VehicleBase(BaseModel):
    brand: str
    model: str
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


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(VehicleBase):
    pass


class VehicleOut(VehicleBase):
    id: int
    status_name: str
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


class VehicleServiceListOut(BaseModel):
    id: int
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


class VehicleServiceOverviewOut(BaseModel):
    id: int
    license_plate: str
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


class ServiceReminderOut(BaseModel):
    license_plate: str
    service_type: str
    service_date: str
    reminder_mode: str
    next_service_date: str | None = None
    days_left: int | None = None
    current_odometer_km: int | None = None
    next_service_odometer_km: int | None = None
    next_service_km_interval: int | None = None
    km_left: int | None = None


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
