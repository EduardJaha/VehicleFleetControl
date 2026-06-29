from fastapi import APIRouter
from app.api.v1.endpoints import accidents, dashboard, fuel, papers, reservations, services, vehicles

api_router = APIRouter()
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(vehicles.router, prefix="/vehicles", tags=["vehicles"])
api_router.include_router(services.router, prefix="/services", tags=["services"])
api_router.include_router(fuel.router, prefix="/fuel", tags=["fuel"])
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
api_router.include_router(accidents.router, prefix="/accidents", tags=["accidents"])
api_router.include_router(reservations.router, prefix="/reservations", tags=["reservations"])
