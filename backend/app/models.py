from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.schema import conv
from app.db.session import Base, TenantMixin


class Company(Base):
    __tablename__ = "Companies"
    __table_args__ = (UniqueConstraint("Slug", name="uq_companies_slug"),)

    id = Column("Id", Integer, primary_key=True)
    name = Column("Name", String(255), nullable=False)
    slug = Column("Slug", String(100), nullable=False, index=True)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    settings = relationship("CompanySettings", back_populates="company", uselist=False, cascade="all, delete-orphan")
    memberships = relationship("CompanyUser", back_populates="company", cascade="all, delete-orphan")


class CompanySettings(TenantMixin, Base):
    __tablename__ = "CompanySettings"
    __table_args__ = (UniqueConstraint("CompanyId", name="uq_company_settings_company"),)

    id = Column("Id", Integer, primary_key=True)
    company_id = Column("CompanyId", Integer, ForeignKey("Companies.Id", ondelete="CASCADE"), nullable=False, index=True)
    logo_path = Column("LogoPath", String(500), nullable=True)
    address = Column("Address", Text, nullable=True)
    default_language = Column("DefaultLanguage", String(5), nullable=False, default="en")
    timezone = Column("Timezone", String(100), nullable=False, default="UTC")
    currency = Column("Currency", String(3), nullable=False, default="EUR")
    notification_rules = Column("NotificationRules", JSON, nullable=False, default=dict)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship("Company", back_populates="settings")


