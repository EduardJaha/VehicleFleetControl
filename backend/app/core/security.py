from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, set_tenant_context
from app.models import Company, CompanyUser, User
from app.schemas import UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


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


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        subject = payload.get("sub")
        if subject is None:
            raise credentials_error
        user_id = int(subject)
        token_session_version = int(payload.get("sv", 0))
        token_company_id = int(payload["cid"]) if payload.get("cid") is not None else None
    except (JWTError, ValueError) as exc:
        raise credentials_error from exc

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    if token_session_version != (user.session_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive.")
    company_id = token_company_id or user.company_id
    membership = db.query(CompanyUser).filter(
        CompanyUser.user_id == user.id,
        CompanyUser.company_id == company_id,
        CompanyUser.is_active.is_(True),
    ).first()
    # Membership rows are mandatory after the multi-company migration. The
    # fallback keeps pre-migration test databases and rolling deployments valid.
    if membership is None and company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company access is not available.")
    company = db.query(Company).filter(Company.id == company_id, Company.is_active.is_(True)).first()
    if company is None and membership is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company is inactive.")
    set_tenant_context(db, company_id)
    db.info["user_id"] = user.id
    db.info["company_role"] = membership.role if membership is not None else user.role
    return user


def require_roles(*roles: UserRole):
    allowed = {role.value for role in roles}

    def dependency(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        from app.core.authorization import active_role
        if active_role(db, current_user) not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return current_user

    return dependency
