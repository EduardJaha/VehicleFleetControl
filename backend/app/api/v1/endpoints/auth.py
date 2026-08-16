from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import uuid4

from app.core.authorization import active_role, get_user_permissions, require_permission
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.db.session import get_db, set_tenant_context
from app.models import Company, CompanySettings, CompanyUser, Role, User, UserRole as UserRoleAssignment
from app.schemas import (
    FirstAdminCreate,
    LanguageCode,
    LanguagePreferenceOut,
    LanguagePreferenceUpdate,
    LoginRequest,
    PasswordChangeRequest,
    TokenOut,
    CompanySwitchRequest,
    UserCreate,
    UserOut,
    UserRole,
)
from app.services.audit import record_audit

router = APIRouter()


def user_out(user: User, db: Session | None = None) -> UserOut:
    assignments = list(user.role_assignments) if db is not None else []
    memberships = []
    if db is not None and user.id is not None:
        memberships = db.query(CompanyUser).execution_options(skip_tenant_scope=True).filter(
            CompanyUser.user_id == user.id,
            CompanyUser.is_active.is_(True),
        ).order_by(CompanyUser.is_default.desc(), CompanyUser.id).all()
    companies = []
    for membership in memberships:
        company = db.query(Company).filter(Company.id == membership.company_id).first() if db else None
        if company and company.is_active:
            companies.append({"id": company.id, "name": company.name, "role": membership.role})
    selected_role = active_role(db, user)
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=selected_role,
        is_active=user.is_active,
        preferred_language=LanguageCode(user.preferred_language or "en"),
        roles=[assignment.role.code for assignment in assignments] or [selected_role],
        permissions=sorted(get_user_permissions(db, user)),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        password_reset_required=user.password_reset_required,
        driver_id=user.driver_profile.id if user.driver_profile else None,
        role_assignments=[{
            "role_id": assignment.role_id,
            "location_id": assignment.location_id,
            "department_id": assignment.department_id,
            "cost_center_id": assignment.cost_center_id,
            "own_records_only": assignment.own_records_only,
        } for assignment in assignments],
        company_id=db.info.get("company_id", user.company_id) if db is not None else user.company_id,
        companies=companies,
    )


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.strip().lower()).first()


def create_user_record(db: Session, payload: UserCreate | FirstAdminCreate, role: UserRole | None = None) -> User:
    selected_role = role or getattr(payload, "role", UserRole.viewer)
    user = User(
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        role=selected_role.value if isinstance(selected_role, UserRole) else str(selected_role),
        is_active=getattr(payload, "is_active", True),
        preferred_language=getattr(payload, "preferred_language", LanguageCode.en).value,
    )
    db.add(user)
    try:
        db.flush()
        configured_role = db.query(Role).filter(Role.code == user.role, Role.is_active.is_(True)).first()
        if configured_role:
            db.add(UserRoleAssignment(user_id=user.id, role_id=configured_role.id))
        db.add(CompanyUser(
            company_id=user.company_id,
            user_id=user.id,
            role=user.role,
            is_active=True,
            is_default=True,
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A user with this email already exists.") from exc
    db.refresh(user)
    return user


@router.post("/register", response_model=TokenOut, status_code=201)
def register_company_admin(payload: FirstAdminCreate, db: Session = Depends(get_db)):
    # Registration is company onboarding, not a one-time database bootstrap.
    # Email remains a global login identity; existing users must be invited to
    # another company from authenticated administration instead of re-registering.
    company = Company(name=payload.company_name.strip(), slug=f"company-{uuid4().hex[:12]}")
    db.add(company)
    db.flush()
    db.add(CompanySettings(company_id=company.id))
    set_tenant_context(db, company.id)
    db.info["company_role"] = UserRole.admin.value
    user = create_user_record(db, payload, UserRole.admin)
    record_audit(
        db, action="User created", entity_type="User", entity_id=user.id, user=user,
        new_values={"email": user.email, "full_name": user.full_name, "role": user.role, "is_active": user.is_active},
        description="Company Administrator user created.",
    )
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, session_version=user.session_version, company_id=company.id), user=user_out(user, db))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = find_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user.hashed_password):
        if user:
            set_tenant_context(db, user.company_id)
            db.info["user_id"] = user.id
            db.info["company_role"] = user.role
            record_audit(
                db, action="Login failure", entity_type="User", entity_id=user.id,
                user=user, new_values={"email": payload.email}, description="Login failed: invalid credentials.",
            )
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    if not user.is_active:
        set_tenant_context(db, user.company_id)
        db.info["user_id"] = user.id
        db.info["company_role"] = user.role
        record_audit(
            db, action="Login failure", entity_type="User", entity_id=user.id, user=user,
            description="Login failed: inactive account.",
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive.")
    memberships = db.query(CompanyUser).filter(
        CompanyUser.user_id == user.id,
        CompanyUser.is_active.is_(True),
    ).order_by(CompanyUser.is_default.desc(), CompanyUser.id).all()
    company_id = memberships[0].company_id if memberships else user.company_id
    company = db.query(Company).filter(Company.id == company_id, Company.is_active.is_(True)).first()
    if memberships and company is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company is inactive.")
    set_tenant_context(db, company_id)
    db.info["user_id"] = user.id
    db.info["company_role"] = memberships[0].role if memberships else user.role
    from datetime import datetime
    user.last_login_at = datetime.utcnow()
    record_audit(
        db, action="Login success", entity_type="User", entity_id=user.id, user=user,
        description="User logged in successfully.",
    )
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, session_version=user.session_version, company_id=company_id), user=user_out(user, db))


