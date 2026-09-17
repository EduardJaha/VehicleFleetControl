from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.http_security import HttpSecurityMiddleware
import app.models  # noqa: F401 ensures SQLAlchemy model registration
from app.core.errors import http_exception_handler, request_validation_exception_handler

from sqlalchemy import text
from starlette.responses import JSONResponse
from app.db.session import engine
from app.services.storage import get_storage
from app.core.observability import configure_logging, RequestTelemetryMiddleware
from app.core.deployment import validate_deployment

configure_logging()
settings = get_settings()
validate_deployment(settings)

app = FastAPI(title=settings.app_name, debug=settings.debug)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)

app.add_middleware(HttpSecurityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.add_middleware(RequestTelemetryMiddleware)

@app.get("/health/live")
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health/ready")
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            # Refuse traffic when a database is reachable but not migrated to this release.
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            heads = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
            current = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if current != heads:
                raise RuntimeError("Schema not ready")
        get_storage().check()
    except Exception:
        return JSONResponse({"status": "not_ready"}, status_code=503, headers={"Cache-Control": "no-store"})
    return JSONResponse({"status": "ready"}, headers={"Cache-Control": "no-store"})
