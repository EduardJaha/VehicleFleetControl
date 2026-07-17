import re


WHITESPACE_RE = re.compile(r"\s+")


def clean_catalog_name(value: str) -> str:
    """Trim catalog display names without removing meaningful punctuation."""
    return WHITESPACE_RE.sub(" ", value.strip())


def normalize_catalog_name(value: str) -> str:
    """Return the case-insensitive key used by catalog uniqueness checks."""
    return clean_catalog_name(value).casefold()
