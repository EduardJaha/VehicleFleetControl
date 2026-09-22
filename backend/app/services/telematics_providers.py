"""Adapter boundary; no commercial provider API is implemented or contacted."""
import os
from typing import Protocol
from app.telematics_schemas import EventBatch


class ProviderAdapter(Protocol):
    def normalize(self, body: bytes) -> EventBatch:
        """Translate an authenticated provider delivery to canonical events."""
        ...


class GenericAdapter:
    def normalize(self, body: bytes) -> EventBatch:
        return EventBatch.model_validate_json(body)


ADAPTERS: dict[str, ProviderAdapter] = {"generic": GenericAdapter()}


def resolve_credentials(reference: str | None) -> str | None:
    # Only an operator-provisioned, namespaced environment reference is accepted.
    # No secret values, arbitrary paths, URLs or external secret-store requests.
    import re
    if reference and re.fullmatch(r"env:TELEMATICS_[A-Z0-9_]{1,100}", reference):
        value = os.environ.get(reference[4:])
        return value if value and len(value) >= 32 else None
    return None
