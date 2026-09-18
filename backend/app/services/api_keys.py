"""High-entropy bearer credentials, bounded routes and live permission intersection."""
import hashlib
import re
import secrets
from datetime import datetime

from fastapi import HTTPException
from app.core.config import get_settings
from app.db.session import set_tenant_context
from app.integration_schemas import SCOPES
from app.models import APIKey, Company, CompanyUser, User

# Explicit route allowlist: new routes do not silently become externally accessible.
ROUTES = (
    ("GET", r"/vehicles(?:/\d+)?", "vehicles.read"),
    ("GET", r"/drivers(?:/\d+)?", "drivers.read"),
    ("POST", r"/fuel", "fuel.write"),
    ("GET", r"/(?:work-orders(?:/\d+)?|services/(?:history|reminders|id/\d+)|maintenance/summary)", "maintenance.read"),
    ("POST", r"/(?:work-orders(?:/\d+/complete)?|services(?:/register-with-bill|/upload-bill-later)?)", "maintenance.write"),
    ("PUT", r"/(?:work-orders/\d+(?:/status)?|services/id/\d+)", "maintenance.write"),
    ("GET", r"/reports/(?:fleet-summary|fuel-costs|service-costs|vehicle-costs|tco|reservations|document-expiry|document-compliance|work-orders|accidents)(?:/export)?", "reports.read"),
)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_key(db, *, company_id, user_id, name, scopes, expires_at=None):
    raw = "vfc_" + secrets.token_urlsafe(32)
    row = APIKey(company_id=company_id, created_by=user_id, name=name, scopes=scopes,
                 expires_at=expires_at, key_prefix=raw[:12], key_hash=hash_key(raw))
    db.add(row)
    db.flush()
    return row, raw


def authenticate_key(raw, db, request):
    unauthorized = HTTPException(401, detail={"code": "integration_key_invalid", "message": "Invalid or expired API key."})
    if len(raw) > 100 or not re.fullmatch(r"vfc_[A-Za-z0-9_-]{43}", raw):
        raise unauthorized
    row = db.query(APIKey).execution_options(skip_tenant_scope=True).filter(APIKey.key_hash == hash_key(raw)).first()
    now = datetime.utcnow()
    if row is None or row.revoked_at or (row.expires_at and row.expires_at <= now):
        raise unauthorized
    company = db.get(Company, row.company_id)
    user = db.query(User).execution_options(skip_tenant_scope=True).filter(User.id == row.created_by).first()
    member = db.query(CompanyUser).execution_options(skip_tenant_scope=True).filter(
        CompanyUser.company_id == row.company_id, CompanyUser.user_id == row.created_by,
        CompanyUser.is_active.is_(True)).first()
    if not company or not company.is_active or not user or not user.is_active or user.password_reset_required or not member:
        raise unauthorized
    prefix = get_settings().api_v1_prefix
    path = request.url.path.removeprefix(prefix).rstrip("/")
    required = next((scope for method, pattern, scope in ROUTES
                     if request.method == method and re.fullmatch(pattern, path)), None)
    if required is None or required not in row.scopes:
        raise HTTPException(403, detail={"code": "integration_scope_denied", "message": "API key scope does not permit this operation."})
    set_tenant_context(db, row.company_id)
    db.info.update(user_id=user.id, company_role=member.role)
    from app.core.authorization import get_user_permissions, authorization_scope
    allowed = set().union(*(SCOPES[scope] for scope in row.scopes if scope in SCOPES))
    allowed &= get_user_permissions(db, user)
    if any(not authorization_scope(db, user, permission).unrestricted for permission in allowed):
        raise HTTPException(403, detail="API keys require unrestricted domain grants.")
    # The normal endpoint dependencies also enforce exact permissions and record scopes.
    if not allowed.intersection(SCOPES[required]):
        raise HTTPException(403, detail="Insufficient permissions.")
    db.info["api_key_permissions"] = allowed
    db.info["api_key_id"] = row.id
    row.last_used_at = now
    db.commit()
    return user
