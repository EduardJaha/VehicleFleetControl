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
    service_type = Column("ServiceType", String(100), nullable=False)
    description = Column("Description", Text, nullable=True)
    service_date = Column("ServiceDate", DateTime, nullable=False)
    odometer_km = Column("OdometerKm", Integer, nullable=True)
    cost = Column("Cost", String, nullable=True)
    workshop = Column("Workshop", String(100), nullable=True)
    next_service_date = Column("NextServiceDate", DateTime, nullable=True)
    next_service_km_interval = Column("NextServiceKmInterval", Integer, nullable=True)
    next_service_odometer_km = Column("NextServiceOdometerKm", Integer, nullable=True)

    vehicle = relationship("Vehicle", back_populates="services")
    bills = relationship("ServiceBill", back_populates="service", cascade="all, delete-orphan")


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
