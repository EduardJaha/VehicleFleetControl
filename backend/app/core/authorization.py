from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models import Permission, Role, RolePermission, User, UserRole as UserRoleAssignment


PERMISSION_CATALOG: dict[str, tuple[str, str]] = {
    "integrations.manage": ("Administration", "Manage API keys and webhooks"),
    "parts.view": ('Parts', 'View parts catalog'),
    "parts.manage": ('Parts', 'Manage parts catalog'),
    "inventory.view": ('Inventory', 'View stock and transactions'),
    "inventory.manage": ('Inventory', 'Move and reserve stock'),
    "vendors.view": ('Vendors', 'View vendors'),
    "vendors.manage": ('Vendors', 'Manage vendors'),
    "purchase_orders.view": ('Purchasing', 'View purchase orders'),
    "purchase_orders.create": ('Purchasing', 'Create and edit purchase orders'),
    "purchase_orders.approve": ('Purchasing', 'Approve purchase orders'),
    "technicians.view": ('Technicians', 'View technicians'),
    "technicians.manage": ('Technicians', 'Manage technicians'),
    "labor.manage": ('Maintenance', 'Record and clock labor'),
    "maintenance.manage_costs": ('Maintenance', 'Manage costs and vendor charges'),
    "dashboard.view": ("Dashboard", "View operational dashboard"),
    "vehicles.view": ("Vehicles", "View vehicles"),
    "vehicles.create": ("Vehicles", "Create vehicles"),
    "vehicles.edit": ("Vehicles", "Edit vehicles"),
    "vehicles.archive": ("Vehicles", "Archive and restore vehicles"),
    "drivers.view": ("Drivers", "View drivers"),
    "drivers.manage": ("Drivers", "Create, edit, and archive drivers"),
    "assignments.view": ("Assignments", "View vehicle assignments"),
    "assignments.self_service": ("Assignments", "Check out and return own assigned vehicles"),
    "accidents.report": ("Accidents", "Report accidents for own vehicles"),
    "maintenance.report_issue": ("Maintenance", "Report issues for own vehicles"),
    "assignments.manage": ("Assignments", "Manage vehicle assignments"),
    "fuel.view": ("Fuel", "View fuel and charging records"),
    "fuel.create": ("Fuel", "Create fuel and charging records"),
    "fuel.edit": ("Fuel", "Edit and archive fuel records"),
    "fuel.view_cost": ("Fuel", "View fuel pricing and cost totals"),
    "maintenance.view": ("Maintenance", "View maintenance records"),
    "maintenance.create_work_order": ("Maintenance", "Create work orders"),
    "maintenance.assign_work_order": ("Maintenance", "Assign and edit work orders"),
    "maintenance.complete_work_order": ("Maintenance", "Complete work orders"),
    "inspection_templates.manage": ("Inspections", "Configure inspection templates, rules, and schedules"),
    "inspections.view": ("Inspections", "View inspections"),
    "inspections.create": ("Inspections", "Create inspections"),
    "inspections.manage": ("Inspections", "Edit and archive inspections"),
    "documents.view": ("Documents", "View documents"),
    "documents.upload": ("Documents", "Upload and renew documents"),
    "documents.verify": ("Documents", "Verify documents and manage requirements"),
    "reservations.view": ("Reservations", "View reservations"),
    "reservations.create": ("Reservations", "Create reservations"),
    "reservations.approve": ("Reservations", "Approve, reject, archive, and restore reservations"),
    "reports.view": ("Reports", "View reports"),
    "reports.export": ("Reports", "Export reports"),
    "accidents.view": ("Accidents", "View accident records"),
    "accidents.manage": ("Accidents", "Manage accident records"),
    "claims.manage": ("Accidents", "Manage insurance claims"),
    "imports.manage": ("Imports", "Validate and execute imports"),
    "audit_logs.view": ("Administration", "View audit logs"),
    "users.manage": ("Administration", "Manage users and sessions"),
    "roles.manage": ("Administration", "Manage roles and permissions"),
    "settings.manage": ("Administration", "Manage locations, departments, and cost centers"),
}

ALL_PERMISSIONS = frozenset(PERMISSION_CATALOG)
DEFAULT_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": ALL_PERMISSIONS,
    "fleet_manager": frozenset(p for p in ALL_PERMISSIONS if p not in {"users.manage", "roles.manage", "settings.manage", "integrations.manage"}),
    "mechanic": frozenset({
        "parts.view", "inventory.view", "inventory.manage", "vendors.view", "technicians.view", "labor.manage",
        "dashboard.view", "vehicles.view", "drivers.view", "assignments.view",
        "maintenance.view", "maintenance.create_work_order", "maintenance.assign_work_order",
        "maintenance.complete_work_order", "inspections.view", "inspections.create", "inspections.manage",
        "documents.view", "accidents.view",
    }),
    "driver": frozenset({
        "assignments.self_service", "accidents.report", "maintenance.report_issue",
        "dashboard.view", "vehicles.view", "assignments.view", "fuel.view", "fuel.create",
        "maintenance.view", "inspections.view", "inspections.create", "documents.view",
        "documents.upload", "reservations.view", "reservations.create", "accidents.view",
    }),
    "finance": frozenset({
        "parts.view", "inventory.view", "vendors.view", "purchase_orders.view", "purchase_orders.approve", "technicians.view", "maintenance.manage_costs",
        "dashboard.view", "vehicles.view", "drivers.view", "fuel.view", "fuel.create", "fuel.edit",
        "fuel.view_cost", "maintenance.view", "documents.view", "reports.view", "reports.export",
        "accidents.view", "claims.manage",
    }),
    "viewer": frozenset({
        "dashboard.view", "vehicles.view", "drivers.view", "assignments.view", "fuel.view",
        "maintenance.view", "inspections.view", "documents.view", "reservations.view",
        "accidents.view",
    }),
}

