from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import user_out
from app.core.authorization import PERMISSION_CATALOG, require_any_permission, require_permission, seed_authorization_defaults
from app.core.security import hash_password
from app.db.session import get_db
from app.models import (
    CostCenter,
    Department,
    Driver,
    Location,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    MasterDataCreate,
    MasterDataOut,
    MasterDataUpdate,
    PasswordResetRequest,
    PermissionOut,
    RoleCreate,
    RoleSummaryOut,
    RoleUpdate,
    ScopeAssignmentIn,
    UserOut,
)
from app.services.audit import record_audit

router = APIRouter()


def ensure_defaults(db: Session) -> None:
    if db.query(Permission).count() != len(PERMISSION_CATALOG):
        seed_authorization_defaults(db)


def role_out(role: Role, db: Session) -> RoleSummaryOut:
    return RoleSummaryOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        is_active=role.is_active,
        permissions=sorted(grant.permission.code for grant in role.role_permissions),
        user_count=db.query(UserRole).filter(UserRole.role_id == role.id).count(),
    )


def validate_permissions(db: Session, codes: list[str]) -> list[Permission]:
    unique_codes = set(codes)
    rows = db.query(Permission).filter(Permission.code.in_(unique_codes)).all() if unique_codes else []
    if len(rows) != len(unique_codes):
        found = {row.code for row in rows}
        raise HTTPException(400, detail=f"Unknown permissions: {', '.join(sorted(unique_codes - found))}")
    return rows


def set_role_permissions(db: Session, role: Role, codes: list[str]) -> None:
    permissions = validate_permissions(db, codes)
    role.role_permissions.clear()
    db.flush()
    role.role_permissions.extend(RolePermission(permission_id=row.id) for row in permissions)


def validate_assignments(db: Session, assignments: list[ScopeAssignmentIn]) -> list[tuple[Role, ScopeAssignmentIn]]:
    if not assignments:
        raise HTTPException(400, detail="At least one role is required.")
    if len({assignment.role_id for assignment in assignments}) != len(assignments):
        raise HTTPException(400, detail="A role can only be assigned once per user.")
    result = []
    for assignment in assignments:
        role = db.get(Role, assignment.role_id)
        if role is None or not role.is_active:
            raise HTTPException(400, detail=f"Role {assignment.role_id} is not active.")
        for model, value, label in (
            (Location, assignment.location_id, "location"),
            (Department, assignment.department_id, "department"),
            (CostCenter, assignment.cost_center_id, "cost center"),
        ):
            if value is not None and db.get(model, value) is None:
                raise HTTPException(400, detail=f"Unknown {label} {value}.")
        result.append((role, assignment))
    return result


def replace_assignments(db: Session, user: User, assignments: list[ScopeAssignmentIn]) -> None:
    validated = validate_assignments(db, assignments)
    user.role_assignments.clear()
    db.flush()
    for role, scope in validated:
        user.role_assignments.append(UserRole(
            role_id=role.id,
            location_id=scope.location_id,
            department_id=scope.department_id,
            cost_center_id=scope.cost_center_id,
            own_records_only=scope.own_records_only,
        ))
    user.role = validated[0][0].code


def link_driver(db: Session, user: User, driver_id: int | None) -> None:
    if user.driver_profile and user.driver_profile.id != driver_id:
        user.driver_profile.user_id = None
    if driver_id is None:
        return
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(400, detail="Driver profile was not found.")
    if driver.user_id not in (None, user.id):
        raise HTTPException(409, detail="Driver profile is linked to another user.")
    driver.user = user


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(db: Session = Depends(get_db), _: User = Depends(require_permission("roles.manage"))):
    ensure_defaults(db)
    return db.query(Permission).order_by(Permission.module, Permission.code).all()


@router.get("/roles", response_model=list[RoleSummaryOut])
def list_roles(db: Session = Depends(get_db), _: User = Depends(require_any_permission("roles.manage", "users.manage"))):
    ensure_defaults(db)
    return [role_out(role, db) for role in db.query(Role).order_by(Role.is_system.desc(), Role.name).all()]


@router.post("/roles", response_model=RoleSummaryOut, status_code=201)
def create_role(payload: RoleCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("roles.manage"))):
    ensure_defaults(db)
    role = Role(code=payload.code, name=payload.name.strip(), description=payload.description, is_system=False)
    db.add(role)
    try:
        db.flush()
        set_role_permissions(db, role, payload.permission_codes)
        record_audit(db, action="Role created", entity_type="Role", entity_id=role.id, user=current_user, new_values={"code": role.code, "permissions": payload.permission_codes})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail="A role with this code already exists.") from exc
    db.refresh(role)
    return role_out(role, db)


