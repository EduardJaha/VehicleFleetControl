from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator

SCOPES = {
    "vehicles.read": {"vehicles.view"},
    "drivers.read": {"drivers.view"},
    "fuel.write": {"fuel.create", "fuel.view"},
    "maintenance.read": {"maintenance.view"},
    "maintenance.write": {"maintenance.view", "maintenance.create_work_order", "maintenance.assign_work_order", "maintenance.complete_work_order"},
    "reports.read": {"reports.view", "reports.export"},
}
EVENTS = (
    "vehicle.created", "vehicle.updated", "driver.created", "assignment.started",
    "assignment.completed", "inspection.failed", "work_order.created", "work_order.completed",
    "service.created", "fuel.created", "document.expiring", "reservation.approved",
    "accident.reported", "claim.updated",
)


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=len(SCOPES))
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def valid_scopes(cls, value):
        if not set(value) <= SCOPES.keys():
            raise ValueError("Unknown API key scope")
        return sorted(set(value))

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value):
        if value:
            value = value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
            if value <= datetime.utcnow():
                raise ValueError("Expiration must be in the future")
        return value


class APIKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_id: int
    name: str
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_by: int
    created_at: datetime


class APIKeyIssued(APIKeyOut):
    raw_key: str


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(max_length=2048)
    events: list[str] = Field(min_length=1, max_length=len(EVENTS))

    @field_validator("events")
    @classmethod
    def valid_events(cls, value):
        if not set(value) <= set(EVENTS):
            raise ValueError("Unknown webhook event")
        return sorted(set(value))


class WebhookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_id: int
    name: str
    url: str
    events: list[str]
    secret_version: int
    revoked_at: datetime | None
    created_by: int
    created_at: datetime


class WebhookIssued(WebhookOut):
    secret: str


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    endpoint_id: int
    event_id: str
    delivery_id: str
    event_type: str
    payload: str
    status: str
    attempt_count: int
    attempts: list[dict]
    next_attempt_at: datetime
    delivered_at: datetime | None
    resend_of: int | None
    created_at: datetime
