from functools import lru_cache
from pathlib import Path
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VehicleManagement API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/vehiclemanagement.db"
    environment: str = "development"
    debug: bool = False
    cors_origins_value: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices("CORS_ORIGINS", "FRONTEND_ORIGINS"),
    )
    upload_directory: str = Field(default="uploads", validation_alias=AliasChoices("UPLOAD_DIRECTORY", "UPLOADS_DIR"))
    jwt_secret_key: str = Field(
        default="change-this-local-development-secret",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY"),
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    max_document_size: int = 10 * 1024 * 1024
    max_image_size: int = 8 * 1024 * 1024
    allowed_document_types: str = "application/pdf"
    allowed_image_types: str = "image/jpeg,image/png,image/webp"
    antivirus_provider: str = "none"
    email_backend: str = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "notifications@vehiclefleetcontrol.local"
    smtp_from_name: str = "VehicleFleetControl"
    smtp_use_tls: bool = True
    frontend_url: str = "http://localhost:3000"
    email_max_attempts: int = 4
    email_retry_base_minutes: int = 5
    email_delivery_interval_minutes: int = 1
    notification_scan_interval_minutes: int = 15
    document_scan_interval_hours: int = 24
    maintenance_scan_interval_minutes: int = 60
    overdue_return_scan_interval_minutes: int = 15
    low_stock_scan_interval_minutes: int = 60
    claim_scan_interval_minutes: int = 1440
    claim_reminder_after_days: int = 7

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment.lower() == "production":
            if self.jwt_secret_key == "change-this-local-development-secret" or len(self.jwt_secret_key) < 32:
                raise ValueError("Production requires a non-default JWT_SECRET_KEY with at least 32 characters.")
            if self.debug:
                raise ValueError("DEBUG must be false in production.")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS cannot contain '*' in production.")
        if self.email_backend not in {"console", "smtp", "mock"}:
            raise ValueError("EMAIL_BACKEND must be console, mock, or smtp.")
        if self.email_backend == "smtp" and (not self.smtp_host or not self.smtp_from_email):
            raise ValueError("SMTP_HOST and SMTP_FROM_EMAIL are required for the SMTP email backend.")
        intervals = (
            self.email_delivery_interval_minutes,
            self.notification_scan_interval_minutes,
            self.document_scan_interval_hours,
            self.maintenance_scan_interval_minutes,
            self.overdue_return_scan_interval_minutes,
            self.low_stock_scan_interval_minutes,
            self.claim_scan_interval_minutes,
            self.email_max_attempts,
            self.email_retry_base_minutes,
        )
        if any(value <= 0 for value in intervals):
            raise ValueError("Scheduler intervals and email retry settings must be positive.")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_value.split(",") if origin.strip()]

    @property
    def uploads_path(self) -> Path:
        return Path(self.upload_directory)

    @property
    def document_mime_types(self) -> set[str]:
        return {value.strip().lower() for value in self.allowed_document_types.split(",") if value.strip()}

    @property
    def image_mime_types(self) -> set[str]:
        return {value.strip().lower() for value in self.allowed_image_types.split(",") if value.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