DEFAULT_ROLE_NAMES = {
    "admin": "Admin",
    "fleet_manager": "Fleet Manager",
    "mechanic": "Mechanic",
    "driver": "Driver",
    "finance": "Finance",
    "viewer": "Viewer",
}


def active_role(db: Session | None, user: User) -> str:
    if isinstance(db, Session) and db.info.get("user_id") not in (None, user.id):
        return user.role
    return str(db.info.get("company_role", user.role)) if isinstance(db, Session) else user.role


def seed_authorization_defaults(db: Session, *, migrate_users: bool = True, commit: bool = True) -> None:
    permissions = {row.code: row for row in db.query(Permission).all()}
    for code, (module, description) in PERMISSION_CATALOG.items():
        if code not in permissions:
            row = Permission(code=code, name=code, module=module, description=description)
            db.add(row)
            permissions[code] = row
    db.flush()

    roles = {row.code: row for row in db.query(Role).all()}
    for code, name in DEFAULT_ROLE_NAMES.items():
        if code not in roles:
            row = Role(code=code, name=name, is_system=True, is_active=True)
            db.add(row)
            roles[code] = row
    db.flush()

    for role_code, permission_codes in DEFAULT_ROLE_PERMISSIONS.items():
        role = roles[role_code]
        existing = {row.permission.code for row in role.role_permissions}
        for code in permission_codes - existing:
            db.add(RolePermission(role_id=role.id, permission_id=permissions[code].id))

    if migrate_users:
        assigned_user_ids = {user_id for (user_id,) in db.query(UserRoleAssignment.user_id).all()}
        for user in db.query(User).all():
            role = roles.get(user.role)
            if role and user.id not in assigned_user_ids:
                db.add(UserRoleAssignment(user_id=user.id, role_id=role.id))
    if commit:
        db.commit()
    else:
        db.flush()


def _assignments(db: Session, user: User) -> list[UserRoleAssignment]:
    return (
        db.query(UserRoleAssignment)
        .options(joinedload(UserRoleAssignment.role).joinedload(Role.role_permissions).joinedload(RolePermission.permission))
        .filter(UserRoleAssignment.user_id == user.id, Role.is_active.is_(True))
        .join(UserRoleAssignment.role)
        .all()
    )


def get_user_permissions(db: Session | None, user: User) -> set[str]:
    if db is not None and "api_key_permissions" in db.info:
        return set(db.info["api_key_permissions"])
    if db is not None and user.id is not None:
        assignments = _assignments(db, user)
        if assignments:
            return {
                grant.permission.code
                for assignment in assignments
                for grant in assignment.role.role_permissions
            }
    return set(DEFAULT_ROLE_PERMISSIONS.get(active_role(db, user), frozenset()))


def has_permission(db: Session | None, user: User, permission: str) -> bool:
    return permission in get_user_permissions(db, user)


def require_permission(permission: str):
    from app.core.security import get_current_user

    def dependency(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        if not has_permission(db, current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "permission_denied", "message": "Insufficient permissions.", "params": {"permission": permission}},
            )
        return current_user

    return dependency


def require_any_permission(*permissions: str):
    from app.core.security import get_current_user

    def dependency(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> User:
        granted = get_user_permissions(db, current_user)
        if not granted.intersection(permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return current_user

    return dependency


@dataclass
class AuthorizationScope:
    unrestricted: bool = False
    location_ids: set[int] = field(default_factory=set)
    department_ids: set[int] = field(default_factory=set)
    cost_center_ids: set[int] = field(default_factory=set)
    own_records_only: bool = False


def authorization_scope(db: Session, user: User, permission: str) -> AuthorizationScope:
    assignments = _assignments(db, user)
    if not assignments:
        return AuthorizationScope(unrestricted=True)
    scope = AuthorizationScope()
    matching = []
    for assignment in assignments:
        codes = {grant.permission.code for grant in assignment.role.role_permissions}
        if permission in codes:
            matching.append(assignment)
    for assignment in matching:
        if not any((assignment.location_id, assignment.department_id, assignment.cost_center_id, assignment.own_records_only)):
            return AuthorizationScope(unrestricted=True)
        if assignment.location_id:
            scope.location_ids.add(assignment.location_id)
        if assignment.department_id:
            scope.department_ids.add(assignment.department_id)
        if assignment.cost_center_id:
            scope.cost_center_ids.add(assignment.cost_center_id)
        scope.own_records_only = scope.own_records_only or assignment.own_records_only
    return scope


def own_records_only(db: Session, user: User, permission: str) -> bool:
    scope = authorization_scope(db, user, permission)
    return not scope.unrestricted and scope.own_records_only
