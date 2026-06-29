from decimal import Decimal
from enum import IntEnum
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
