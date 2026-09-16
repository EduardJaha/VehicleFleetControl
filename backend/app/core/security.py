from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, set_tenant_context
from app.models import Company, CompanyUser, User
from app.schemas import UserRole

pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
_DUMMY_PASSWORD_HASH = pwd_context.hash("not-a-real-user-password")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password_or_dummy(plain_password: str, hashed_password: str | None) -> bool:
    """Keep unknown-user and wrong-password verification work comparable."""
    return verify_password(plain_password, hashed_password or _DUMMY_PASSWORD_HASH)


def create_access_token(
    subject: str | int,
    expires_delta: timedelta | None = None,
    *,
    session_version: int = 0,
    company_id: int | None = None,
) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire, "sv": session_version}
    if company_id is not None:
        payload["cid"] = company_id
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def validate_access_token(token: str, db: Session, *, request_path: str | None = None) -> User:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options={"require_exp": True})
        subject = payload.get("sub")
        if subject is None:
            raise credentials_error
        user_id = int(subject)
        token_session_version = int(payload.get("sv", 0))
        token_company_id = int(payload["cid"]) if payload.get("cid") is not None else None
    except (JWTError, ValueError, TypeError) as exc:
        raise credentials_error from exc

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    if token_session_version != (user.session_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked.")
    if not user.is_active:
        raise credentials_error
    company_id = token_company_id or user.company_id
    membership = db.query(CompanyUser).filter(
        CompanyUser.user_id == user.id,
        CompanyUser.company_id == company_id,
        CompanyUser.is_active.is_(True),
    ).first()
    any_membership = db.query(CompanyUser).execution_options(skip_tenant_scope=True).filter(
        CompanyUser.user_id == user.id,
        CompanyUser.company_id == company_id,
    ).first()
    # Membership rows are mandatory after the multi-company migration. The
    # fallback keeps pre-migration test databases and rolling deployments valid.
    if membership is None and (company_id != user.company_id or any_membership is not None):
        raise credentials_error
    company = db.query(Company).filter(Company.id == company_id).first()
    if (company is not None and not company.is_active) or (company is None and membership is not None):
        raise credentials_error
    set_tenant_context(db, company_id)
    db.info["user_id"] = user.id
    db.info["company_role"] = membership.role if membership is not None else user.role
    password_change_paths = {
        f"{settings.api_v1_prefix}/auth/me",
        f"{settings.api_v1_prefix}/auth/me/password",
        f"{settings.api_v1_prefix}/auth/me/language",
        f"{settings.api_v1_prefix}/auth/logout",
    }
    if user.password_reset_required and request_path is not None and request_path not in password_change_paths:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "password_change_required",
                "message": "Password change is required.",
                "params": {},
            },
        )
    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    settings = get_settings()
    access_token = (request.cookies.get(settings.auth_cookie_name) if request is not None else None) or token
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return validate_access_token(access_token, db, request_path=request.url.path if request is not None else None)


def require_roles(*roles: UserRole):
    allowed = {role.value for role in roles}

    def dependency(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        from app.core.authorization import active_role
        if active_role(db, current_user) not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return current_user

    return dependency
