from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    driver_profile = relationship("Driver", back_populates="user", uselist=False)


class Vehicle(Base):
    __tablename__ = "Vehicles"
    __table_args__ = (UniqueConstraint("LicensePlate", name="uq_vehicles_license_plate"),)

    id = Column("Id", Integer, primary_key=True, index=True)
    brand = Column("Brand", String, nullable=False)
    model = Column("Model", String, nullable=False)
    fuel_type = Column("FuelType", String, nullable=False)
    vehicle_location = Column("VehicleLocation", String, nullable=False)
    license_plate = Column("LicensePlate", String, nullable=False, index=True)
    status = Column("Status", Integer, nullable=False, default=0)
    engine_cc = Column("EngineCc", Integer, nullable=True)
    vin_number = Column("VinNumber", String(50), nullable=True)
    year = Column("Year", Integer, nullable=True)
    odometer_km = Column("OdometerKm", Integer, nullable=True)

    papers = relationship("VehiclePaper", back_populates="vehicle", cascade="all, delete-orphan")
    services = relationship("VehicleService", back_populates="vehicle", cascade="all, delete-orphan")
    fuels = relationship("VehicleFuel", back_populates="vehicle", cascade="all, delete-orphan")
    accidents = relationship("VehicleAccident", back_populates="vehicle", cascade="all, delete-orphan")
    reservations = relationship("VehicleReservation", back_populates="vehicle", cascade="all, delete-orphan")
    assigned_drivers = relationship("Driver", back_populates="assigned_vehicle")
    inspections = relationship("Inspection", back_populates="vehicle", cascade="all, delete-orphan")
    work_orders = relationship("WorkOrder", back_populates="vehicle", cascade="all, delete-orphan")


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

    assigned_vehicle = relationship("Vehicle", back_populates="assigned_drivers")
    user = relationship("User", back_populates="driver_profile")
    inspections = relationship("Inspection", back_populates="driver")
    work_orders = relationship("WorkOrder", back_populates="driver")


class Inspection(Base):
    __tablename__ = "Inspections"

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="SET NULL"), nullable=True)
    inspection_type = Column("InspectionType", String(50), nullable=False)
    inspection_date = Column("InspectionDate", DateTime, nullable=False)
    overall_status = Column("OverallStatus", String(50), nullable=False, default="Needs Review")
    notes = Column("Notes", Text, nullable=True)
    inspector = Column("Inspector", String(150), nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="inspections")
    driver = relationship("Driver", back_populates="inspections")
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

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    driver_id = Column("DriverId", Integer, ForeignKey("Drivers.Id", ondelete="SET NULL"), nullable=True)
    inspection_id = Column("InspectionId", Integer, ForeignKey("Inspections.Id", ondelete="SET NULL"), nullable=True)
    reminder_service_id = Column("ReminderServiceId", Integer, ForeignKey("VehicleServices.Id", ondelete="SET NULL"), nullable=True)
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
    labor_cost = Column("LaborCost", String, nullable=True)
    parts_cost = Column("PartsCost", String, nullable=True)
    total_cost = Column("TotalCost", String, nullable=True)
    notes = Column("Notes", Text, nullable=True)
    completed_odometer_km = Column("CompletedOdometerKm", Integer, nullable=True)
    completion_notes = Column("CompletionNotes", Text, nullable=True)
    completed_by = Column("CompletedBy", String(150), nullable=True)
    created_by = Column("CreatedBy", String(150), nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False)
    created_at = Column("CreatedAt", DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column("UpdatedAt", DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="work_orders")
    driver = relationship("Driver", back_populates="work_orders")
    inspection = relationship("Inspection", back_populates="work_orders")
    reminder_service = relationship("VehicleService", foreign_keys=[reminder_service_id], back_populates="reminder_work_orders")
    linked_service = relationship("VehicleService", foreign_keys="VehicleService.work_order_id", back_populates="work_order", uselist=False)


class VehiclePaper(Base):
    __tablename__ = "VehiclePapers"

    id = Column("Id", Integer, primary_key=True, index=True)
    document_type = Column("DocumentType", String, nullable=False)
    file_path = Column("FilePath", String, nullable=False)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    issue_date = Column("IssueDate", DateTime, nullable=False)
    expiry_date = Column("ExpiryDate", DateTime, nullable=False)

    vehicle = relationship("Vehicle", back_populates="papers")


class VehicleService(Base):
    __tablename__ = "VehicleServices"

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    work_order_id = Column("WorkOrderId", Integer, ForeignKey("WorkOrders.Id", ondelete="SET NULL"), nullable=True, unique=True)
    service_type = Column("ServiceType", String(100), nullable=False)
    description = Column("Description", Text, nullable=True)
    service_date = Column("ServiceDate", DateTime, nullable=False)
    odometer_km = Column("OdometerKm", Integer, nullable=True)
    cost = Column("Cost", String, nullable=True)
    labor_cost = Column("LaborCost", String, nullable=True)
    parts_cost = Column("PartsCost", String, nullable=True)
    workshop = Column("Workshop", String(100), nullable=True)
    next_service_date = Column("NextServiceDate", DateTime, nullable=True)
    next_service_km_interval = Column("NextServiceKmInterval", Integer, nullable=True)
    next_service_odometer_km = Column("NextServiceOdometerKm", Integer, nullable=True)
    source = Column("Source", String(50), nullable=False, default="Manual")
    status = Column("Status", String(50), nullable=False, default="Completed")
    reminder_status = Column("ReminderStatus", String(50), nullable=True)
    archived = Column("Archived", Boolean, nullable=False, default=False)
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

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    refuel_date = Column("RefuelDate", DateTime, nullable=False)
    liters = Column("Liters", String, nullable=False)
    cost_per_liter = Column("CostPerLiter", String, nullable=False, default="0")
    total_cost = Column("TotalCost", String, nullable=False, default="0")
    fuel_type = Column("FuelType", String, nullable=False)
    location = Column("Location", String, nullable=False)
    station_name = Column("StationName", String, nullable=False, default="")
    bill_file_path = Column("BillFilePath", String, nullable=True)
    odometer_km = Column("OdometerKm", Integer, nullable=False, default=0)

    vehicle = relationship("Vehicle", back_populates="fuels")


class VehicleAccident(Base):
    __tablename__ = "VehicleAccidents"

    id = Column("Id", Integer, primary_key=True, index=True)
    vehicle_id = Column("VehicleId", Integer, ForeignKey("Vehicles.Id", ondelete="CASCADE"), nullable=False)
    accident_date = Column("AccidentDate", DateTime, nullable=False)
    location = Column("Location", String, nullable=False)
    description = Column("Description", Text, nullable=True)

    vehicle = relationship("Vehicle", back_populates="accidents")
    files = relationship("AccidentFile", back_populates="accident", cascade="all, delete-orphan")


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

    vehicle = relationship("Vehicle", back_populates="reservations")
