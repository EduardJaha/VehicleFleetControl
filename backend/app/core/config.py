from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VehicleManagement API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/vehiclemanagement.db"
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    uploads_dir: str = "uploads"
    secret_key: str = "change-this-local-development-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()
