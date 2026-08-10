from fastapi import APIRouter, Depends, Request

from app.core.i18n import request_language
from app.core.authorization import require_permission
from app.services.license_plates import REGISTRATION_COUNTRIES


router = APIRouter(dependencies=[Depends(require_permission("vehicles.view"))])


@router.get("/countries")
def registration_countries(request: Request):
    if request_language(request) == "sq":
        return (
            {**REGISTRATION_COUNTRIES[0], "name": "Shqipëria", "description": "Dy shkronja, tre shifra, dy shkronja", "helper_text": ["Formati: AA 123 AA", "Dy shkronja, tre shifra, dy shkronja"]},
            {**REGISTRATION_COUNTRIES[1], "name": "Kosova", "description": "Kodi i rajonit, tre shifra, dy shkronja", "helper_text": ["Formati: 01-123-AB", "Kodet e rajoneve: 01–07", "Diapazoni i numrave: 101–999"]},
        )
    return REGISTRATION_COUNTRIES
