from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProgramIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    is_active: bool = True


class ProgramTaskIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    service_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    km_interval: int | None = Field(default=None, gt=0, le=1000000)
    month_interval: int | None = Field(default=None, gt=0, le=120)
    whichever_occurs_first: bool = True
    warning_km: int | None = Field(default=None, ge=0, le=1000000)
    warning_days: int | None = Field(default=None, ge=0, le=3660)
    priority: Literal["Low", "Medium", "High", "Critical"] = "Medium"
    auto_create_work_order: bool = False
    is_active: bool = True
    display_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def intervals(self):
        if self.km_interval is None and self.month_interval is None:
            raise ValueError("program_interval_required")
        if self.warning_km is not None and (self.km_interval is None or self.warning_km > self.km_interval):
            raise ValueError("program_warning_invalid")
        if self.warning_days is not None and self.month_interval is None:
            raise ValueError("program_warning_invalid")
        return self


class ProgramRuleIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    program_id: int = Field(gt=0)
    target_type: Literal["Vehicle", "BrandModel", "FuelType", "Category", "Location", "Department"]
    target_value: str = Field(min_length=1, max_length=255)
    model: str | None = Field(default=None, max_length=150)
    effective_from: date = Field(default_factory=date.today)
    is_active: bool = True

    @model_validator(mode="after")
    def target(self):
        if self.target_type != "BrandModel" and self.model:
            raise ValueError("program_target_invalid")
        if self.target_type in {"Vehicle", "Location", "Department"}:
            if not self.target_value.isdigit() or int(self.target_value) < 1:
                raise ValueError("program_target_invalid")
            self.target_value = str(int(self.target_value))
        return self
