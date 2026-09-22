from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    integrations_encryption_key: str = ""

    app_name: str = "VehicleManagement API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/vehiclemanagement.db"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    cors_origins_value: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
        validation_alias=AliasChoices("CORS_ORIGINS", "FRONTEND_ORIGINS"),
    )
    upload_directory: str = Field(default="uploads", validation_alias=AliasChoices("UPLOAD_DIRECTORY", "UPLOADS_DIR"))
    jwt_secret_key: str = Field(
        default="change-this-local-development-secret",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY"),
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    auth_cookie_name: str = "vehicle_fleet_control_session"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict"] = "lax"
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 900
    max_document_size: int = 10 * 1024 * 1024
    max_image_size: int = 8 * 1024 * 1024
    allowed_document_types: str = "application/pdf"
    allowed_image_types: str = "image/jpeg,image/png,image/webp"
    storage_provider: Literal["local", "s3"] = "local"
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"
    error_monitoring_provider: Literal["none", "sentry"] = "none"
    sentry_dsn: str | None = None
    release: str = "development"
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        # Standard PostgreSQL URLs use psycopg 3; SQLite remains the local default.
        if self.database_url.startswith(("postgres://", "postgresql://")):
            self.database_url = "postgresql+psycopg://" + self.database_url.split("://", 1)[1]
        if not self.database_url.startswith(("sqlite:", "sqlite+pysqlite:", "postgresql+psycopg:")):
            raise ValueError("DATABASE_URL must use SQLite or PostgreSQL (psycopg).")
        if self.storage_provider == "s3":
            if not self.s3_bucket:
                raise ValueError("S3_BUCKET is required for object storage.")
            if bool(self.s3_access_key) != bool(self.s3_secret_key):
                raise ValueError("Supply both S3 credentials, or neither to use the IAM credential chain.")
            if self.s3_endpoint and urlsplit(self.s3_endpoint).scheme not in {"http", "https"}:
                raise ValueError("S3_ENDPOINT must use HTTP(S).")
        if self.error_monitoring_provider == "sentry" and not self.sentry_dsn:
            raise ValueError("SENTRY_DSN is required for Sentry monitoring.")
        for origin in self.cors_origins:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                    or parsed.password or parsed.path or parsed.query or parsed.fragment or "*" in origin):
                raise ValueError("CORS_ORIGINS must contain exact HTTP(S) origins without paths or wildcards.")
        if not self.auth_cookie_name or any(c in self.auth_cookie_name for c in " ;=\r\n"):
            raise ValueError("AUTH_COOKIE_NAME must be a valid cookie name.")
        if self.environment in {"staging", "production"}:
            secret = self.jwt_secret_key.strip()
            if (len(secret) < 32 or len(set(secret)) < 12 or any(marker in secret.lower() for marker in
                    ("change-this", "replace-with", "changeme", "your-secret", "development-secret"))):
                raise ValueError("Production requires a non-default JWT_SECRET_KEY with at least 32 characters.")
            if self.debug:
                raise ValueError("DEBUG must be false in production.")
            if not self.cors_origins or "*" in self.cors_origins:
                raise ValueError("Production CORS_ORIGINS must contain explicit trusted origins.")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production CORS_ORIGINS must use HTTPS.")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production.")
        if self.access_token_expire_minutes <= 0:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be positive.")
        if self.login_rate_limit_attempts <= 0 or self.login_rate_limit_window_seconds <= 0:
            raise ValueError("Login rate-limit settings must be positive.")
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
