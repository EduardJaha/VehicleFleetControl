"""Shared fixed-window throttling with atomic reservations before password work."""
from datetime import datetime, timedelta
from hashlib import sha256
import hmac
import math

from sqlalchemy import case, delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import localized_http_exception
from app.models import LoginRateLimit


def _bucket_key(client_ip: str, email: str | None) -> str:
    identity = f"{client_ip}\0{email.strip().lower() if email is not None else '<all-accounts>'}"
    return hmac.new(get_settings().jwt_secret_key.encode(), identity.encode(), sha256).hexdigest()


def reserve_login_attempt(db: Session, client_ip: str, email: str, *, now: datetime | None = None) -> bool:
    """Reserve pair and IP budgets; return True only on the pair threshold.

    Success resets its pair. The broader IP budget (10x) counts all requests
    so spraying other accounts cannot evade it. Requests never extend a window.
    """
    current = now or datetime.utcnow()
    settings = get_settings()
    cutoff = current - timedelta(seconds=settings.login_rate_limit_window_seconds)
    table = LoginRateLimit.__table__
    dialect = db.get_bind().dialect.name
    insert = sqlite_insert if dialect == "sqlite" else pg_insert if dialect == "postgresql" else None
    if insert is None:
        raise RuntimeError("Login throttling requires SQLite or PostgreSQL.")
    db.execute(delete(table).where(table.c.UpdatedAt < cutoff))
    retry_after = 0
    reached_threshold = False
    for account, limit in ((None, settings.login_rate_limit_attempts * 10), (email, settings.login_rate_limit_attempts)):
        key = _bucket_key(client_ip, account)
        expired = table.c.WindowStartedAt <= cutoff
        db.execute(insert(table).values(
            KeyHash=key, AttemptCount=0, WindowStartedAt=current, UpdatedAt=current,
        ).on_conflict_do_nothing(index_elements=[table.c.KeyHash]))
        row = db.execute(update(table).where(table.c.KeyHash == key).values(
            AttemptCount=case((expired, 1), else_=table.c.AttemptCount + 1),
            WindowStartedAt=case((expired, current), else_=table.c.WindowStartedAt),
            UpdatedAt=current,
        ).returning(table.c.AttemptCount, table.c.WindowStartedAt)).one()
        if row.AttemptCount > limit:
            retry_after = max(retry_after, math.ceil((row.WindowStartedAt + timedelta(
                seconds=settings.login_rate_limit_window_seconds) - current).total_seconds()))
            break
        if account is not None:
            reached_threshold = row.AttemptCount == limit
    db.commit()
    if retry_after:
        exc = localized_http_exception(429, "login_rate_limited")
        exc.headers = {"Retry-After": str(max(1, retry_after))}
        raise exc
    return reached_threshold


def reset_login_failures(db: Session, client_ip: str, email: str) -> None:
    db.execute(delete(LoginRateLimit).where(LoginRateLimit.key_hash == _bucket_key(client_ip, email)))
    # Caller commits alongside last-login and audit changes.