@router.put("/roles/{role_id}", response_model=RoleSummaryOut)
def update_role(role_id: int, payload: RoleUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("roles.manage"))):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(404, detail="Role was not found.")
    old = {"name": role.name, "is_active": role.is_active, "permissions": [row.permission.code for row in role.role_permissions]}
    role.name = payload.name.strip()
    role.description = payload.description
    role.is_active = payload.is_active
    set_role_permissions(db, role, payload.permission_codes)
    record_audit(db, action="Role updated", entity_type="Role", entity_id=role.id, user=current_user, old_values=old, new_values={"name": role.name, "is_active": role.is_active, "permissions": payload.permission_codes})
    db.commit()
    db.refresh(role)
    return role_out(role, db)


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    ensure_defaults(db)
    return [user_out(user, db) for user in db.query(User).order_by(User.full_name, User.email).all()]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: AdminUserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("users.manage"))):
    ensure_defaults(db)
    validated = validate_assignments(db, payload.role_assignments)
    user = User(
        email=payload.email.strip().lower(), full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password), role=validated[0][0].code,
        is_active=payload.is_active, preferred_language=payload.preferred_language.value,
    )
    db.add(user)
    try:
        db.flush()
        replace_assignments(db, user, payload.role_assignments)
        link_driver(db, user, payload.driver_id)
        record_audit(db, action="User created", entity_type="User", entity_id=user.id, user=current_user, new_values={"email": user.email, "roles": [row[0].code for row in validated], "is_active": user.is_active})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail="A user with this email already exists.") from exc
    db.refresh(user)
    return user_out(user, db)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: AdminUserUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("users.manage"))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, detail="User was not found.")
    old = {"email": user.email, "role": user.role, "is_active": user.is_active, "preferred_language": user.preferred_language}
    user.email = payload.email.strip().lower()
    user.full_name = payload.full_name.strip()
    user.preferred_language = payload.preferred_language.value
    if user.is_active and not payload.is_active:
        user.session_version = (user.session_version or 0) + 1
    user.is_active = payload.is_active
    replace_assignments(db, user, payload.role_assignments)
    link_driver(db, user, payload.driver_id)
    try:
        record_audit(db, action="User updated", entity_type="User", entity_id=user.id, user=current_user, old_values=old, new_values={"email": user.email, "role": user.role, "is_active": user.is_active, "preferred_language": user.preferred_language})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail="A user with this email already exists.") from exc
    db.refresh(user)
    return user_out(user, db)


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(user_id: int, payload: PasswordResetRequest, db: Session = Depends(get_db), current_user: User = Depends(require_permission("users.manage"))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, detail="User was not found.")
    user.hashed_password = hash_password(payload.temporary_password)
    user.password_reset_required = payload.require_change
    user.session_version = (user.session_version or 0) + 1
    record_audit(db, action="Password reset", entity_type="User", entity_id=user.id, user=current_user, description="Administrator reset the user's password and revoked existing sessions.")
    db.commit()


@router.post("/users/{user_id}/revoke-sessions", status_code=204)
def revoke_sessions(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("users.manage"))):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, detail="User was not found.")
    user.session_version = (user.session_version or 0) + 1
    record_audit(db, action="Sessions revoked", entity_type="User", entity_id=user.id, user=current_user, description="Administrator revoked all user sessions.")
    db.commit()


MASTER_MODELS = {"locations": Location, "departments": Department, "cost-centers": CostCenter}


@router.get("/{kind}", response_model=list[MasterDataOut])
def list_master_data(kind: str, db: Session = Depends(get_db), _: User = Depends(require_any_permission("settings.manage", "users.manage"))):
    model = MASTER_MODELS.get(kind)
    if model is None:
        raise HTTPException(404, detail="Unknown settings type.")
    return db.query(model).order_by(model.name).all()


@router.post("/{kind}", response_model=MasterDataOut, status_code=201)
def create_master_data(kind: str, payload: MasterDataCreate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("settings.manage"))):
    model = MASTER_MODELS.get(kind)
    if model is None:
        raise HTTPException(404, detail="Unknown settings type.")
    row = model(code=payload.code.strip(), name=payload.name.strip(), is_active=True)
    db.add(row)
    try:
        db.flush()
        record_audit(db, action="Master data created", entity_type=model.__name__, entity_id=row.id, user=current_user, new_values={"code": row.code, "name": row.name})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail="This code is already in use.") from exc
    db.refresh(row)
    return row


@router.put("/{kind}/{row_id}", response_model=MasterDataOut)
def update_master_data(kind: str, row_id: int, payload: MasterDataUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_permission("settings.manage"))):
    model = MASTER_MODELS.get(kind)
    row = db.get(model, row_id) if model else None
    if row is None:
        raise HTTPException(404, detail="Settings record was not found.")
    old = {"code": row.code, "name": row.name, "is_active": row.is_active}
    row.code, row.name, row.is_active = payload.code.strip(), payload.name.strip(), payload.is_active
    try:
        record_audit(db, action="Master data updated", entity_type=model.__name__, entity_id=row.id, user=current_user, old_values=old, new_values={"code": row.code, "name": row.name, "is_active": row.is_active})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail="This code is already in use.") from exc
    db.refresh(row)
    return row
