from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas import InspectionType

CATEGORIES = ["Tires", "Brakes", "Lights", "Fluids", "Safety", "Body", "Interior", "Documents", "Electrical", "EV System", "Other"]

class TemplateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    inspection_type: InspectionType
    is_active: bool = True

class TemplateItemIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    category: Literal["Tires", "Brakes", "Lights", "Fluids", "Safety", "Body", "Interior", "Documents", "Electrical", "EV System", "Other"] = "Other"
    display_order: int = Field(default=0, ge=0)
    required: bool = True
    critical: bool = False
    photo_required_on_failure: bool = False
    comment_required_on_failure: bool = False
    create_work_order_on_failure: bool = False
    mark_vehicle_unavailable_on_failure: bool = False
    generate_notification_on_failure: bool = True
    is_active: bool = True

class AssignmentIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    target_type: Literal["Vehicle", "Category", "FuelType", "BrandModel", "Location", "Department"]
    target_value: str = Field(min_length=1, max_length=255)
    model: str | None = Field(default=None, max_length=150)
    priority: int = Field(default=0, ge=-10000, le=10000)
    is_active: bool = True

    @model_validator(mode="after")
    def target(self):
        if self.target_type != "BrandModel" and self.model:
            raise ValueError("invalid_value")
        if self.target_type in {"Vehicle", "Location", "Department"}:
            if not self.target_value.isdigit() or int(self.target_value) < 1:
                raise ValueError("invalid_value")
            self.target_value = str(int(self.target_value))
        return self

class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["Daily", "Weekly", "Monthly", "Every X days", "Before check-out", "After return", "Mileage"]
    start_date: date = Field(default_factory=date.today)
    interval_days: int | None = Field(default=None, gt=0, le=3660)
    interval_km: int | None = Field(default=None, gt=0, le=1000000)
    baseline_odometer_km: int | None = Field(default=None, ge=0)
    is_active: bool = True

    @model_validator(mode="after")
    def intervals(self):
        if self.frequency == "Every X days" and self.interval_days is None:
            raise ValueError("inspection_schedule_interval")
        if self.frequency == "Mileage" and (self.interval_km is None or self.baseline_odometer_km is None):
            raise ValueError("inspection_schedule_interval")
        if self.frequency != "Every X days" and self.interval_days is not None:
            raise ValueError("inspection_schedule_interval")
        if self.frequency != "Mileage" and (self.interval_km is not None or self.baseline_odometer_km is not None):
            raise ValueError("inspection_schedule_interval")
        return self

class ReorderIn(BaseModel):
    item_ids: list[int] = Field(min_length=1)