class CompanyUser(TenantMixin, Base):
    __tablename__ = "CompanyUsers"
    __table_args__ = (UniqueConstraint("CompanyId", "UserId", name="uq_company_users_company_user"),)

    id = Column("Id", Integer, primary_key=True)
    company_id = Column("CompanyId", Integer, ForeignKey("Companies.Id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column("Role", String(50), nullable=False, default="viewer")
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    is_default = Column("IsDefault", Boolean, nullable=False, default=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    company = relationship("Company", back_populates="memberships")
    user = relationship("User", back_populates="company_memberships", foreign_keys=[user_id])


class User(TenantMixin, Base):
    __tablename__ = "Users"
    __table_args__ = (UniqueConstraint("Email", name="uq_users_email"),)

    id = Column("Id", Integer, primary_key=True, index=True)
    email = Column("Email", String(255), nullable=False, index=True)
    full_name = Column("FullName", String(255), nullable=False)
    hashed_password = Column("HashedPassword", String(255), nullable=False)
    role = Column("Role", String(50), nullable=False, default="viewer")
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    preferred_language = Column("PreferredLanguage", String(5), nullable=False, default="en")
    last_login_at = Column("LastLoginAt", DateTime, nullable=True)
    session_version = Column("SessionVersion", Integer, nullable=False, default=0)
    password_reset_required = Column("PasswordResetRequired", Boolean, nullable=False, default=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    driver_profile = relationship("Driver", back_populates="user", uselist=False, foreign_keys="Driver.user_id")
    role_assignments = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    assignments_created = relationship(
        "VehicleAssignment",
        back_populates="assigned_by_user",
        foreign_keys="VehicleAssignment.assigned_by_user_id",
    )
    assignments_ended = relationship(
        "VehicleAssignment",
        back_populates="ended_by_user",
        foreign_keys="VehicleAssignment.ended_by_user_id",
    )
    default_company = relationship("Company", foreign_keys="User.company_id")
    company_memberships = relationship("CompanyUser", back_populates="user", cascade="all, delete-orphan", foreign_keys="CompanyUser.user_id")


class LoginRateLimit(Base):
    """Privacy-preserving, shared login throttle bucket."""

    __tablename__ = "LoginRateLimits"
    __table_args__ = (
        Index("ix_login_rate_limits_updated_at", "UpdatedAt"),
    )

    key_hash = Column("KeyHash", String(64), primary_key=True)
    attempt_count = Column("AttemptCount", Integer, nullable=False, default=0)
    window_started_at = Column("WindowStartedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Permission(Base):
    __tablename__ = "Permissions"
    __table_args__ = (UniqueConstraint("Code", name="uq_permissions_code"),)

    id = Column("Id", Integer, primary_key=True)
    code = Column("Code", String(100), nullable=False, index=True)
    name = Column("Name", String(150), nullable=False)
    description = Column("Description", Text, nullable=True)
    module = Column("Module", String(50), nullable=False, index=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    role_permissions = relationship("RolePermission", back_populates="permission", cascade="all, delete-orphan")


class Role(Base):
    __tablename__ = "Roles"
    __table_args__ = (UniqueConstraint("Code", name="uq_roles_code"),)

    id = Column("Id", Integer, primary_key=True)
    code = Column("Code", String(50), nullable=False, index=True)
    name = Column("Name", String(100), nullable=False)
    description = Column("Description", Text, nullable=True)
    is_system = Column("IsSystem", Boolean, nullable=False, default=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    role_permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")
    user_assignments = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")


class RolePermission(Base):
    __tablename__ = "RolePermissions"
    __table_args__ = (UniqueConstraint("RoleId", "PermissionId", name="uq_role_permissions_role_permission"),)

    id = Column("Id", Integer, primary_key=True)
    role_id = Column("RoleId", Integer, ForeignKey("Roles.Id", ondelete="CASCADE"), nullable=False, index=True)
    permission_id = Column("PermissionId", Integer, ForeignKey("Permissions.Id", ondelete="CASCADE"), nullable=False, index=True)

    role = relationship("Role", back_populates="role_permissions")
    permission = relationship("Permission", back_populates="role_permissions")


class Location(TenantMixin, Base):
    __tablename__ = "Locations"
    __table_args__ = (UniqueConstraint("CompanyId", "Code", name="uq_locations_company_code"),)

    id = Column("Id", Integer, primary_key=True)
    code = Column("Code", String(50), nullable=False, index=True)
    name = Column("Name", String(150), nullable=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Department(TenantMixin, Base):
    __tablename__ = "Departments"
    __table_args__ = (UniqueConstraint("CompanyId", "Code", name="uq_departments_company_code"),)

    id = Column("Id", Integer, primary_key=True)
    code = Column("Code", String(50), nullable=False, index=True)
    name = Column("Name", String(150), nullable=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CostCenter(TenantMixin, Base):
    __tablename__ = "CostCenters"
    __table_args__ = (UniqueConstraint("CompanyId", "Code", name="uq_cost_centers_company_code"),)

    id = Column("Id", Integer, primary_key=True)
    code = Column("Code", String(50), nullable=False, index=True)
    name = Column("Name", String(150), nullable=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserRole(TenantMixin, Base):
    __tablename__ = "UserRoles"
    __table_args__ = (UniqueConstraint("CompanyId", "UserId", "RoleId", name="uq_user_roles_company_user_role"),)

    id = Column("Id", Integer, primary_key=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column("RoleId", Integer, ForeignKey("Roles.Id", ondelete="CASCADE"), nullable=False, index=True)
    location_id = Column("LocationId", Integer, ForeignKey("Locations.Id", ondelete="SET NULL"), nullable=True)
    department_id = Column("DepartmentId", Integer, ForeignKey("Departments.Id", ondelete="SET NULL"), nullable=True)
    cost_center_id = Column("CostCenterId", Integer, ForeignKey("CostCenters.Id", ondelete="SET NULL"), nullable=True)
    own_records_only = Column("OwnRecordsOnly", Boolean, nullable=False, default=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="role_assignments")
    role = relationship("Role", back_populates="user_assignments")
    location = relationship("Location")
    department = relationship("Department")
    cost_center = relationship("CostCenter")


class VehicleBrand(Base):
    __tablename__ = "VehicleBrands"
    __table_args__ = (UniqueConstraint("NormalizedName", name="uq_vehicle_brands_normalized_name"),)

    id = Column("Id", Integer, primary_key=True, index=True)
    name = Column("Name", String(255), nullable=False)
    normalized_name = Column("NormalizedName", String(255), nullable=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    models = relationship("VehicleModel", back_populates="brand", cascade="all, delete-orphan")
    vehicles = relationship("Vehicle", back_populates="catalog_brand", foreign_keys="Vehicle.brand_id")


class VehicleModel(Base):
    __tablename__ = "VehicleModels"
    __table_args__ = (
        UniqueConstraint("BrandId", "NormalizedName", name="uq_vehicle_models_brand_normalized_name"),
        Index("ix_vehicle_models_brand_id", "BrandId"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    brand_id = Column("BrandId", Integer, ForeignKey("VehicleBrands.Id", ondelete="CASCADE"), nullable=False)
    name = Column("Name", String(255), nullable=False)
    normalized_name = Column("NormalizedName", String(255), nullable=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    brand = relationship("VehicleBrand", back_populates="models")
    vehicles = relationship("Vehicle", back_populates="catalog_model", foreign_keys="Vehicle.model_id")


class Supplier(TenantMixin, Base):
    """Minimal supplier master used by vehicle acquisition records."""

    __tablename__ = "Suppliers"
    __table_args__ = (UniqueConstraint("CompanyId", "Name", name="uq_suppliers_company_name"),)

    id = Column("Id", Integer, primary_key=True, index=True)
    name = Column("Name", String(255), nullable=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicles = relationship("Vehicle", back_populates="supplier")


class Vehicle(TenantMixin, Base):
    __tablename__ = "Vehicles"
    __table_args__ = (
        UniqueConstraint(
            "CompanyId",
            "RegistrationCountry",
            "LicensePlateNormalized",
            name=conv("uq_vehicles_company_registration_country_license_plate_normalized"),
        ),
        Index("ix_vehicles_brand_id", "BrandId"),
        Index("ix_vehicles_model_id", "ModelId"),
        Index("ix_vehicles_registration_country", "RegistrationCountry"),
        Index("ix_vehicles_license_plate_normalized", "LicensePlateNormalized"),
        Index(
            "ix_vehicles_registration_country_license_plate_normalized",
            "RegistrationCountry",
            "LicensePlateNormalized",
        ),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    brand = Column("Brand", String, nullable=False)
    model = Column("Model", String, nullable=False)
    brand_id = Column("BrandId", Integer, ForeignKey("VehicleBrands.Id"), nullable=True)
    model_id = Column("ModelId", Integer, ForeignKey("VehicleModels.Id"), nullable=True)
    fuel_type = Column("FuelType", String, nullable=False)
    vehicle_location = Column("VehicleLocation", String, nullable=False)
    location_id = Column("LocationId", Integer, ForeignKey("Locations.Id", ondelete="SET NULL"), nullable=True, index=True)
    vehicle_category = Column("VehicleCategory", String(100), nullable=True, index=True)
    license_plate = Column("LicensePlate", String, nullable=False, index=True)
    registration_country = Column("RegistrationCountry", String(2), nullable=False)
    license_plate_normalized = Column("LicensePlateNormalized", String(7), nullable=False)
    status = Column("Status", Integer, nullable=False, default=0)
    engine_cc = Column("EngineCc", Integer, nullable=True)
    vin_number = Column("VinNumber", String(50), nullable=True)
    year = Column("Year", Integer, nullable=True)
    odometer_km = Column("OdometerKm", Integer, nullable=True)
    acquisition_date = Column("AcquisitionDate", Date, nullable=True)
    purchase_price = Column("PurchasePrice", Numeric(14, 2), nullable=True)
    supplier_id = Column("SupplierId", Integer, ForeignKey("Suppliers.Id", ondelete="SET NULL"), nullable=True)
    ownership_type = Column("OwnershipType", String(20), nullable=False, default="Owned")
    lease_start = Column("LeaseStart", Date, nullable=True)
    lease_end = Column("LeaseEnd", Date, nullable=True)
    monthly_lease_payment = Column("MonthlyLeasePayment", Numeric(14, 2), nullable=True)
    warranty_expiry = Column("WarrantyExpiry", Date, nullable=True)
    expected_service_years = Column("ExpectedServiceYears", Integer, nullable=True)
    expected_service_km = Column("ExpectedServiceKm", Integer, nullable=True)
    depreciation_method = Column("DepreciationMethod", String(30), nullable=False, default="Straight Line")
    residual_value = Column("ResidualValue", Numeric(14, 2), nullable=True)
    sale_date = Column("SaleDate", Date, nullable=True)
    sale_price = Column("SalePrice", Numeric(14, 2), nullable=True)
    disposal_reason = Column("DisposalReason", Text, nullable=True)
    fuel_tank_capacity_l = Column("FuelTankCapacityL", Numeric(10, 2), nullable=True)
    battery_capacity_kwh = Column("BatteryCapacityKwh", Numeric(10, 2), nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    catalog_brand = relationship("VehicleBrand", back_populates="vehicles", foreign_keys=[brand_id])
    catalog_model = relationship("VehicleModel", back_populates="vehicles", foreign_keys=[model_id])
    supplier = relationship("Supplier", back_populates="vehicles")
    papers = relationship("VehiclePaper", back_populates="vehicle", cascade="all, delete-orphan")
    services = relationship("VehicleService", back_populates="vehicle", cascade="all, delete-orphan")
    fuels = relationship("VehicleFuel", back_populates="vehicle", cascade="all, delete-orphan")
    accidents = relationship("VehicleAccident", back_populates="vehicle", cascade="all, delete-orphan")
    reservations = relationship("VehicleReservation", back_populates="vehicle", cascade="all, delete-orphan")
    assigned_drivers = relationship("Driver", back_populates="assigned_vehicle")
    inspections = relationship("Inspection", back_populates="vehicle", cascade="all, delete-orphan")
    work_orders = relationship("WorkOrder", back_populates="vehicle", cascade="all, delete-orphan")
    assignments = relationship("VehicleAssignment", back_populates="vehicle")
    condition_records = relationship("VehicleConditionRecord", back_populates="vehicle")
    operating_costs = relationship("VehicleOperatingCost", back_populates="vehicle", cascade="all, delete-orphan")


class Driver(TenantMixin, Base):
    __tablename__ = "Drivers"
    __table_args__ = (
        UniqueConstraint("CompanyId", "Email", name="uq_drivers_company_email"),
        UniqueConstraint("CompanyId", "EmployeeNumber", name="uq_drivers_company_employee_number"),
        UniqueConstraint("CompanyId", "LicenseNumber", name="uq_drivers_company_license_number"),
        UniqueConstraint("CompanyId", "UserId", name="uq_drivers_company_user"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    full_name = Column("FullName", String(255), nullable=False)
    phone_number = Column("PhoneNumber", String(50), nullable=True)
    email = Column("Email", String(255), nullable=True, index=True)
    employee_number = Column("EmployeeNumber", String(100), nullable=False, index=True)
    department = Column("Department", String(100), nullable=True)
    department_id = Column("DepartmentId", Integer, ForeignKey("Departments.Id", ondelete="SET NULL"), nullable=True, index=True)
    cost_center_id = Column("CostCenterId", Integer, ForeignKey("CostCenters.Id", ondelete="SET NULL"), nullable=True, index=True)
    license_number = Column("LicenseNumber", String(100), nullable=False, index=True)
    license_category = Column("LicenseCategory", String(50), nullable=False)
    license_expiry_date = Column("LicenseExpiryDate", DateTime, nullable=False)
    assigned_vehicle_id = Column("AssignedVehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="SET NULL"), nullable=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    status = Column("Status", String(50), nullable=False, default="Active")
    notes = Column("Notes", Text, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    assigned_vehicle = relationship("Vehicle", back_populates="assigned_drivers")
    user = relationship("User", back_populates="driver_profile", foreign_keys=[user_id])
    inspections = relationship("Inspection", back_populates="driver")
    work_orders = relationship("WorkOrder", back_populates="driver")
    assignments = relationship("VehicleAssignment", back_populates="driver")
    condition_records = relationship("VehicleConditionRecord", back_populates="driver")
    documents = relationship("VehiclePaper", back_populates="driver")
    accidents = relationship("VehicleAccident", back_populates="driver")


class VehicleAssignment(TenantMixin, Base):
    __tablename__ = "VehicleAssignments"
    __table_args__ = (
        CheckConstraint(
            '"Status" IN (\'Scheduled\', \'Active\', \'Completed\', \'Cancelled\', \'Overdue\')',
            name="ck_vehicle_assignments_status",
        ),
        CheckConstraint('"StartOdometerKm" >= 0', name="ck_vehicle_assignments_start_odometer_nonnegative"),
        CheckConstraint(
            '"EndOdometerKm" IS NULL OR "EndOdometerKm" >= "StartOdometerKm"',
            name="ck_vehicle_assignments_end_odometer",
        ),
        CheckConstraint(
            '"StartEnergyLevel" IS NULL OR ("StartEnergyLevel" >= 0 AND "StartEnergyLevel" <= 100)',
            name="ck_vehicle_assignments_start_energy",
        ),
        CheckConstraint(
            '"EndEnergyLevel" IS NULL OR ("EndEnergyLevel" >= 0 AND "EndEnergyLevel" <= 100)',
            name="ck_vehicle_assignments_end_energy",
        ),
        CheckConstraint(
            '"EndDatetime" IS NULL OR "EndDatetime" >= "StartDatetime"',
            name="ck_vehicle_assignments_end_datetime",
        ),
        Index("ix_vehicle_assignments_vehicle_id", "VehicleId"),
        Index("ix_vehicle_assignments_driver_id", "DriverId"),
        Index("ix_vehicle_assignments_reservation_id", "ReservationId"),
        Index("ix_vehicle_assignments_start_datetime", "StartDatetime"),
        Index("ix_vehicle_assignments_status", "Status"),
        Index("ix_vehicle_assignments_archived", "Archived"),
        Index(
            "uq_vehicle_assignments_active_vehicle",
            "CompanyId",
            "VehicleId",
            unique=True,
            sqlite_where=text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = 0'),
            postgresql_where=text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = false'),
        ),
        Index(
            "uq_vehicle_assignments_active_driver",
            "CompanyId",
            "DriverId",
            unique=True,
            sqlite_where=text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = 0'),
            postgresql_where=text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = false'),
        ),
    )

    id = Column("Id", Integer, primary_key=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="RESTRICT"), nullable=False)
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="RESTRICT"), nullable=False)
    reservation_id = Column(
        "ReservationId",
        Integer,
        ForeignKey("VehicleReservations.Id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_by_user_id = Column(
        "AssignedByUserId",
        Integer,
        ForeignKey("Users.Id", ondelete="SET NULL"),
        nullable=True,
    )
    ended_by_user_id = Column(
        "EndedByUserId",
        Integer,
        ForeignKey("Users.Id", ondelete="SET NULL"),
        nullable=True,
    )
    start_datetime = Column("StartDatetime", DateTime, nullable=False)
    end_datetime = Column("EndDatetime", DateTime, nullable=True)
    start_odometer_km = Column("StartOdometerKm", Integer, nullable=False)
    end_odometer_km = Column("EndOdometerKm", Integer, nullable=True)
    start_energy_level = Column("StartEnergyLevel", Integer, nullable=True)
    end_energy_level = Column("EndEnergyLevel", Integer, nullable=True)
    purpose = Column("Purpose", String(255), nullable=True)
    destination = Column("Destination", String(255), nullable=True)
    documents_handed_over = Column("DocumentsHandedOver", JSON, nullable=True)
    vehicle_status_before_checkout = Column("VehicleStatusBeforeCheckout", Integer, nullable=True)
    notes = Column("Notes", Text, nullable=True)
    return_notes = Column("ReturnNotes", Text, nullable=True)
    status = Column("Status", String(50), nullable=False, default="Scheduled")
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived = Column("Archived", Boolean, nullable=False, default=False)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    vehicle = relationship("Vehicle", back_populates="assignments")
    driver = relationship("Driver", back_populates="assignments")
    reservation = relationship("VehicleReservation", back_populates="assignments")
    assigned_by_user = relationship("User", back_populates="assignments_created", foreign_keys=[assigned_by_user_id])
    ended_by_user = relationship("User", back_populates="assignments_ended", foreign_keys=[ended_by_user_id])
    accidents = relationship("VehicleAccident", back_populates="vehicle_assignment")
    fuel_records = relationship("VehicleFuel", back_populates="vehicle_assignment")
    inspections = relationship("Inspection", back_populates="vehicle_assignment")
    condition_records = relationship(
        "VehicleConditionRecord",
        back_populates="vehicle_assignment",
        cascade="all, delete-orphan",
        order_by="VehicleConditionRecord.recorded_at",
    )


class VehicleConditionRecord(TenantMixin, Base):
    __tablename__ = "VehicleConditionRecords"
    __table_args__ = (
        CheckConstraint(
            '"RecordType" IN (\'Checkout\', \'Return\')',
            name="ck_vehicle_condition_records_type",
        ),
        CheckConstraint('"OdometerKm" >= 0', name="ck_vehicle_condition_records_odometer"),
        CheckConstraint(
            '"EnergyLevel" IS NULL OR ("EnergyLevel" >= 0 AND "EnergyLevel" <= 100)',
            name="ck_vehicle_condition_records_energy",
        ),
        UniqueConstraint("VehicleAssignmentId", "RecordType", name="uq_vehicle_condition_assignment_type"),
        Index("ix_vehicle_condition_records_assignment_id", "VehicleAssignmentId"),
        Index("ix_vehicle_condition_records_vehicle_id", "VehicleId"),
    )

    id = Column("Id", Integer, primary_key=True)
    vehicle_assignment_id = Column(
        "VehicleAssignmentId",
        Integer,
        ForeignKey("VehicleAssignments.Id", ondelete="CASCADE"),
        nullable=False,
    )
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="RESTRICT"), nullable=False)
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="RESTRICT"), nullable=False)
    record_type = Column("RecordType", String(20), nullable=False)
    recorded_at = Column("RecordedAt", DateTime, nullable=False)
    odometer_km = Column("OdometerKm", Integer, nullable=False)
    energy_level = Column("EnergyLevel", Integer, nullable=True)
    vehicle_condition = Column("VehicleCondition", String(50), nullable=False)
    damage_description = Column("DamageDescription", Text, nullable=True)
    driver_comments = Column("DriverComments", Text, nullable=True)
    return_inspection_required = Column("ReturnInspectionRequired", Boolean, nullable=False, default=False)
    recorded_by_user_id = Column("RecordedByUserId", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    vehicle_assignment = relationship("VehicleAssignment", back_populates="condition_records")
    vehicle = relationship("Vehicle", back_populates="condition_records")
    driver = relationship("Driver", back_populates="condition_records")
    recorded_by_user = relationship("User", foreign_keys=[recorded_by_user_id])


class InspectionTemplate(TenantMixin, Base):
    __tablename__ = "InspectionTemplates"
    __table_args__ = (UniqueConstraint("CompanyId", "Code", name="uq_inspection_template_code"),)
    id = Column("Id", Integer, primary_key=True)
    code = Column("Code", String(80), nullable=False)
    name = Column("Name", String(150), nullable=False)
    description = Column("Description", Text)
    inspection_type = Column("InspectionType", String(50), nullable=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    archived = Column("Archived", Boolean, nullable=False, default=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    items = relationship("InspectionTemplateItem", order_by="(InspectionTemplateItem.display_order, InspectionTemplateItem.id)", back_populates="template", cascade="all, delete-orphan")


class InspectionTemplateItem(TenantMixin, Base):
    __tablename__ = "InspectionTemplateItems"
    __table_args__ = (UniqueConstraint("CompanyId", "TemplateId", "Code", name="uq_inspection_template_item_code"),)
    id = Column("Id", Integer, primary_key=True)
    template_id = Column("TemplateId", Integer, ForeignKey("InspectionTemplates.Id"), nullable=False, index=True)
    code = Column("Code", String(80), nullable=False)
    name = Column("Name", String(150), nullable=False)
    description = Column("Description", Text)
    category = Column("Category", String(50), nullable=False, default="Other")
    display_order = Column("DisplayOrder", Integer, nullable=False, default=0)
    required = Column("Required", Boolean, nullable=False, default=True)
    critical = Column("Critical", Boolean, nullable=False, default=False)
    photo_required_on_failure = Column("PhotoRequiredOnFailure", Boolean, nullable=False, default=False)
    comment_required_on_failure = Column("CommentRequiredOnFailure", Boolean, nullable=False, default=False)
    create_work_order_on_failure = Column("CreateWorkOrderOnFailure", Boolean, nullable=False, default=False)
    mark_vehicle_unavailable_on_failure = Column("MarkVehicleUnavailableOnFailure", Boolean, nullable=False, default=False)
    generate_notification_on_failure = Column("GenerateNotificationOnFailure", Boolean, nullable=False, default=True)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    template = relationship("InspectionTemplate", back_populates="items")


class InspectionTemplateAssignment(TenantMixin, Base):
    __tablename__ = "InspectionTemplateAssignments"
    id = Column("Id", Integer, primary_key=True)
    template_id = Column("TemplateId", Integer, ForeignKey("InspectionTemplates.Id"), nullable=False, index=True)
    target_type = Column("TargetType", String(30), nullable=False)
    target_value = Column("TargetValue", String(255), nullable=False)
    model = Column("Model", String(150))
    priority = Column("Priority", Integer, nullable=False, default=0)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    template = relationship("InspectionTemplate")


class InspectionSchedule(TenantMixin, Base):
    __tablename__ = "InspectionSchedules"
    id = Column("Id", Integer, primary_key=True)
    template_id = Column("TemplateId", Integer, ForeignKey("InspectionTemplates.Id"), nullable=False, index=True)
    frequency = Column("Frequency", String(30), nullable=False)
    start_date = Column("StartDate", Date, nullable=False)
    interval_days = Column("IntervalDays", Integer)
    interval_km = Column("IntervalKm", Integer)
    baseline_odometer_km = Column("BaselineOdometerKm", Integer)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    template = relationship("InspectionTemplate")
    __table_args__ = (
        CheckConstraint('"IntervalDays" IS NULL OR "IntervalDays" > 0', name="ck_inspection_schedule_days"),
        CheckConstraint('"IntervalKm" IS NULL OR "IntervalKm" > 0', name="ck_inspection_schedule_km"),
    )


class Inspection(TenantMixin, Base):
    __tablename__ = "Inspections"
    __table_args__ = (
        Index("ix_inspections_vehicle_assignment_id", "VehicleAssignmentId"),
        UniqueConstraint("CompanyId", "OccurrenceKey", name="uq_inspection_occurrence"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="SET NULL"), nullable=True)
    vehicle_assignment_id = Column(
        "VehicleAssignmentId",
        Integer,
        ForeignKey("VehicleAssignments.Id", ondelete="SET NULL"),
        nullable=True,
    )
    template_id = Column("TemplateId", Integer, ForeignKey("InspectionTemplates.Id", name="fk_inspections_templateid"), nullable=True)
    template_snapshot = Column("TemplateSnapshot", JSON, nullable=True)
    created_by_user_id = Column("CreatedByUserId", Integer, ForeignKey("Users.Id", ondelete="SET NULL", name="fk_inspections_createdbyuserid"), nullable=True)
    schedule_id = Column("ScheduleId", Integer, ForeignKey("InspectionSchedules.Id", name="fk_inspections_scheduleid"), nullable=True)
    occurrence_key = Column("OccurrenceKey", String(200), nullable=True)
    completed_at = Column("CompletedAt", DateTime, nullable=True)
    odometer_km = Column("OdometerKm", Integer, nullable=True)
    inspection_type = Column("InspectionType", String(50), nullable=False)
    inspection_date = Column("InspectionDate", DateTime, nullable=False)
    overall_status = Column("OverallStatus", String(50), nullable=False, default="Needs Review")
    notes = Column("Notes", Text, nullable=True)
    inspector = Column("Inspector", String(150), nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="inspections")
    driver = relationship("Driver", back_populates="inspections")
    vehicle_assignment = relationship("VehicleAssignment", back_populates="inspections")
    items = relationship("InspectionItem", back_populates="inspection", cascade="all, delete-orphan")
    work_orders = relationship("WorkOrder", back_populates="inspection")


class InspectionItem(TenantMixin, Base):
    __tablename__ = "InspectionItems"

    id = Column("Id", Integer, primary_key=True, index=True)
    inspection_id = Column("InspectionId", Integer, ForeignKey("Inspections.Id", ondelete="CASCADE"), nullable=False)
    item_name = Column("ItemName", String(150), nullable=False)
    status = Column("Status", String(50), nullable=False, default="Not Checked")
    comment = Column("Comment", Text, nullable=True)

    template_item_id = Column("TemplateItemId", Integer, nullable=True)
    item_snapshot = Column("ItemSnapshot", JSON, nullable=True)
    photo_attachment_ids = Column("PhotoAttachmentIds", JSON, nullable=True)

    inspection = relationship("Inspection", back_populates="items")


class WorkOrder(TenantMixin, Base):
    __tablename__ = "WorkOrders"
    __table_args__ = (
        Index("ix_work_orders_reminder_service", "ReminderServiceId"),
        Index("ix_work_orders_accident_id", "AccidentId"),
        UniqueConstraint("InspectionItemId", name="uq_work_order_inspection_item"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="SET NULL"), nullable=True)
    inspection_id = Column("InspectionId", Integer, ForeignKey("Inspections.Id", ondelete="SET NULL"), nullable=True)
    inspection_item_id = Column("InspectionItemId", Integer, ForeignKey("InspectionItems.Id", ondelete="RESTRICT", name="fk_workorders_inspectionitemid"), nullable=True)
    reminder_service_id = Column("ReminderServiceId", Integer, ForeignKey("VehicleServices.Id"), nullable=True)
    accident_id = Column("AccidentId", Integer, ForeignKey("VehicleAccidents.Id", ondelete="SET NULL"), nullable=True)
    source = Column("Source", String(50), nullable=False, default="Manual")
    title = Column("Title", String(150), nullable=False)
    description = Column("Description", Text, nullable=True)
    reported_issue = Column("ReportedIssue", Text, nullable=True)
    priority = Column("Priority", String(50), nullable=False, default="Medium")
    status = Column("Status", String(50), nullable=False, default="Open")
    requested_by = Column("RequestedBy", String(150), nullable=True)
    assigned_to = Column("AssignedTo", String(150), nullable=True)
    workshop = Column("Workshop", String(150), nullable=True)
    expected_completion_date = Column("ExpectedCompletionDate", DateTime, nullable=True)
    actual_completion_date = Column("ActualCompletionDate", DateTime, nullable=True)
    vendor_id = Column("VendorId", Integer, ForeignKey("Vendors.Id", ondelete="SET NULL"), nullable=True)
    external_vendor_cost = Column("ExternalVendorCost", Numeric(12, 2), nullable=False, default=0)
    tax_amount = Column("TaxAmount", Numeric(12, 2), nullable=False, default=0)
    discount_amount = Column("DiscountAmount", Numeric(12, 2), nullable=False, default=0)
    other_cost = Column("OtherCost", Numeric(12, 2), nullable=False, default=0)
    labor_cost = Column("LaborCost", Numeric(12, 2), nullable=True)
    parts_cost = Column("PartsCost", Numeric(12, 2), nullable=True)
    total_cost = Column("TotalCost", Numeric(12, 2), nullable=True)
    notes = Column("Notes", Text, nullable=True)
    completed_odometer_km = Column("CompletedOdometerKm", Integer, nullable=True)
    completion_notes = Column("CompletionNotes", Text, nullable=True)
    completed_by = Column("CompletedBy", String(150), nullable=True)
    created_by = Column("CreatedBy", String(150), nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="work_orders")
    driver = relationship("Driver", back_populates="work_orders")
    inspection = relationship("Inspection", back_populates="work_orders")
    reminder_service = relationship("VehicleService", foreign_keys=[reminder_service_id], back_populates="reminder_work_orders")
    linked_service = relationship("VehicleService", foreign_keys="VehicleService.work_order_id", back_populates="work_order", uselist=False)
    accident = relationship("VehicleAccident", back_populates="work_orders")
    vendor = relationship("Vendor", foreign_keys=[vendor_id], back_populates="work_orders")
    part_lines = relationship("WorkOrderPart", back_populates="work_order")
    technician_assignments = relationship("WorkOrderTechnician", back_populates="work_order")
    labor_entries = relationship("LaborEntry", back_populates="work_order")
    vendor_charges = relationship("WorkOrderVendorCharge", back_populates="work_order")
    program_reminder = relationship("ServiceProgramReminder", back_populates="work_order", uselist=False)


class Vendor(TenantMixin, Base):
    __tablename__ = "Vendors"
    __table_args__ = (
        UniqueConstraint("CompanyId", "Name", name="uq_vendors_company_name"),
        CheckConstraint('"Rating" IS NULL OR ("Rating" >= 0 AND "Rating" <= 5)', name="ck_vendors_rating"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    name = Column("Name", String(200), nullable=False, index=True)
    vendor_type = Column("VendorType", String(50), nullable=False, index=True)
    city = Column("City", String(150))
    country = Column("Country", String(100))
    notes = Column("Notes", Text)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    contact_name = Column("ContactName", String(150), nullable=True)
    email = Column("Email", String(255), nullable=True)
    phone = Column("Phone", String(50), nullable=True)
    address = Column("Address", Text, nullable=True)
    payment_terms = Column("PaymentTerms", String(150), nullable=True)
    tax_number = Column("TaxNumber", String(100), nullable=True, index=True)
    supported_services = Column("SupportedServices", JSON, nullable=False, default=list)
    status = Column("Status", String(30), nullable=False, default="Active", index=True)
    rating = Column("Rating", Numeric(3, 2), nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplied_parts = relationship("Part", back_populates="supplier")
    purchase_orders = relationship("PurchaseOrder", back_populates="vendor")
    work_orders = relationship("WorkOrder", foreign_keys="WorkOrder.vendor_id", back_populates="vendor")
    service_records = relationship("VehicleService", foreign_keys="VehicleService.vendor_id", back_populates="vendor")
    charges = relationship("WorkOrderVendorCharge", back_populates="vendor")


class PartCategory(TenantMixin, Base):
    __tablename__ = "PartCategories"
    __table_args__ = (UniqueConstraint("CompanyId", "Name", name="uq_part_categories_company_name"),)

    id = Column("Id", Integer, primary_key=True, index=True)
    name = Column("Name", String(150), nullable=False)
    description = Column("Description", Text, nullable=True)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    parts = relationship("Part", back_populates="category")


class Part(TenantMixin, Base):
    __tablename__ = "Parts"
    __table_args__ = (
        UniqueConstraint("CompanyId", "PartNumber", name="uq_parts_company_number"),
        UniqueConstraint("CompanyId", "Barcode", name="uq_parts_company_barcode"),
        CheckConstraint('"UnitCost" >= 0', name="ck_parts_unit_cost"),
        CheckConstraint('"MinimumStock" >= 0', name="ck_parts_minimum_stock"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    part_number = Column("PartNumber", String(100), nullable=False, index=True)
    name = Column("Name", String(200), nullable=False, index=True)
    manufacturer = Column("Manufacturer", String(200))
    description = Column("Description", Text, nullable=True)
    category_id = Column("CategoryId", Integer, ForeignKey("PartCategories.Id", ondelete="RESTRICT"), nullable=False, index=True)
    unit = Column("Unit", String(30), nullable=False)
    unit_cost = Column("UnitCost", Numeric(14, 4), nullable=False, default=0)
    supplier_id = Column("SupplierId", Integer, ForeignKey("Vendors.Id", ondelete="SET NULL"), nullable=True, index=True)
    barcode = Column("Barcode", String(100), nullable=True)
    minimum_stock = Column("MinimumStock", Numeric(14, 3), nullable=False, default=0)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("PartCategory", back_populates="parts")
    supplier = relationship("Vendor", back_populates="supplied_parts")
    inventories = relationship("PartInventory", back_populates="part")
    transactions = relationship("InventoryTransaction", back_populates="part")
    work_order_lines = relationship("WorkOrderPart", back_populates="part")
    purchase_order_items = relationship("PurchaseOrderItem", back_populates="part")


class PartInventory(TenantMixin, Base):
    __tablename__ = "PartInventories"
    __table_args__ = (
        UniqueConstraint("PartId", "LocationId", name="uq_part_inventory_part_location"),
        CheckConstraint('"QuantityOnHand" >= 0', name="ck_part_inventory_nonnegative"),
        CheckConstraint('"ReservedQuantity" >= 0 AND "ReservedQuantity" <= "QuantityOnHand"', name="ck_inventory_reserved"),
        CheckConstraint('"MinimumStock" IS NULL OR "MinimumStock" >= 0', name="ck_inventory_minimum"),
    )

    id = Column("Id", Integer, primary_key=True)
    part_id = Column("PartId", Integer, ForeignKey("Parts.Id", ondelete="RESTRICT"), nullable=False, index=True)
    location_id = Column("LocationId", Integer, ForeignKey("Locations.Id", ondelete="RESTRICT"), nullable=False, index=True)
    reserved_quantity = Column("ReservedQuantity", Numeric(14, 3), nullable=False, default=0)
    minimum_stock = Column("MinimumStock", Numeric(14, 3), nullable=True)
    quantity_on_hand = Column("QuantityOnHand", Numeric(14, 3), nullable=False, default=0)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    part = relationship("Part", back_populates="inventories")
    location = relationship("Location")


class PurchaseOrder(TenantMixin, Base):
    __tablename__ = "PurchaseOrders"
    __table_args__ = (UniqueConstraint("CompanyId", "OrderNumber", name="uq_purchase_orders_company_number"),)

    id = Column("Id", Integer, primary_key=True, index=True)
    order_number = Column("OrderNumber", String(100), nullable=False, index=True)
    vendor_id = Column("VendorId", Integer, ForeignKey("Vendors.Id", ondelete="RESTRICT"), nullable=False, index=True)
    storage_location_id = Column("StorageLocationId", Integer, ForeignKey("Locations.Id", ondelete="RESTRICT"), nullable=False)
    status = Column("Status", String(40), nullable=False, default="Draft", index=True)
    order_date = Column("OrderDate", DateTime, nullable=True)
    expected_date = Column("ExpectedDate", DateTime, nullable=True)
    notes = Column("Notes", Text, nullable=True)
    subtotal = Column("Subtotal", Numeric(14, 2), nullable=False, default=0)
    tax_amount = Column("TaxAmount", Numeric(14, 2), nullable=False, default=0)
    discount_amount = Column("DiscountAmount", Numeric(14, 2), nullable=False, default=0)
    total_amount = Column("TotalAmount", Numeric(14, 2), nullable=False, default=0)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_by = Column("CreatedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    approved_by = Column("ApprovedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    approved_at = Column("ApprovedAt", DateTime, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor = relationship("Vendor", back_populates="purchase_orders")
    storage_location = relationship("Location")
    items = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderItem(TenantMixin, Base):
    __tablename__ = "PurchaseOrderItems"
    __table_args__ = (
        UniqueConstraint("PurchaseOrderId", "PartId", name="uq_purchase_order_items_part"),
        CheckConstraint('"QuantityOrdered" > 0', name="ck_purchase_order_items_ordered_positive"),
        CheckConstraint('"QuantityReceived" >= 0 AND "QuantityReceived" <= "QuantityOrdered"', name="ck_purchase_order_items_received"),
        CheckConstraint('"UnitCost" >= 0', name="ck_purchase_order_items_unit_cost"),
    )

    id = Column("Id", Integer, primary_key=True)
    purchase_order_id = Column("PurchaseOrderId", Integer, ForeignKey("PurchaseOrders.Id", ondelete="CASCADE"), nullable=False, index=True)
    part_id = Column("PartId", Integer, ForeignKey("Parts.Id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity_ordered = Column("QuantityOrdered", Numeric(14, 3), nullable=False)
    quantity_received = Column("QuantityReceived", Numeric(14, 3), nullable=False, default=0)
    unit_cost = Column("UnitCost", Numeric(14, 4), nullable=False)
    line_total = Column("LineTotal", Numeric(14, 2), nullable=False)

    purchase_order = relationship("PurchaseOrder", back_populates="items")
    part = relationship("Part", back_populates="purchase_order_items")
    inventory_transactions = relationship("InventoryTransaction", back_populates="purchase_order_item")


class InventoryTransaction(TenantMixin, Base):
    __tablename__ = "InventoryTransactions"
    __table_args__ = (
        CheckConstraint('"Quantity" <> 0', name="ck_inventory_transactions_quantity_nonzero"),
        Index("ix_inventory_transactions_part_created", "PartId", "CreatedAt"),
    )

    id = Column("Id", Integer, primary_key=True)
    part_id = Column("PartId", Integer, ForeignKey("Parts.Id", ondelete="RESTRICT"), nullable=False, index=True)
    transaction_type = Column("TransactionType", String(40), nullable=False, index=True)
    quantity = Column("Quantity", Numeric(14, 3), nullable=False)
    unit_cost = Column("UnitCost", Numeric(14, 4), nullable=True)
    from_location_id = Column("FromLocationId", Integer, ForeignKey("Locations.Id", ondelete="RESTRICT"), nullable=True)
    to_location_id = Column("ToLocationId", Integer, ForeignKey("Locations.Id", ondelete="RESTRICT"), nullable=True)
    work_order_id = Column("WorkOrderId", Integer, ForeignKey("WorkOrders.Id", ondelete="RESTRICT"), nullable=True, index=True)
    purchase_order_item_id = Column("PurchaseOrderItemId", Integer, ForeignKey("PurchaseOrderItems.Id", ondelete="RESTRICT"), nullable=True, index=True)
    notes = Column("Notes", Text, nullable=True)
    performed_by = Column("PerformedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    part = relationship("Part", back_populates="transactions")
    from_location = relationship("Location", foreign_keys=[from_location_id])
    to_location = relationship("Location", foreign_keys=[to_location_id])
    work_order = relationship("WorkOrder")
    purchase_order_item = relationship("PurchaseOrderItem", back_populates="inventory_transactions")


class WorkOrderPart(TenantMixin, Base):
    __tablename__ = "WorkOrderParts"
    __table_args__ = (
        CheckConstraint('"QuantityReturned" >= 0 AND "QuantityReturned" <= "Quantity"', name="ck_work_order_parts_returned"),
        CheckConstraint('"Quantity" > 0', name="ck_work_order_parts_quantity_positive"),
        CheckConstraint('"UnitCost" >= 0', name="ck_work_order_parts_unit_cost"),
    )

    id = Column("Id", Integer, primary_key=True)
    work_order_id = Column("WorkOrderId", Integer, ForeignKey("WorkOrders.Id", ondelete="RESTRICT"), nullable=False, index=True)
    part_id = Column("PartId", Integer, ForeignKey("Parts.Id", ondelete="RESTRICT"), nullable=False, index=True)
    location_id = Column("LocationId", Integer, ForeignKey("Locations.Id", ondelete="RESTRICT"), nullable=False)
    inventory_transaction_id = Column("InventoryTransactionId", Integer, ForeignKey("InventoryTransactions.Id", ondelete="RESTRICT"), nullable=False, unique=True)
    quantity_returned = Column("QuantityReturned", Numeric(14, 3), nullable=False, default=0)
    quantity = Column("Quantity", Numeric(14, 3), nullable=False)
    unit_cost = Column("UnitCost", Numeric(14, 4), nullable=False)
    total_cost = Column("TotalCost", Numeric(14, 2), nullable=False)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="part_lines")
    part = relationship("Part", back_populates="work_order_lines")
    location = relationship("Location")
    inventory_transaction = relationship("InventoryTransaction", foreign_keys=[inventory_transaction_id])


class Technician(TenantMixin, Base):
    __tablename__ = "Technicians"
    __table_args__ = (UniqueConstraint("CompanyId", "EmployeeNumber", name="uq_technicians_company_number"),)

    id = Column("Id", Integer, primary_key=True, index=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id", ondelete="SET NULL"))
    specialization = Column("Specialization", String(200))
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    employee_number = Column("EmployeeNumber", String(100), nullable=False, index=True)
    full_name = Column("FullName", String(200), nullable=False, index=True)
    email = Column("Email", String(255), nullable=True)
    phone = Column("Phone", String(50), nullable=True)
    hourly_rate = Column("HourlyRate", Numeric(12, 2), nullable=False, default=0)
    status = Column("Status", String(30), nullable=False, default="Active", index=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_orders = relationship("WorkOrderTechnician", back_populates="technician")
    labor_entries = relationship("LaborEntry", back_populates="technician")


class WorkOrderTechnician(TenantMixin, Base):
    __tablename__ = "WorkOrderTechnicians"
    __table_args__ = (
        UniqueConstraint("WorkOrderId", "TechnicianId", name="uq_work_order_technicians_assignment"),
        CheckConstraint('"EstimatedHours" >= 0', name="ck_work_order_technicians_estimated_hours"),
    )

    id = Column("Id", Integer, primary_key=True)
    work_order_id = Column("WorkOrderId", Integer, ForeignKey("WorkOrders.Id", ondelete="CASCADE"), nullable=False, index=True)
    technician_id = Column("TechnicianId", Integer, ForeignKey("Technicians.Id", ondelete="RESTRICT"), nullable=False, index=True)
    estimated_hours = Column("EstimatedHours", Numeric(10, 2), nullable=False, default=0)
    task_description = Column("TaskDescription", Text, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="technician_assignments")
    technician = relationship("Technician", back_populates="work_orders")


class LaborEntry(TenantMixin, Base):
    __tablename__ = "LaborEntries"
    __table_args__ = (
        CheckConstraint('"ActualHours" >= 0', name="ck_labor_entries_actual_hours"),
        CheckConstraint('"HourlyRate" >= 0', name="ck_labor_entries_hourly_rate"),
        CheckConstraint('"LaborCost" >= 0', name="ck_labor_entries_labor_cost"),
        Index("uq_labor_active_clock", "CompanyId", "TechnicianId", unique=True, sqlite_where=text('"ClockIn" IS NOT NULL AND "ClockOut" IS NULL AND "Archived" = false'), postgresql_where=text('"ClockIn" IS NOT NULL AND "ClockOut" IS NULL AND "Archived" = false')),
    )

    id = Column("Id", Integer, primary_key=True)
    work_order_id = Column("WorkOrderId", Integer, ForeignKey("WorkOrders.Id", ondelete="RESTRICT"), nullable=False, index=True)
    technician_id = Column("TechnicianId", Integer, ForeignKey("Technicians.Id", ondelete="RESTRICT"), nullable=False, index=True)
    notes = Column("Notes", Text)
    actual_hours = Column("ActualHours", Numeric(10, 2), nullable=False)
    clock_in = Column("ClockIn", DateTime, nullable=True)
    clock_out = Column("ClockOut", DateTime, nullable=True)
    hourly_rate = Column("HourlyRate", Numeric(12, 2), nullable=False)
    labor_cost = Column("LaborCost", Numeric(14, 2), nullable=False)
    task_description = Column("TaskDescription", Text, nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="labor_entries")
    technician = relationship("Technician", back_populates="labor_entries")


class WorkOrderVendorCharge(TenantMixin, Base):
    __tablename__ = "WorkOrderVendorCharges"
    __table_args__ = (CheckConstraint('"Amount" >= 0', name="ck_work_order_vendor_charges_amount"),)

    id = Column("Id", Integer, primary_key=True)
    work_order_id = Column("WorkOrderId", Integer, ForeignKey("WorkOrders.Id", ondelete="RESTRICT"), nullable=False, index=True)
    vendor_id = Column("VendorId", Integer, ForeignKey("Vendors.Id", ondelete="RESTRICT"), nullable=False, index=True)
    description = Column("Description", String(255), nullable=False)
    invoice_number = Column("InvoiceNumber", String(150))
    attachment_id = Column("AttachmentId", Integer, ForeignKey("Attachments.Id", ondelete="SET NULL"))
    amount = Column("Amount", Numeric(14, 2), nullable=False)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    work_order = relationship("WorkOrder", back_populates="vendor_charges")
    vendor = relationship("Vendor", back_populates="charges")


class DocumentRequirement(TenantMixin, Base):
    __tablename__ = "DocumentRequirements"
    __table_args__ = (
        CheckConstraint('"WarningDays" >= 0', name="ck_document_requirements_warning_days"),
        CheckConstraint(
            '"ValidityMonths" IS NULL OR "ValidityMonths" > 0',
            name="ck_document_requirements_validity_months",
        ),
        Index("ix_document_requirements_scope", "AppliesToDriver", "AppliesToCountry", "AppliesToVehicleCategory"),
        Index("ix_document_requirements_active", "IsActive"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    document_type = Column("DocumentType", String(150), nullable=False)
    applies_to_vehicle_category = Column("AppliesToVehicleCategory", String(100), nullable=True)
    applies_to_country = Column("AppliesToCountry", String(2), nullable=True)
    applies_to_driver = Column("AppliesToDriver", Boolean, nullable=False, default=False)
    required = Column("Required", Boolean, nullable=False, default=True)
    validity_months = Column("ValidityMonths", Integer, nullable=True)
    warning_days = Column("WarningDays", Integer, nullable=False, default=30)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    documents = relationship("VehiclePaper", back_populates="requirement")


class VehiclePaper(TenantMixin, Base):
    __tablename__ = "VehiclePapers"
    __table_args__ = (
        CheckConstraint(
            '("VehicleId" IS NOT NULL AND "DriverId" IS NULL) OR '
            '("VehicleId" IS NULL AND "DriverId" IS NOT NULL)',
            name="ck_vehicle_papers_exactly_one_owner",
        ),
        Index("ix_vehicle_papers_driver_id", "DriverId"),
        Index("ix_vehicle_papers_requirement_id", "RequirementId"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    document_type = Column("DocumentType", String, nullable=False)
    file_path = Column("FilePath", String, nullable=False)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="RESTRICT"), nullable=True)
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="RESTRICT"), nullable=True)
    requirement_id = Column(
        "RequirementId",
        Integer,
        ForeignKey("DocumentRequirements.Id", ondelete="SET NULL"),
        nullable=True,
    )
    document_number = Column("DocumentNumber", String(150), nullable=True)
    issuing_authority = Column("IssuingAuthority", String(255), nullable=True)
    renewal_status = Column("RenewalStatus", String(50), nullable=False, default="None")
    issue_date = Column("IssueDate", DateTime, nullable=False)
    expiry_date = Column("ExpiryDate", DateTime, nullable=False)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="papers")
    driver = relationship("Driver", back_populates="documents")
    requirement = relationship("DocumentRequirement", back_populates="documents")
    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number.desc()",
    )


class DocumentVersion(TenantMixin, Base):
    __tablename__ = "DocumentVersions"
    __table_args__ = (
        UniqueConstraint("DocumentId", "VersionNumber", name="uq_document_versions_number"),
        Index("ix_document_versions_document_id", "DocumentId"),
        Index("ix_document_versions_expiry_date", "ExpiryDate"),
        Index(
            "uq_document_versions_current",
            "DocumentId",
            unique=True,
            sqlite_where=text('"IsCurrent" = 1'),
            postgresql_where=text('"IsCurrent" = true'),
        ),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    document_id = Column(
        "DocumentId",
        Integer,
        ForeignKey("VehiclePapers.Id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = Column("VersionNumber", Integer, nullable=False)
    attachment_id = Column("AttachmentId", Integer, ForeignKey("Attachments.Id", ondelete="RESTRICT"), nullable=True)
    file_path = Column("FilePath", String(500), nullable=False)
    document_number = Column("DocumentNumber", String(150), nullable=True)
    issuing_authority = Column("IssuingAuthority", String(255), nullable=True)
    issue_date = Column("IssueDate", DateTime, nullable=False)
    expiry_date = Column("ExpiryDate", DateTime, nullable=False)
    uploaded_by = Column("UploadedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    uploaded_at = Column("UploadedAt", DateTime, nullable=False, default=datetime.utcnow)
    verified_by = Column("VerifiedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    verified_at = Column("VerifiedAt", DateTime, nullable=True)
    rejection_reason = Column("RejectionReason", Text, nullable=True)
    renewal_status = Column("RenewalStatus", String(50), nullable=False, default="None")
    is_current = Column("IsCurrent", Boolean, nullable=False, default=True)
    archived = Column("Archived", Boolean, nullable=False, default=False)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    document = relationship("VehiclePaper", back_populates="versions")
    attachment = relationship("Attachment", foreign_keys=[attachment_id])
    uploader = relationship("User", foreign_keys=[uploaded_by])
    verifier = relationship("User", foreign_keys=[verified_by])


class VehicleService(TenantMixin, Base):
    __tablename__ = "VehicleServices"
    __table_args__ = (
        Index("uq_vehicle_services_work_order", "WorkOrderId", unique=True),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    work_order_id = Column("WorkOrderId", Integer, ForeignKey("WorkOrders.Id"), nullable=True)
    service_type = Column("ServiceType", String(100), nullable=False)
    description = Column("Description", Text, nullable=True)
    service_date = Column("ServiceDate", DateTime, nullable=False)
    odometer_km = Column("OdometerKm", Integer, nullable=True)
    vendor_id = Column("VendorId", Integer, ForeignKey("Vendors.Id", ondelete="SET NULL"), nullable=True)
    vendor = relationship("Vendor", foreign_keys=[vendor_id], back_populates="service_records")
    cost = Column("Cost", Numeric(12, 2), nullable=True)
    labor_cost = Column("LaborCost", Numeric(12, 2), nullable=True)
    parts_cost = Column("PartsCost", Numeric(12, 2), nullable=True)
    workshop = Column("Workshop", String(100), nullable=True)
    next_service_date = Column("NextServiceDate", DateTime, nullable=True)
    next_service_km_interval = Column("NextServiceKmInterval", Integer, nullable=True)
    next_service_odometer_km = Column("NextServiceOdometerKm", Integer, nullable=True)
    source = Column("Source", String(50), nullable=False, default="Manual")
    status = Column("Status", String(50), nullable=False, default="Completed")
    reminder_status = Column("ReminderStatus", String(50), nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="services")
    bills = relationship("ServiceBill", back_populates="service", cascade="all, delete-orphan")
    work_order = relationship("WorkOrder", foreign_keys=[work_order_id], back_populates="linked_service")
    reminder_work_orders = relationship("WorkOrder", foreign_keys="WorkOrder.reminder_service_id", back_populates="reminder_service")


class ServiceBill(TenantMixin, Base):
    __tablename__ = "ServiceBills"

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_service_id = Column("VehicleServiceId", Integer, ForeignKey("VehicleServices.Id", ondelete="CASCADE"), nullable=False)
    file_path = Column("FilePath", String(255), nullable=False)
    uploaded_at = Column("UploadedAt", DateTime, nullable=False)

    service = relationship("VehicleService", back_populates="bills")


class VehicleFuel(TenantMixin, Base):
    __tablename__ = "VehicleFuels"
    __table_args__ = (
        CheckConstraint('"Quantity" >= 0', name="ck_vehicle_fuels_quantity_nonnegative"),
        CheckConstraint('"UnitCost" >= 0', name="ck_vehicle_fuels_unit_cost_nonnegative"),
        CheckConstraint('"EnergyUnit" IN (\'L\', \'KWH\')', name="ck_vehicle_fuels_energy_unit"),
        Index("ix_vehicle_fuels_energy_unit", "EnergyUnit"),
        Index("ix_vehiclefuels_vehicle_assignment_id", "VehicleAssignmentId"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    vehicle_assignment_id = Column(
        "VehicleAssignmentId",
        Integer,
        ForeignKey("VehicleAssignments.Id", ondelete="SET NULL"),
        nullable=True,
    )
    refuel_date = Column("RefuelDate", DateTime, nullable=False)
    quantity = Column("Quantity", Numeric(12, 3), nullable=False)
    unit = Column("EnergyUnit", String(8), nullable=False)
    unit_cost = Column("UnitCost", Numeric(12, 4), nullable=False, default=0)
    total_cost = Column("TotalCost", Numeric(12, 2), nullable=False, default=0)
    fuel_type = Column("FuelType", String, nullable=False)
    unit_review_required = Column("UnitReviewRequired", Boolean, nullable=False, default=False)
    # Transitional historical columns. New records deliberately leave these
    # empty so Electric energy is never written to a column named Liters.
    liters = Column("Liters", Numeric(12, 3), nullable=True)
    cost_per_liter = Column("CostPerLiter", Numeric(12, 3), nullable=True)
    location = Column("Location", String, nullable=False)
    station_name = Column("StationName", String, nullable=False, default="")
    bill_file_path = Column("BillFilePath", String, nullable=True)
    odometer_km = Column("OdometerKm", Integer, nullable=False, default=0)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    vehicle = relationship("Vehicle", back_populates="fuels")
    vehicle_assignment = relationship("VehicleAssignment", back_populates="fuel_records")


class VehicleOperatingCost(TenantMixin, Base):
    """Costs not represented by fuel, maintenance, accidents, leases, or depreciation."""

    __tablename__ = "VehicleOperatingCosts"
    __table_args__ = (
        CheckConstraint(
            '"Category" IN (\'Insurance\', \'Registration\', \'Other Operating\')',
            name="ck_vehicle_operating_cost_category",
        ),
        CheckConstraint('"Amount" >= 0', name="ck_vehicle_operating_cost_amount_nonnegative"),
        Index("ix_vehicle_operating_costs_vehicle_date", "VehicleId", "CostDate"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    category = Column("Category", String(30), nullable=False)
    cost_date = Column("CostDate", Date, nullable=False)
    amount = Column("Amount", Numeric(14, 2), nullable=False)
    supplier_id = Column("SupplierId", Integer, ForeignKey("Suppliers.Id", ondelete="SET NULL"), nullable=True)
    description = Column("Description", Text, nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="operating_costs")
    supplier = relationship("Supplier")


class VehicleAccident(TenantMixin, Base):
    __tablename__ = "VehicleAccidents"
    __table_args__ = (
        Index("ix_vehicleaccidents_vehicle_assignment_id", "VehicleAssignmentId"),
        Index("ix_vehicleaccidents_driver_id", "DriverId"),
        Index("ix_vehicleaccidents_reservation_id", "ReservationId"),
        Index("ix_vehicleaccidents_status", "Status"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    vehicle_assignment_id = Column(
        "VehicleAssignmentId",
        Integer,
        ForeignKey("VehicleAssignments.Id", ondelete="SET NULL"),
        nullable=True,
    )
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="SET NULL"), nullable=True)
    reservation_id = Column(
        "ReservationId", Integer, ForeignKey("VehicleReservations.Id", ondelete="SET NULL"), nullable=True
    )
    accident_date = Column("AccidentDate", DateTime, nullable=False)
    location = Column("Location", String, nullable=False)
    severity = Column("Severity", String(50), nullable=False, default="Minor")
    status = Column("Status", String(50), nullable=False, default="Reported")
    police_involved = Column("PoliceInvolved", Boolean, nullable=False, default=False)
    police_report_number = Column("PoliceReportNumber", String(150), nullable=True)
    description = Column("Description", Text, nullable=True)
    vehicle_available_after_accident = Column("VehicleAvailableAfterAccident", Boolean, nullable=False, default=True)
    estimated_damage_cost = Column("EstimatedDamageCost", Numeric(12, 2), nullable=True)
    actual_damage_cost = Column("ActualDamageCost", Numeric(12, 2), nullable=True)
    fault_determination = Column("FaultDetermination", String(100), nullable=True)
    resolved_at = Column("ResolvedAt", DateTime, nullable=True)
    closed_at = Column("ClosedAt", DateTime, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    vehicle = relationship("Vehicle", back_populates="accidents")
    vehicle_assignment = relationship("VehicleAssignment", back_populates="accidents")
    driver = relationship("Driver", back_populates="accidents")
    reservation = relationship("VehicleReservation", back_populates="accidents")
    files = relationship("AccidentFile", back_populates="accident", cascade="all, delete-orphan")
    claim = relationship("AccidentClaim", back_populates="accident", cascade="all, delete-orphan", uselist=False)
    parties = relationship("AccidentParty", back_populates="accident", cascade="all, delete-orphan")
    injuries = relationship("AccidentInjury", back_populates="accident", cascade="all, delete-orphan")
    work_orders = relationship("WorkOrder", back_populates="accident")


class AccidentClaim(TenantMixin, Base):
    __tablename__ = "AccidentClaims"
    __table_args__ = (
        UniqueConstraint("AccidentId", name="uq_accident_claims_accident_id"),
        UniqueConstraint("CompanyId", "ClaimNumber", name="uq_accident_claims_company_claim_number"),
        Index("ix_accident_claims_status", "ClaimStatus"),
    )

    id = Column("Id", Integer, primary_key=True)
    accident_id = Column("AccidentId", Integer, ForeignKey("VehicleAccidents.Id", ondelete="CASCADE"), nullable=False)
    insurance_document_id = Column(
        "InsuranceDocumentId", Integer, ForeignKey("VehiclePapers.Id", ondelete="SET NULL"), nullable=True
    )
    insurance_company = Column("InsuranceCompany", String(255), nullable=False)
    policy_number = Column("PolicyNumber", String(150), nullable=False)
    claim_number = Column("ClaimNumber", String(150), nullable=False)
    claim_status = Column("ClaimStatus", String(50), nullable=False, default="Open")
    claim_opened_date = Column("ClaimOpenedDate", DateTime, nullable=False)
    claim_closed_date = Column("ClaimClosedDate", DateTime, nullable=True)
    settlement_amount = Column("SettlementAmount", Numeric(12, 2), nullable=True)
    deductible = Column("Deductible", Numeric(12, 2), nullable=True)
    adjuster_name = Column("AdjusterName", String(255), nullable=True)
    notes = Column("Notes", Text, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    accident = relationship("VehicleAccident", back_populates="claim")
    insurance_document = relationship("VehiclePaper")


class AccidentParty(TenantMixin, Base):
    __tablename__ = "AccidentParties"
    __table_args__ = (Index("ix_accident_parties_accident_id", "AccidentId"),)

    id = Column("Id", Integer, primary_key=True)
    accident_id = Column("AccidentId", Integer, ForeignKey("VehicleAccidents.Id", ondelete="CASCADE"), nullable=False)
    party_type = Column("PartyType", String(50), nullable=False)
    name = Column("Name", String(255), nullable=False)
    phone = Column("Phone", String(50), nullable=True)
    email = Column("Email", String(255), nullable=True)
    address = Column("Address", String(500), nullable=True)
    vehicle_registration = Column("VehicleRegistration", String(100), nullable=True)
    insurance_company = Column("InsuranceCompany", String(255), nullable=True)
    policy_number = Column("PolicyNumber", String(150), nullable=True)
    notes = Column("Notes", Text, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    accident = relationship("VehicleAccident", back_populates="parties")
    injuries = relationship("AccidentInjury", back_populates="party")


class AccidentInjury(TenantMixin, Base):
    __tablename__ = "AccidentInjuries"
    __table_args__ = (Index("ix_accident_injuries_accident_id", "AccidentId"),)

    id = Column("Id", Integer, primary_key=True)
    accident_id = Column("AccidentId", Integer, ForeignKey("VehicleAccidents.Id", ondelete="CASCADE"), nullable=False)
    party_id = Column("PartyId", Integer, ForeignKey("AccidentParties.Id", ondelete="SET NULL"), nullable=True)
    injured_person_name = Column("InjuredPersonName", String(255), nullable=False)
    injury_severity = Column("InjurySeverity", String(50), nullable=False)
    description = Column("Description", Text, nullable=True)
    medical_treatment = Column("MedicalTreatment", Text, nullable=True)
    hospitalized = Column("Hospitalized", Boolean, nullable=False, default=False)
    notes = Column("Notes", Text, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    accident = relationship("VehicleAccident", back_populates="injuries")
    party = relationship("AccidentParty", back_populates="injuries")


class AccidentFile(TenantMixin, Base):
    __tablename__ = "AccidentFiles"

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_accident_id = Column("VehicleAccidentId", Integer, ForeignKey("VehicleAccidents.Id", ondelete="CASCADE"), nullable=False)
    file_path = Column("FilePath", String, nullable=False)

    accident = relationship("VehicleAccident", back_populates="files")


class VehicleReservation(TenantMixin, Base):
    __tablename__ = "VehicleReservations"

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    reserved_by = Column("ReservedBy", String, nullable=False)
    reservation_type = Column("ReservationType", String, nullable=False)
    start_date = Column("StartDate", DateTime, nullable=False)
    end_date = Column("EndDate", DateTime, nullable=False)
    notes = Column("Notes", Text, nullable=True)
    status = Column("Status", Integer, nullable=False, default=0)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    vehicle = relationship("Vehicle", back_populates="reservations")
    assignments = relationship("VehicleAssignment", back_populates="reservation")
    accidents = relationship("VehicleAccident", back_populates="reservation")


class AuditLog(TenantMixin, Base):
    __tablename__ = "AuditLogs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "CreatedAt"),
        Index("ix_audit_logs_entity", "EntityType", "EntityId"),
        Index("ix_audit_logs_user_id", "UserId"),
    )

    id = Column("Id", Integer, primary_key=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    username = Column("Username", String(255), nullable=True)
    action = Column("Action", String(100), nullable=False)
    entity_type = Column("EntityType", String(100), nullable=False)
    entity_id = Column("EntityId", Integer, nullable=True)
    old_values = Column("OldValues", JSON, nullable=True)
    new_values = Column("NewValues", JSON, nullable=True)
    description = Column("Description", Text, nullable=True)
    action_code = Column("ActionCode", String(100), nullable=True)
    description_key = Column("DescriptionKey", String(255), nullable=True)
    description_params = Column("DescriptionParams", JSON, nullable=True)
    ip_address = Column("IpAddress", String(64), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User")


class ImportJob(TenantMixin, Base):
    """A retained, auditable CSV/XLSX import attempt.

    Source files and row results are intentionally kept separate from the
    target entities so validation is a genuine dry run.
    """

    __tablename__ = "ImportJobs"
    __table_args__ = (
        Index("ix_import_jobs_uploaded_by", "UploadedBy"),
        Index("ix_import_jobs_entity_status", "EntityType", "Status"),
        Index("ix_import_jobs_created_at", "CreatedAt"),
    )

    id = Column("Id", Integer, primary_key=True)
    entity_type = Column("EntityType", String(50), nullable=False)
    filename = Column("Filename", String(255), nullable=False)
    source_path = Column("SourcePath", String(500), nullable=False)
    uploaded_by = Column("UploadedBy", Integer, ForeignKey("Users.Id", ondelete="RESTRICT"), nullable=False)
    status = Column("Status", String(50), nullable=False, default="Uploaded")
    column_mapping = Column("ColumnMapping", JSON, nullable=True)
    update_mode = Column("UpdateMode", String(50), nullable=True)
    transaction_mode = Column("TransactionMode", String(20), nullable=True)
    source_headers = Column("SourceHeaders", JSON, nullable=True)
    total_rows = Column("TotalRows", Integer, nullable=False, default=0)
    valid_rows = Column("ValidRows", Integer, nullable=False, default=0)
    invalid_rows = Column("InvalidRows", Integer, nullable=False, default=0)
    created_rows = Column("CreatedRows", Integer, nullable=False, default=0)
    updated_rows = Column("UpdatedRows", Integer, nullable=False, default=0)
    skipped_rows = Column("SkippedRows", Integer, nullable=False, default=0)
    started_at = Column("StartedAt", DateTime, nullable=True)
    completed_at = Column("CompletedAt", DateTime, nullable=True)
    error_report_path = Column("ErrorReportPath", String(500), nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    uploader = relationship("User", foreign_keys=[uploaded_by])
    row_results = relationship(
        "ImportRowResult", back_populates="job", cascade="all, delete-orphan", order_by="ImportRowResult.row_number"
    )


class ImportRowResult(TenantMixin, Base):
    __tablename__ = "ImportRowResults"
    __table_args__ = (
        UniqueConstraint("ImportJobId", "RowNumber", name="uq_import_row_results_job_row"),
        Index("ix_import_row_results_job_status", "ImportJobId", "Status"),
    )

    id = Column("Id", Integer, primary_key=True)
    import_job_id = Column("ImportJobId", Integer, ForeignKey("ImportJobs.Id", ondelete="CASCADE"), nullable=False)
    row_number = Column("RowNumber", Integer, nullable=False)
    status = Column("Status", String(30), nullable=False)
    action = Column("Action", String(30), nullable=False)
    raw_data = Column("RawData", JSON, nullable=False)
    mapped_data = Column("MappedData", JSON, nullable=True)
    errors = Column("Errors", JSON, nullable=True)
    duplicate_fields = Column("DuplicateFields", JSON, nullable=True)
    target_id = Column("TargetId", Integer, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)

    job = relationship("ImportJob", back_populates="row_results")


class Notification(TenantMixin, Base):
    __tablename__ = "Notifications"
    __table_args__ = (
        UniqueConstraint("CompanyId", "DeduplicationKey", name="uq_notifications_company_deduplication_key"),
        Index("ix_notifications_user_status", "UserId", "Status"),
        Index("ix_notifications_created_at", "CreatedAt"),
    )

    id = Column("Id", Integer, primary_key=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id", ondelete="CASCADE"), nullable=False)
    notification_type = Column("NotificationType", String(100), nullable=False)
    title = Column("Title", String(255), nullable=False)
    message = Column("Message", Text, nullable=False)
    title_key = Column("TitleKey", String(255), nullable=True)
    message_key = Column("MessageKey", String(255), nullable=True)
    message_params = Column("MessageParams", JSON, nullable=True)
    priority = Column("Priority", String(20), nullable=False, default="Medium")
    status = Column("Status", String(20), nullable=False, default="Unread")
    entity_type = Column("EntityType", String(100), nullable=True)
    entity_id = Column("EntityId", Integer, nullable=True)
    deduplication_key = Column("DeduplicationKey", String(255), nullable=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    read_at = Column("ReadAt", DateTime, nullable=True)
    resolved_at = Column("ResolvedAt", DateTime, nullable=True)
    dismissed_at = Column("DismissedAt", DateTime, nullable=True)

    user = relationship("User")
    deliveries = relationship("NotificationDelivery", back_populates="notification", cascade="all, delete-orphan")


class NotificationPreference(TenantMixin, Base):
    __tablename__ = "NotificationPreferences"
    __table_args__ = (
        UniqueConstraint("CompanyId", "UserId", "NotificationType", name="uq_notification_preferences_user_type"),
        Index("ix_notification_preferences_user", "UserId"),
    )

    id = Column("Id", Integer, primary_key=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id", ondelete="CASCADE"), nullable=False)
    notification_type = Column("NotificationType", String(100), nullable=False)
    in_app_enabled = Column("InAppEnabled", Boolean, nullable=False, default=True)
    email_enabled = Column("EmailEnabled", Boolean, nullable=False, default=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class NotificationDelivery(TenantMixin, Base):
    __tablename__ = "NotificationDeliveries"
    __table_args__ = (
        UniqueConstraint("CompanyId", "NotificationId", "Channel", name="uq_notification_deliveries_notification_channel"),
        Index("ix_notification_deliveries_status_attempt", "Status", "NextAttemptAt"),
    )

    id = Column("Id", Integer, primary_key=True)
    notification_id = Column("NotificationId", Integer, ForeignKey("Notifications.Id", ondelete="CASCADE"), nullable=False)
    channel = Column("Channel", String(20), nullable=False)
    recipient = Column("Recipient", String(255), nullable=False)
    status = Column("Status", String(20), nullable=False, default="Pending")
    attempt_count = Column("AttemptCount", Integer, nullable=False, default=0)
    last_attempt = Column("LastAttempt", DateTime, nullable=True)
    next_attempt_at = Column("NextAttemptAt", DateTime, nullable=True)
    sent_at = Column("SentAt", DateTime, nullable=True)
    failure_reason = Column("FailureReason", Text, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    notification = relationship("Notification", back_populates="deliveries")


class Attachment(TenantMixin, Base):
    __tablename__ = "Attachments"
    __table_args__ = (
        Index("ix_attachments_entity", "EntityType", "EntityId"),
        Index("ix_attachments_uploaded_by", "UploadedBy"),
    )

    id = Column("Id", Integer, primary_key=True)
    original_filename = Column("OriginalFilename", String(255), nullable=False)
    stored_filename = Column("StoredFilename", String(255), nullable=False, unique=True)
    storage_path = Column("StoragePath", String(500), nullable=False, unique=True)
    mime_type = Column("MimeType", String(100), nullable=False)
    file_size = Column("FileSize", Integer, nullable=False)
    uploaded_by = Column("UploadedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)
    uploaded_at = Column("UploadedAt", DateTime, nullable=False, default=datetime.utcnow)
    entity_type = Column("EntityType", String(100), nullable=False)
    entity_id = Column("EntityId", Integer, nullable=False)
    archived = Column("Archived", Boolean, nullable=False, default=False)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    uploader = relationship("User", foreign_keys=[uploaded_by])


class ServiceProgram(TenantMixin, Base):
    __tablename__ = "ServicePrograms"
    __table_args__ = (UniqueConstraint("CompanyId", "Name", name="uq_service_program_name"),)
    id = Column("Id", Integer, primary_key=True)
    name = Column("Name", String(150), nullable=False)
    description = Column("Description", Text)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    archived = Column("Archived", Boolean, nullable=False, default=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    tasks = relationship("ServiceProgramTask", back_populates="program", order_by="ServiceProgramTask.display_order")


class ServiceProgramTask(TenantMixin, Base):
    __tablename__ = "ServiceProgramTasks"
    __table_args__ = (
        UniqueConstraint("CompanyId", "ProgramId", "ServiceType", name="uq_program_task_type"),
        CheckConstraint('"KmInterval" IS NOT NULL OR "MonthInterval" IS NOT NULL', name="ck_program_task_interval"),
        CheckConstraint('"KmInterval" IS NULL OR "KmInterval" > 0', name="ck_program_task_km"),
        CheckConstraint('"MonthInterval" IS NULL OR "MonthInterval" > 0', name="ck_program_task_month"),
    )
    id = Column("Id", Integer, primary_key=True)
    program_id = Column("ProgramId", Integer, ForeignKey("ServicePrograms.Id"), nullable=False, index=True)
    service_type = Column("ServiceType", String(100), nullable=False)
    title = Column("Title", String(150), nullable=False)
    description = Column("Description", Text)
    km_interval = Column("KmInterval", Integer)
    month_interval = Column("MonthInterval", Integer)
    whichever_occurs_first = Column("WhicheverOccursFirst", Boolean, nullable=False, default=True)
    warning_km = Column("WarningKm", Integer)
    warning_days = Column("WarningDays", Integer)
    priority = Column("Priority", String(50), nullable=False, default="Medium")
    auto_create_work_order = Column("AutoCreateWorkOrder", Boolean, nullable=False, default=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    display_order = Column("DisplayOrder", Integer, nullable=False, default=0)
    program = relationship("ServiceProgram", back_populates="tasks")


class ServiceProgramRule(TenantMixin, Base):
    __tablename__ = "ServiceProgramRules"
    id = Column("Id", Integer, primary_key=True)
    program_id = Column("ProgramId", Integer, ForeignKey("ServicePrograms.Id"), nullable=False, index=True)
    target_type = Column("TargetType", String(30), nullable=False)
    target_value = Column("TargetValue", String(255), nullable=False)
    model = Column("Model", String(150))
    effective_from = Column("EffectiveFrom", Date, nullable=False)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    assigned_by = Column("AssignedBy", Integer, ForeignKey("Users.Id"))
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    program = relationship("ServiceProgram")


class VehicleServiceProgram(TenantMixin, Base):
    __tablename__ = "VehicleServicePrograms"
    __table_args__ = (Index("uq_vehicle_active_program", "CompanyId", "VehicleId", unique=True,
                            sqlite_where=text('"IsActive" = 1'), postgresql_where=text('"IsActive" = true')),)
    id = Column("Id", Integer, primary_key=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id"), nullable=False, index=True)
    program_id = Column("ProgramId", Integer, ForeignKey("ServicePrograms.Id"), nullable=False)
    rule_id = Column("RuleId", Integer, ForeignKey("ServiceProgramRules.Id"), nullable=False)
    assigned_at = Column("AssignedAt", DateTime, nullable=False, default=datetime.utcnow)
    assigned_by = Column("AssignedBy", Integer, ForeignKey("Users.Id"))
    effective_from = Column("EffectiveFrom", Date, nullable=False)
    baseline_odometer_km = Column("BaselineOdometerKm", Integer)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    program = relationship("ServiceProgram")
    vehicle = relationship("Vehicle")


class ServiceProgramReminder(TenantMixin, Base):
    __tablename__ = "ServiceProgramReminders"
    __table_args__ = (
        Index("uq_program_active_reminder", "CompanyId", "AssignmentId", "TaskId", unique=True,
              sqlite_where=text('"IsActive" = 1'), postgresql_where=text('"IsActive" = true')),
        UniqueConstraint("WorkOrderId", name="uq_program_reminder_work_order"),
    )
    id = Column("Id", Integer, primary_key=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id"), nullable=False, index=True)
    assignment_id = Column("AssignmentId", Integer, ForeignKey("VehicleServicePrograms.Id"), nullable=False)
    task_id = Column("TaskId", Integer, ForeignKey("ServiceProgramTasks.Id"), nullable=False)
    basis_service_id = Column("BasisServiceId", Integer, ForeignKey("VehicleServices.Id"))
    due_date = Column("DueDate", Date)
    due_odometer_km = Column("DueOdometerKm", Integer)
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    resolution = Column("Resolution", String(30))
    resolved_at = Column("ResolvedAt", DateTime)
    work_order_id = Column("WorkOrderId", Integer, ForeignKey("WorkOrders.Id"))
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    task = relationship("ServiceProgramTask")
    vehicle = relationship("Vehicle")
    work_order = relationship("WorkOrder", back_populates="program_reminder")


class MobileOperation(TenantMixin, Base):
    """Durable retry receipts committed in the same transaction as the domain write."""
    __tablename__ = "MobileOperations"
    __table_args__ = (UniqueConstraint("CompanyId", "UserId", "OperationKey", name="uq_mobile_operation"),)
    id = Column("Id", Integer, primary_key=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id"), nullable=False)
    operation_key = Column("OperationKey", String(100), nullable=False)
    payload_hash = Column("PayloadHash", String(64), nullable=False)
    result = Column("Result", JSON, nullable=True)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)


class APIKey(TenantMixin, Base):
    __tablename__ = "APIKeys"
    id = Column("Id", Integer, primary_key=True)
    name = Column("Name", String(100), nullable=False)
    key_prefix = Column("KeyPrefix", String(24), nullable=False)
    key_hash = Column("KeyHash", String(64), nullable=False, unique=True)
    scopes = Column("Scopes", JSON, nullable=False)
    expires_at = Column("ExpiresAt", DateTime)
    last_used_at = Column("LastUsedAt", DateTime)
    revoked_at = Column("RevokedAt", DateTime)
    created_by = Column("CreatedBy", Integer, ForeignKey("Users.Id"), nullable=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)


class WebhookEndpoint(TenantMixin, Base):
    __tablename__ = "WebhookEndpoints"
    id = Column("Id", Integer, primary_key=True)
    name = Column("Name", String(100), nullable=False)
    url = Column("Url", String(2048), nullable=False)
    events = Column("Events", JSON, nullable=False)
    secret_ciphertext = Column("SecretCiphertext", Text, nullable=False)
    secret_version = Column("SecretVersion", Integer, nullable=False, default=1)
    revoked_at = Column("RevokedAt", DateTime)
    created_by = Column("CreatedBy", Integer, ForeignKey("Users.Id"), nullable=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)


class WebhookDelivery(TenantMixin, Base):
    __tablename__ = "WebhookDeliveries"
    __table_args__ = (
        CheckConstraint('"Status" IN (\'Pending\', \'Delivered\', \'Failed\', \'Retrying\', \'Dead\')', name="ck_webhook_delivery_status"),
        Index("ix_webhook_deliveries_due", "Status", "NextAttemptAt"),
        Index("uq_webhook_original_event", "CompanyId", "EndpointId", "EventId", unique=True,
              sqlite_where=text('"ResendOf" IS NULL'), postgresql_where=text('"ResendOf" IS NULL')),
        Index("ix_webhook_deliveries_event", "CompanyId", "EventId", "EndpointId"),
    )
    id = Column("Id", Integer, primary_key=True)
    endpoint_id = Column("EndpointId", Integer, ForeignKey("WebhookEndpoints.Id"), nullable=False)
    event_id = Column("EventId", String(36), nullable=False)
    delivery_id = Column("DeliveryId", String(36), nullable=False, unique=True)
    event_type = Column("EventType", String(80), nullable=False)
    payload = Column("Payload", Text, nullable=False)
    status = Column("Status", String(16), nullable=False, default="Pending")
    attempt_count = Column("AttemptCount", Integer, nullable=False, default=0)
    attempts = Column("Attempts", JSON, nullable=False, default=list)
    next_attempt_at = Column("NextAttemptAt", DateTime, nullable=False, default=datetime.utcnow)
    lease_token = Column("LeaseToken", String(36))
    lease_until = Column("LeaseUntil", DateTime)
    delivered_at = Column("DeliveredAt", DateTime)
    resend_of = Column("ResendOf", Integer, ForeignKey("WebhookDeliveries.Id"))
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
