from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
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
from app.db.session import Base


class User(Base):
    __tablename__ = "Users"
    __table_args__ = (UniqueConstraint("Email", name="uq_users_email"),)

    id = Column("Id", Integer, primary_key=True, index=True)
    email = Column("Email", String(255), nullable=False, index=True)
    full_name = Column("FullName", String(255), nullable=False)
    hashed_password = Column("HashedPassword", String(255), nullable=False)
    role = Column("Role", String(50), nullable=False, default="viewer")
    is_active = Column("IsActive", Boolean, nullable=False, default=True)
    preferred_language = Column("PreferredLanguage", String(5), nullable=False, default="en")
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    driver_profile = relationship("Driver", back_populates="user", uselist=False, foreign_keys="Driver.user_id")
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


class Vehicle(Base):
    __tablename__ = "Vehicles"
    __table_args__ = (
        UniqueConstraint(
            "RegistrationCountry",
            "LicensePlateNormalized",
            name="uq_vehicles_registration_country_license_plate_normalized",
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
    vehicle_category = Column("VehicleCategory", String(100), nullable=True, index=True)
    license_plate = Column("LicensePlate", String, nullable=False, index=True)
    registration_country = Column("RegistrationCountry", String(2), nullable=False)
    license_plate_normalized = Column("LicensePlateNormalized", String(7), nullable=False)
    status = Column("Status", Integer, nullable=False, default=0)
    engine_cc = Column("EngineCc", Integer, nullable=True)
    vin_number = Column("VinNumber", String(50), nullable=True)
    year = Column("Year", Integer, nullable=True)
    odometer_km = Column("OdometerKm", Integer, nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False, index=True)
    archived_at = Column("ArchivedAt", DateTime, nullable=True)
    archived_by = Column("ArchivedBy", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True)

    catalog_brand = relationship("VehicleBrand", back_populates="vehicles", foreign_keys=[brand_id])
    catalog_model = relationship("VehicleModel", back_populates="vehicles", foreign_keys=[model_id])
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


class Driver(Base):
    __tablename__ = "Drivers"
    __table_args__ = (
        UniqueConstraint("Email", name="uq_drivers_email"),
        UniqueConstraint("EmployeeNumber", name="uq_drivers_employee_number"),
        UniqueConstraint("LicenseNumber", name="uq_drivers_license_number"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    full_name = Column("FullName", String(255), nullable=False)
    phone_number = Column("PhoneNumber", String(50), nullable=True)
    email = Column("Email", String(255), nullable=True, index=True)
    employee_number = Column("EmployeeNumber", String(100), nullable=False, index=True)
    department = Column("Department", String(100), nullable=True)
    license_number = Column("LicenseNumber", String(100), nullable=False, index=True)
    license_category = Column("LicenseCategory", String(50), nullable=False)
    license_expiry_date = Column("LicenseExpiryDate", DateTime, nullable=False)
    assigned_vehicle_id = Column("AssignedVehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="SET NULL"), nullable=True)
    user_id = Column("UserId", Integer, ForeignKey("Users.Id", ondelete="SET NULL"), nullable=True, unique=True)
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


class VehicleAssignment(Base):
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
            "VehicleId",
            unique=True,
            sqlite_where=text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = 0'),
            postgresql_where=text('"Status" IN (\'Active\', \'Overdue\') AND "Archived" = false'),
        ),
        Index(
            "uq_vehicle_assignments_active_driver",
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


class VehicleConditionRecord(Base):
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


class Inspection(Base):
    __tablename__ = "Inspections"
    __table_args__ = (
        Index("ix_inspections_vehicle_assignment_id", "VehicleAssignmentId"),
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


class InspectionItem(Base):
    __tablename__ = "InspectionItems"

    id = Column("Id", Integer, primary_key=True, index=True)
    inspection_id = Column("InspectionId", Integer, ForeignKey("Inspections.Id", ondelete="CASCADE"), nullable=False)
    item_name = Column("ItemName", String(150), nullable=False)
    status = Column("Status", String(50), nullable=False, default="Not Checked")
    comment = Column("Comment", Text, nullable=True)

    inspection = relationship("Inspection", back_populates="items")


class WorkOrder(Base):
    __tablename__ = "WorkOrders"
    __table_args__ = (
        Index("ix_work_orders_reminder_service", "ReminderServiceId"),
        Index("ix_work_orders_accident_id", "AccidentId"),
    )

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="SET NULL"), nullable=True)
    inspection_id = Column("InspectionId", Integer, ForeignKey("Inspections.Id", ondelete="SET NULL"), nullable=True)
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


class DocumentRequirement(Base):
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


class VehiclePaper(Base):
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


class DocumentVersion(Base):
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


class VehicleService(Base):
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


class ServiceBill(Base):
    __tablename__ = "ServiceBills"

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_service_id = Column("VehicleServiceId", Integer, ForeignKey("VehicleServices.Id", ondelete="CASCADE"), nullable=False)
    file_path = Column("FilePath", String(255), nullable=False)
    uploaded_at = Column("UploadedAt", DateTime, nullable=False)

    service = relationship("VehicleService", back_populates="bills")


class VehicleFuel(Base):
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


class VehicleAccident(Base):
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


class AccidentClaim(Base):
    __tablename__ = "AccidentClaims"
    __table_args__ = (
        UniqueConstraint("AccidentId", name="uq_accident_claims_accident_id"),
        UniqueConstraint("ClaimNumber", name="uq_accident_claims_claim_number"),
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


class AccidentParty(Base):
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


class AccidentInjury(Base):
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


class AccidentFile(Base):
    __tablename__ = "AccidentFiles"

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_accident_id = Column("VehicleAccidentId", Integer, ForeignKey("VehicleAccidents.Id", ondelete="CASCADE"), nullable=False)
    file_path = Column("FilePath", String, nullable=False)

    accident = relationship("VehicleAccident", back_populates="files")


class VehicleReservation(Base):
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


class AuditLog(Base):
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


class Notification(Base):
    __tablename__ = "Notifications"
    __table_args__ = (
        UniqueConstraint("DeduplicationKey", name="uq_notifications_deduplication_key"),
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


class Attachment(Base):
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
