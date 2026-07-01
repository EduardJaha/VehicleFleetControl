from fastapi import APIRouter
from app.api.v1.endpoints import accidents, auth, dashboard, drivers, fuel, inspections, papers, reservations, services, vehicles

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(vehicles.router, prefix="/vehicles", tags=["vehicles"])
api_router.include_router(drivers.router, prefix="/drivers", tags=["drivers"])
api_router.include_router(inspections.router, prefix="/inspections", tags=["inspections"])
api_router.include_router(services.router, prefix="/services", tags=["services"])
api_router.include_router(fuel.router, prefix="/fuel", tags=["fuel"])
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
api_router.include_router(accidents.router, prefix="/accidents", tags=["accidents"])
api_router.include_router(reservations.router, prefix="/reservations", tags=["reservations"])
