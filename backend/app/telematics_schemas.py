"""Canonical SI-unit input contract. Provider-specific payloads belong in adapters."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class ConnectionSettings(StrictModel):
    min_confidence: float = Field(default=0.9, ge=0.9, le=1)
    max_reading_age_seconds: int = Field(default=3600, ge=1, le=86400)
    online_after_seconds: int = Field(default=900, ge=60, le=86400)


class ConnectionCreate(StrictModel):
    provider: Literal["generic", "geotab", "samsara", "motive", "oem"]
    credentials_reference: str | None = Field(default=None, pattern=r"^env:TELEMATICS_[A-Z0-9_]{1,100}$")
    settings: ConnectionSettings = Field(default_factory=ConnectionSettings)


class ConnectionUpdate(StrictModel):
    enabled: bool
    credentials_reference: str | None = Field(default=None, pattern=r"^env:TELEMATICS_[A-Z0-9_]{1,100}$")
    settings: ConnectionSettings = Field(default_factory=ConnectionSettings)


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    status: str
    last_sync_at: datetime | None
    last_error: str | None
    settings: ConnectionSettings


class MappingCreate(StrictModel):
    vehicle_id: int = Field(gt=0)
    external_vehicle_id: str = Field(min_length=1, max_length=200)
    vin: str | None = Field(default=None, min_length=1, max_length=50)
    external_device_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("vin")
    @classmethod
    def uppercase_vin(cls, value):
        return value.upper() if value else value


class MappingOut(MappingCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    connection_id: int
    odometer_sync_enabled: bool


class OdometerPolicy(StrictModel):
    enabled: bool
    release_manual_override: bool = False


class EventBase(StrictModel):
    external_event_id: str = Field(min_length=1, max_length=200)
    external_vehicle_id: str = Field(min_length=1, max_length=200)
    occurred_at: datetime

    @field_validator("latitude", "longitude", "speed_kph", "heading", "distance_km", "odometer_km",
                     "confidence", "engine_hours", "fuel_percent", "soc_percent", check_fields=False)
    @classmethod
    def storage_precision(cls, value, info):
        if value is None:
            return None
        places = 7 if info.field_name in {"latitude", "longitude"} else 4 if info.field_name == "confidence" else 3
        # Normalize before hashing/comparing: storage rounding must never increase
        # confidence/mileage or turn a valid heading just below 360 into 360.
        return float(Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_DOWN))

    @field_validator("occurred_at", check_fields=False)
    @classmethod
    def utc_timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(timezone.utc).replace(tzinfo=None)


class LocationInput(EventBase):
    kind: Literal["location"]
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed_kph: float | None = Field(default=None, ge=0, le=1000)
    heading: float | None = Field(default=None, ge=0, lt=360)
    ignition: bool | None = None
    idling: bool | None = None


class TripInput(EventBase):
    kind: Literal["trip"]
    ended_at: datetime
    distance_km: float = Field(ge=0, le=1000000)
    idle_seconds: int = Field(ge=0)

    @field_validator("ended_at")
    @classmethod
    def utc_end(cls, value):
        return cls.utc_timestamp(value)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.ended_at < self.occurred_at or self.idle_seconds > (self.ended_at - self.occurred_at).total_seconds():
            raise ValueError("Invalid trip interval or idle duration")
        return self


class OdometerInput(EventBase):
    kind: Literal["odometer"]
    odometer_km: float = Field(ge=0, le=100000000)
    confidence: float = Field(ge=0, le=1)


class EngineHourInput(EventBase):
    kind: Literal["engine_hours"]
    engine_hours: float = Field(ge=0, le=100000000)


class FuelLevelInput(EventBase):
    kind: Literal["fuel_level"]
    fuel_percent: float = Field(ge=0, le=100)


class BatteryLevelInput(EventBase):
    kind: Literal["battery_level"]
    soc_percent: float = Field(ge=0, le=100)


class DiagnosticInput(EventBase):
    kind: Literal["diagnostic"]
    code: str = Field(pattern=r"^[A-Z0-9_-]{1,50}$")
    active: bool


class BehaviorInput(EventBase):
    kind: Literal["behavior"]
    behavior: Literal["harsh_braking", "harsh_acceleration", "harsh_cornering", "speeding", "idling"]
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)


NormalizedEvent = Annotated[LocationInput | TripInput | OdometerInput | EngineHourInput | FuelLevelInput | BatteryLevelInput | DiagnosticInput | BehaviorInput, Field(discriminator="kind")]


class EventBatch(StrictModel):
    events: list[NormalizedEvent] = Field(min_length=1, max_length=500)