@router.post("/switch-company", response_model=TokenOut)
def switch_company(
    payload: CompanySwitchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    membership = db.query(CompanyUser).execution_options(skip_tenant_scope=True).filter(
        CompanyUser.user_id == current_user.id,
        CompanyUser.company_id == payload.company_id,
        CompanyUser.is_active.is_(True),
    ).first()
    company = db.query(Company).filter(Company.id == payload.company_id, Company.is_active.is_(True)).first()
    if membership is None or company is None:
        raise HTTPException(status_code=404, detail="Company was not found.")
    set_tenant_context(db, company.id)
    db.info["company_role"] = membership.role
    return TokenOut(
        access_token=create_access_token(current_user.id, session_version=current_user.session_version, company_id=company.id),
        user=user_out(current_user, db),
    )


@router.get("/me", response_model=UserOut)
def me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return user_out(current_user, db)


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
):
    return [
        user_out(user, db)
        for user in db.query(User).order_by(User.full_name, User.email).all()
    ]


@router.put("/me/language", response_model=LanguagePreferenceOut)
def update_my_language(
    payload: LanguagePreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    old_language = current_user.preferred_language or "en"
    current_user.preferred_language = payload.language.value
    record_audit(
        db,
        action="Language preference changed",
        action_code="user_language_changed",
        entity_type="User",
        entity_id=current_user.id,
        user=current_user,
        old_values={"preferred_language": old_language},
        new_values={"preferred_language": payload.language.value},
        description="User language preference changed.",
        description_key="audit.userLanguageChanged",
        description_params={"language": payload.language.value},
    )
    db.commit()
    return LanguagePreferenceOut(preferred_language=payload.language)


@router.put("/me/password", response_model=TokenOut)
def change_my_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    current_user.hashed_password = hash_password(payload.new_password)
    current_user.password_reset_required = False
    current_user.session_version = (current_user.session_version or 0) + 1
    record_audit(db, action="Password changed", entity_type="User", entity_id=current_user.id, user=current_user, description="User changed their password and existing sessions were revoked.")
    db.commit()
    return TokenOut(
        access_token=create_access_token(current_user.id, session_version=current_user.session_version, company_id=db.info.get("company_id")),
        user=user_out(current_user, db),
    )


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("users.manage"))):
    user = create_user_record(db, payload)
    record_audit(
        db, action="User created", entity_type="User", entity_id=user.id, user=current_user,
        new_values={"email": user.email, "full_name": user.full_name, "role": user.role, "is_active": user.is_active},
        description=f"User {user.email} created.",
    )
    db.commit()
    return user_out(user, db)
