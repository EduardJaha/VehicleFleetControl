from decimal import Decimal
from enum import Enum, IntEnum
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from app.utils.vehicle_catalog import clean_catalog_name
from app.services.license_plates import (
    RegistrationCountry,
    PlateValidationError,
    validate_license_plate,
)


class VehicleStatus(IntEnum):
    active = 0
    in_service = 1
    sold = 2
    out_of_use = 3
    assigned = 4


class VehicleReservationStatus(IntEnum):
    pending = 0
    approved = 1
    rejected = 2
    cancelled = 3
    completed = 4


class UserRole(str, Enum):
    admin = "admin"
    fleet_manager = "fleet_manager"
    mechanic = "mechanic"
    driver = "driver"
    finance = "finance"
    viewer = "viewer"


class LanguageCode(str, Enum):
    en = "en"
    sq = "sq"


class EnergyUnit(str, Enum):
    liter = "L"
    kilowatt_hour = "KWH"


class DriverStatus(str, Enum):
    active = "Active"
    suspended = "Suspended"
    left_company = "Left Company"


class VehicleAssignmentStatus(str, Enum):
    scheduled = "Scheduled"
    active = "Active"
    completed = "Completed"
    cancelled = "Cancelled"
    overdue = "Overdue"


class VehicleConditionType(str, Enum):
    checkout = "Checkout"
    return_ = "Return"


class InspectionType(str, Enum):
    general = "General"
    daily = "Daily"
    weekly = "Weekly"
    monthly = "Monthly"
    before_trip = "Before Trip"
    after_trip = "After Trip"
    random = "Random"
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
    preferred_language: LanguageCode = LanguageCode.en

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


class LanguagePreferenceUpdate(BaseModel):
    language: LanguageCode


class LanguagePreferenceOut(BaseModel):
    preferred_language: LanguageCode


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
    archived: bool = False
    archived_at: str | None = None
    archived_by: int | None = None
    model_config = ConfigDict(from_attributes=True)


class VehicleAssignmentBase(BaseModel):
    vehicle_id: int = Field(gt=0)
    driver_id: int = Field(gt=0)
    reservation_id: int | None = Field(default=None, gt=0)
    start_datetime: str
    start_odometer_km: int = Field(ge=0)
    start_energy_level: int | None = Field(default=None, ge=0, le=100)
    purpose: str | None = Field(default=None, max_length=255)
    destination: str | None = Field(default=None, max_length=255)
    documents_handed_over: list[str] = []
    notes: str | None = None

    @field_validator("purpose", "destination", "notes")
    @classmethod
    def normalize_assignment_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class VehicleAssignmentCreate(VehicleAssignmentBase):
    pass


class VehicleAssignmentUpdate(VehicleAssignmentBase):
    pass


class VehicleAssignmentStart(BaseModel):
    start_datetime: str | None = None
    start_odometer_km: int | None = Field(default=None, ge=0)
    start_energy_level: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        return VehicleAssignmentBase.normalize_assignment_text(value)


class VehicleAssignmentComplete(BaseModel):
    end_datetime: str
    end_odometer_km: int = Field(ge=0)
    end_energy_level: int | None = Field(default=None, ge=0, le=100)
    return_notes: str | None = None

    @field_validator("return_notes")
    @classmethod
    def normalize_return_notes(cls, value: str | None) -> str | None:
        return VehicleAssignmentBase.normalize_assignment_text(value)


