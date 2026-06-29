from datetime import datetime
from fastapi import HTTPException

DATE_FORMAT = "%d-%m-%Y"


def parse_date(value: str | None, field_name: str = "date") -> datetime:
    try:
        return datetime.strptime(value or "", DATE_FORMAT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be dd-MM-yyyy.") from exc


def format_date(value: datetime | None) -> str | None:
    return value.strftime(DATE_FORMAT) if value else None
