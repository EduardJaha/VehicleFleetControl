import re
from enum import Enum
from typing import TypedDict


class RegistrationCountry(str, Enum):
    ALBANIA = "AL"
    KOSOVO = "XK"


class PlateValidationError(ValueError):
    """A user-facing validation error for an ordinary registration plate."""


class KosovoRegion(TypedDict):
    code: str
    name: str


class RegistrationCountryMetadata(TypedDict, total=False):
    code: str
    name: str
    placeholder: str
    example: str
    description: str
    helper_text: list[str]
    regions: list[KosovoRegion]


KOSOVO_REGIONS: tuple[KosovoRegion, ...] = (
    {"code": "01", "name": "Prishtina"},
    {"code": "02", "name": "Mitrovica"},
    {"code": "03", "name": "Peja"},
    {"code": "04", "name": "Prizren"},
    {"code": "05", "name": "Ferizaj"},
    {"code": "06", "name": "Gjilan"},
    {"code": "07", "name": "Gjakova"},
)
KOSOVO_DISALLOWED_SUFFIX_LETTERS = frozenset("TRVWXY")
_ALBANIA_PATTERN = re.compile(r"^[A-Z]{2}[0-9]{3}[A-Z]{2}$")
_KOSOVO_SHAPE = re.compile(r"^[0-9]{5}[A-Z]{2}$")
_SUPPORTED_INPUT = re.compile(r"^[A-Za-z0-9\s-]+$")


REGISTRATION_COUNTRIES: tuple[RegistrationCountryMetadata, ...] = (
    {
        "code": RegistrationCountry.ALBANIA.value,
        "name": "Albania",
        "placeholder": "AA 123 AA",
        "example": "AA 123 AA",
        "description": "Two letters, three digits, two letters",
        "helper_text": [
            "Format: AA 123 AA",
            "Two letters, three digits, two letters",
        ],
    },
    {
        "code": RegistrationCountry.KOSOVO.value,
        "name": "Kosovo",
        "placeholder": "01-123-AB",
        "example": "01-123-AB",
        "description": "Region code, three digits, two letters",
        "helper_text": [
            "Format: 01-123-AB",
            "Region codes: 01–07",
            "Number range: 101–999",
        ],
        "regions": list(KOSOVO_REGIONS),
    },
)


def coerce_registration_country(country: RegistrationCountry | str) -> RegistrationCountry:
    if isinstance(country, RegistrationCountry):
        return country
    try:
        return RegistrationCountry(str(country).strip().upper())
    except ValueError as exc:
        raise PlateValidationError("Only Albania and Kosovo are currently supported.") from exc


def registration_country_name(country: RegistrationCountry | str | None) -> str | None:
    if country is None:
        return None
    try:
        code = coerce_registration_country(country)
    except PlateValidationError:
        return None
    return "Albania" if code is RegistrationCountry.ALBANIA else "Kosovo"


def normalize_license_plate(
    country: RegistrationCountry | str,
    value: str,
) -> str:
    coerce_registration_country(country)
    text = value.strip()
    if not text:
        raise PlateValidationError("Enter a licence plate.")
    if not _SUPPORTED_INPUT.fullmatch(text):
        raise PlateValidationError("Licence plates may contain only letters, digits, spaces, and hyphens.")
    return re.sub(r"[\s-]", "", text).upper()


def format_license_plate(
    country: RegistrationCountry | str,
    normalized_value: str,
) -> str:
    code = coerce_registration_country(country)
    normalized = normalized_value.upper()
    if len(normalized) != 7:
        if code is RegistrationCountry.ALBANIA:
            raise PlateValidationError("Albania licence plates must use the format AA 123 AA.")
        raise PlateValidationError("Kosovo licence plates must use the format 01-123-AB.")
    if code is RegistrationCountry.ALBANIA:
        return f"{normalized[:2]} {normalized[2:5]} {normalized[5:]}"
    return f"{normalized[:2]}-{normalized[2:5]}-{normalized[5:]}"


def validate_license_plate(
    country: RegistrationCountry | str,
    value: str,
) -> str:
    code = coerce_registration_country(country)
    normalized = normalize_license_plate(code, value)
    if code is RegistrationCountry.ALBANIA:
        if not _ALBANIA_PATTERN.fullmatch(normalized):
            raise PlateValidationError(
                "Albania licence plates must use the format AA 123 AA. "
                "Enter two letters, three digits, and two letters."
            )
        return format_license_plate(code, normalized)

    if not _KOSOVO_SHAPE.fullmatch(normalized):
        raise PlateValidationError("Kosovo licence plates must use the format 01-123-AB.")
    region = normalized[:2]
    if region not in {item["code"] for item in KOSOVO_REGIONS}:
        raise PlateValidationError("Kosovo region code must be between 01 and 07.")
    number = int(normalized[2:5])
    if not 101 <= number <= 999:
        raise PlateValidationError("Kosovo plate number must be between 101 and 999.")
    if any(letter in KOSOVO_DISALLOWED_SUFFIX_LETTERS for letter in normalized[5:]):
        raise PlateValidationError(
            "The selected Kosovo plate contains a letter that is not allowed for an ordinary plate."
        )
    return format_license_plate(code, normalized)


def detect_registration_country(value: str) -> RegistrationCountry | None:
    for country in RegistrationCountry:
        try:
            validate_license_plate(country, value)
            return country
        except PlateValidationError:
            continue
    return None


def normalized_plate_search(value: str | None) -> str:
    """Normalize a partial plate search without treating it as a complete plate."""
    text = (value or "").strip()
    if not text:
        return ""
    if not _SUPPORTED_INPUT.fullmatch(text):
        return text.upper()
    return re.sub(r"[\s-]", "", text).upper()
