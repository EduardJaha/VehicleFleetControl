from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.i18n import request_language, translate


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _origin_from_referer(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


class HttpSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        response = None
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is None:
                referer = request.headers.get("referer")
                origin = _origin_from_referer(referer) if referer else None
            cookie_flow = settings.auth_cookie_name in request.cookies or request.url.path.rstrip("/") in {
                f"{settings.api_v1_prefix}/auth/login", f"{settings.api_v1_prefix}/auth/register",
            }
            # Fail closed for cookie mutations and login CSRF, including missing
            # or null origins. Header-only legacy API clients remain supported.
            if ((cookie_flow and origin is None) or
                    (origin is not None and origin not in settings.cors_origins)):
                language = request_language(request)
                response = JSONResponse(
                    status_code=403,
                    content={"code": "csrf_failed", "message": translate("csrf_failed", language), "params": {}},
                )

        if response is None:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        if request.url.path.startswith(settings.api_v1_prefix):
            response.headers["Cache-Control"] = "private, no-store"
        # Uvicorn must normalize the scheme using only explicitly trusted proxies.
        if settings.environment.lower() == "production" and request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