class VehicleCheckoutCreate(BaseModel):
    assignment_id: int | None = Field(default=None, gt=0)
    vehicle_id: int = Field(gt=0)
    driver_id: int = Field(gt=0)
    reservation_id: int | None = Field(default=None, gt=0)
    checkout_datetime: str
    starting_odometer_km: int = Field(ge=0)
    energy_level: int | None = Field(default=None, ge=0, le=100)
    vehicle_condition: str = Field(min_length=1, max_length=50)
    existing_damage: str | None = None
    documents_handed_over: list[str] = []
    purpose: str | None = Field(default=None, max_length=255)
    destination: str | None = Field(default=None, max_length=255)
    notes: str | None = None

    @field_validator("vehicle_condition")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("existing_damage", "purpose", "destination", "notes")
    @classmethod
    def normalize_checkout_text(cls, value: str | None) -> str | None:
        return VehicleAssignmentBase.normalize_assignment_text(value)

    @field_validator("documents_handed_over")
    @classmethod
    def normalize_documents(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class VehicleReturnCreate(BaseModel):
    return_datetime: str
    ending_odometer_km: int = Field(ge=0)
    energy_level: int | None = Field(default=None, ge=0, le=100)
    vehicle_condition: str = Field(min_length=1, max_length=50)
    new_damage: str | None = None
    driver_comments: str | None = None
    return_inspection_required: bool = False
    create_accident: bool = False
    create_work_order: bool = False

    @field_validator("vehicle_condition")
    @classmethod
    def normalize_return_condition(cls, value: str) -> str:
        return value.strip()

    @field_validator("new_damage", "driver_comments")
    @classmethod
    def normalize_return_text(cls, value: str | None) -> str | None:
        return VehicleAssignmentBase.normalize_assignment_text(value)

    @model_validator(mode="after")
    def damage_actions_require_damage(self):
        if (self.create_accident or self.create_work_order) and not self.new_damage:
            raise ValueError("New damage is required when creating an Accident or Work Order.")
        return self


class VehicleConditionRecordOut(BaseModel):
    id: int
    vehicle_assignment_id: int
    vehicle_id: int
    driver_id: int
    record_type: VehicleConditionType
    recorded_at: str
    odometer_km: int
    energy_level: int | None = None
    vehicle_condition: str
    damage_description: str | None = None
    driver_comments: str | None = None
    return_inspection_required: bool
    attachment_count: int = 0


class VehicleAssignmentOut(VehicleAssignmentBase):
    id: int
    vehicle_license_plate: str
    vehicle_name: str
    driver_name: str
    assigned_by_user_id: int | None = None
    assigned_by_name: str | None = None
    ended_by_user_id: int | None = None
    ended_by_name: str | None = None
    end_datetime: str | None = None
    end_odometer_km: int | None = None
    end_energy_level: int | None = None
    return_notes: str | None = None
    status: VehicleAssignmentStatus
    created_at: str
    updated_at: str
    archived: bool = False
    archived_at: str | None = None
    archived_by: int | None = None
    conditions: list[VehicleConditionRecordOut] = []
    model_config = ConfigDict(from_attributes=True)


class VehicleCheckoutResult(BaseModel):
    assignment: VehicleAssignmentOut
    condition_record: VehicleConditionRecordOut


class VehicleReturnResult(BaseModel):
    assignment: VehicleAssignmentOut
    condition_record: VehicleConditionRecordOut
    inspection_id: int | None = None
    accident_id: int | None = None
    work_order_id: int | None = None


class VehicleAssignmentPage(BaseModel):
    items: list[VehicleAssignmentOut]
    page: int
    page_size: int
    total: int
    pages: int


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
    vehicle_assignment_id: int | None = None
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


class WorkOrderCompletionRequest(BaseModel):
    actual_completion_date: str
    completed_odometer_km: int = Field(ge=0)
    workshop: str | None = Field(default=None, max_length=150)
    labor_cost: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    parts_cost: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    completion_notes: str | None = None
    create_service_record: bool = True
    service_type: str | None = Field(default=None, max_length=100)
    service_description: str | None = None
    next_service_km_interval: int | None = Field(default=None, ge=1)
    next_service_date: str | None = None
    resolve_source_reminder: bool = True

    @field_validator("workshop", "completion_notes", "service_type", "service_description")
    @classmethod
    def normalize_completion_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class WorkOrderCompletionOut(BaseModel):
    work_order: "WorkOrderOut"
    service: "LinkedService | None" = None
    reminder_resolved: bool = False
    next_reminder_created: bool = False


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
    registration_country: RegistrationCountry | None = None
    license_plate: str
    year: int | None = Field(default=None, ge=1900, le=2100)
    vin_number: str | None = Field(default=None, max_length=50)
    engine_cc: int | None = Field(default=None, ge=50, le=10000)
    odometer_km: int | None = Field(default=None, ge=0, le=2_000_000)
    status: int = 0

    @field_validator("license_plate")
    @classmethod
    def clean_plate(cls, value: str) -> str:
        return value.strip()


class VehicleWriteBase(VehicleFields):
    registration_country: RegistrationCountry
    brand_id: int = Field(gt=0)
    model_id: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_registration(self):
        try:
            self.license_plate = validate_license_plate(
                self.registration_country,
                self.license_plate,
            )
        except PlateValidationError as exc:
            raise ValueError(str(exc)) from exc
        return self


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
    registration_country_name: str | None = None
    archived: bool = False
    archived_at: str | None = None
    archived_by: int | None = None
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
    event_code: str | None = None
    title_key: str | None = None
    description_key: str | None = None
    params: dict | None = None


class MaintenanceTimelinePage(BaseModel):
    items: list[MaintenanceTimelineEvent]
    page: int
    page_size: int
    total: int
    pages: int


class FuelUpdate(BaseModel):
    refuel_date: str
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)
    location: str | None = None
    station_name: str | None = None
    odometer_km: int | None = None
    # Deprecated compatibility inputs. They are accepted only for stored
    # liter-based records and are never emitted by the API.
    liters: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=3)
    cost_per_liter: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)
    fuel_type: str | None = None
    unit: EnergyUnit | None = None

    @model_validator(mode="after")
    def require_quantity(self):
        if self.quantity is None and self.liters is None:
            raise ValueError("Quantity is required.")
        return self


