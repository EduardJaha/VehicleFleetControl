from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.services.license_plates import REGISTRATION_COUNTRIES


router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/countries")
def registration_countries():
    return REGISTRATION_COUNTRIES
