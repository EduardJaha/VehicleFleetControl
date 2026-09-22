from fastapi import APIRouter
from app.api.v1.endpoints import accidents, admin, audit_logs, auth, bulk_actions, compliance, dashboard, drivers, files, fuel, imports, inspections, maintenance, maintenance_supply, notifications, papers, reports, reservations, services, vehicle_assignments, vehicle_catalog, vehicle_registration, vehicles, work_orders

from app.api.v1.endpoints import mobile

api_router = APIRouter()
api_router.include_router(mobile.router, prefix="/mobile", tags=["mobile"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["administration"])
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit logs"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
api_router.include_router(bulk_actions.router, prefix="/bulk-actions", tags=["bulk actions"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(vehicles.router, prefix="/vehicles", tags=["vehicles"])
api_router.include_router(vehicle_registration.router, prefix="/vehicle-registration", tags=["vehicle registration"])
api_router.include_router(vehicle_catalog.router, prefix="/vehicle-catalog", tags=["vehicle catalog"])
api_router.include_router(drivers.router, prefix="/drivers", tags=["drivers"])
api_router.include_router(vehicle_assignments.router, prefix="/vehicle-assignments", tags=["vehicle assignments"])
api_router.include_router(inspections.router, prefix="/inspections", tags=["inspections"])
api_router.include_router(work_orders.router, prefix="/work-orders", tags=["work-orders"])
api_router.include_router(maintenance.router, prefix="/maintenance", tags=["maintenance"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(services.router, prefix="/services", tags=["services"])
api_router.include_router(fuel.router, prefix="/fuel", tags=["fuel"])
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
api_router.include_router(compliance.router, prefix="/compliance", tags=["document compliance"])
api_router.include_router(accidents.router, prefix="/accidents", tags=["accidents"])
api_router.include_router(reservations.router, prefix="/reservations", tags=["reservations"])

api_router.include_router(maintenance_supply.router, tags=["maintenance supply"])

from app.api.v1.endpoints import service_programs
api_router.include_router(service_programs.router, prefix="/maintenance/programs", tags=["maintenance programs"])

from app.api.v1.endpoints import inspection_templates
api_router.include_router(inspection_templates.router, prefix="/inspection-templates", tags=["inspection templates"])

from app.api.v1.endpoints import integrations
api_router.include_router(integrations.router, prefix="/admin/integrations", tags=["integrations"])

from app.api.v1.endpoints import telematics
api_router.include_router(telematics.router, prefix="/telematics", tags=["telematics"])