class FuelRecordOut(BaseModel):
    id: int
    vehicle_id: int
    vehicle_assignment_id: int | None = None
    license_plate: str
    brand: str
    model: str
    refuel_date: str
    fuel_type: str
    quantity: Decimal
    unit: EnergyUnit
    unit_cost: Decimal
    total_cost: Decimal
    location: str
    station_name: str
    bill_file_path: str | None = None
    odometer_km: int
    archived: bool = False
    unit_review_required: bool = False


class FuelOverviewOut(BaseModel):
    vehicle_id: int
    license_plate: str
    brand: str
    model: str
    fuel_type: str
    unit: EnergyUnit
    total_quantity: Decimal
    total_cost: Decimal
    record_count: int


class FuelFleetTotalsOut(BaseModel):
    total_fuel_cost: Decimal
    total_liters: Decimal
    total_kwh: Decimal
    record_count: int


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
    archived: bool = False


class AccidentOut(BaseModel):
    id: int
    vehicle_assignment_id: int | None = None
    accident_date: str
    location: str | None = None
    description: str | None = None
    license_plate: str | None = None
    brand: str | None = None
    model: str | None = None
    files: list[str] = []
    archived: bool = False


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
    vehicle_id: int
    vehicle_assignment_id: int | None = None
    license_plate: str
    reserved_by: str
    reservation_type: str
    start_date: str
    end_date: str
    notes: str | None = ""
    status: int
    status_name: str
    archived: bool = False


class AuditLogOut(BaseModel):
    id: int
    user_id: int | None = None
    username: str | None = None
    action: str
    entity_type: str
    entity_id: int | None = None
    old_values: dict | None = None
    new_values: dict | None = None
    description: str | None = None
    action_code: str | None = None
    description_key: str | None = None
    description_params: dict | None = None
    ip_address: str | None = None
    created_at: str


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    page: int
    page_size: int
    total: int
    pages: int


class NotificationStatus(str, Enum):
    unread = "Unread"
    read = "Read"
    resolved = "Resolved"
    dismissed = "Dismissed"


class NotificationPriority(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"
    critical = "Critical"


class NotificationOut(BaseModel):
    id: int
    notification_type: str
    title: str
    message: str
    title_key: str | None = None
    message_key: str | None = None
    message_params: dict | None = None
    priority: NotificationPriority
    status: NotificationStatus
    entity_type: str | None = None
    entity_id: int | None = None
    created_at: str
    read_at: str | None = None
    resolved_at: str | None = None
    dismissed_at: str | None = None


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    page: int
    page_size: int
    total: int
    pages: int


class NotificationUnreadCount(BaseModel):
    unread_count: int


class AttachmentOut(BaseModel):
    id: int
    original_filename: str
    mime_type: str
    file_size: int
    entity_type: str
    entity_id: int
    uploaded_at: str


class DashboardStatusItem(BaseModel):
    status: int
    count: int


class DashboardLocationItem(BaseModel):
    location: str
    count: int


class DashboardReservationStatusItem(BaseModel):
    status: str
    count: int


class DashboardActiveUsageItem(BaseModel):
    assignment_id: int
    vehicle_id: int
    driver_id: int
    license_plate: str
    vehicle_name: str
    driver_name: str
    checkout_datetime: str
    expected_return_datetime: str | None = None
    destination: str | None = None
    overdue: bool = False


class DashboardSummaryOut(BaseModel):
    total_vehicles: int
    status_summary: list[DashboardStatusItem]
    location_summary: list[DashboardLocationItem]
    reservation_status_summary: list[DashboardReservationStatusItem] = []
    active_usage: list[DashboardActiveUsageItem] = []
    active_usage_count: int = 0
    overdue_return_count: int = 0
