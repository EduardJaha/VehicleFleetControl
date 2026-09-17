"""Allowlisted structured telemetry; no request bodies, queries, headers or exception text."""
import json
import logging
import re
import sys
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.core.config import get_settings


# Only known server lifecycle templates may become messages. Never format their
# arguments: an arbitrary server/SDK log can contain URLs, credentials or data.
SERVER_MESSAGES = {
    'Started server process [%d]': 'Started server process.',
    'Finished server process [%d]': 'Finished server process.',
    'Waiting for application startup.': 'Waiting for application startup.',
    'Application startup complete.': 'Application startup complete.',
    'Application startup failed. Exiting.': 'Application startup failed. Exiting.',
    'Waiting for application shutdown.': 'Waiting for application shutdown.',
    'Application shutdown complete.': 'Application shutdown complete.',
    'Application shutdown failed. Exiting.': 'Application shutdown failed. Exiting.',
    'Shutting down': 'Shutting down.',
    'Uvicorn running on %s://%s:%d (Press CTRL+C to quit)': 'Uvicorn is listening (Press CTRL+C to quit).',
}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        fields = {key: getattr(record, key, None) for key in
                  ('request_id', 'company_id', 'user_id', 'route', 'duration', 'status_code')}
        fields.update(timestamp=datetime.now(timezone.utc).isoformat(), level=record.levelname,
                      event=getattr(record, 'event', record.name))
        if record.name == 'uvicorn.error' and isinstance(record.msg, str):
            message = SERVER_MESSAGES.get(record.msg)
            if message:
                fields['message'] = message
        if getattr(record, 'exception_type', None):
            fields['exception_type'] = record.exception_type
        if record.exc_info:
            fields['exception_type'] = record.exc_info[0].__name__
        return json.dumps(fields)


class ConsoleFormatter(JsonFormatter):
    """Readable local output using exactly the same safe fields as production."""

    def format(self, record):
        fields = json.loads(super().format(record))
        message = fields.get('message', fields['event'])
        if fields['event'] == 'http_request':
            message = f"{fields['route']} {fields['status_code']} ({fields['duration']} ms)"
        context = ' '.join(f'{key}={fields[key]}' for key in
                           ('request_id', 'company_id', 'user_id', 'exception_type')
                           if fields.get(key) is not None)
        return f"{fields['level']}:     {message}" + (f' {context}' if context else '')


def configure_logging():
    handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter if get_settings().environment in {'staging', 'production'} else ConsoleFormatter
    handler.setFormatter(formatter())
    logging.getLogger().handlers = [handler]
    logging.getLogger().setLevel(logging.INFO)
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access', 'gunicorn.error', 'gunicorn.access'):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


class ErrorMonitor:
    def capture(self, exc, context):
        pass


class SentryErrorMonitor(ErrorMonitor):
    def __init__(self, settings):
        import sentry_sdk
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment,
                        release=settings.release, default_integrations=False,
                        auto_enabling_integrations=False, send_default_pii=False)

    def capture(self, exc, context):
        import sentry_sdk
        # Never send exception values, locals, request objects or authentication data.
        sentry_sdk.capture_event({'level': 'error', 'message': type(exc).__name__, 'tags': context})


def error_monitor():
    settings = get_settings()
    return SentryErrorMonitor(settings) if settings.error_monitoring_provider == 'sentry' else ErrorMonitor()


class RequestTelemetryMiddleware:
    def __init__(self, app):
        self.app = app
        self.monitor = error_monitor()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        supplied = dict(scope.get('headers', [])).get(b'x-request-id', b'').decode('ascii', errors='ignore')
        request_id = supplied if re.fullmatch(r'[a-zA-Z0-9_-]{8,64}', supplied) else uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        started = perf_counter()
        status = 500
        response_started = False
        exception_type = None

        async def correlated_send(message):
            nonlocal status, response_started
            if message['type'] == 'http.response.start':
                response_started = True
                status = message['status']
                message['headers'] = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'x-request-id']
                message['headers'].append((b'x-request-id', request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, correlated_send)
        except Exception as exc:
            exception_type = type(exc).__name__
            try:
                self.monitor.capture(exc, {'request_id': request_id})
            except Exception:
                pass  # Monitoring failures must not change the application response.
            # A safe generic response avoids logging raw exception values via Uvicorn.
            if not response_started:
                from starlette.responses import JSONResponse
                await JSONResponse({'detail': 'Internal server error.'}, status_code=500)(scope, receive, correlated_send)
            else:
                raise
        finally:
            state = scope['state']
            log = logging.getLogger('fleet.request')
            emit = log.error if status >= 500 or exception_type else log.info
            emit('request', extra={
                'exception_type': exception_type,
                'event': 'http_request', 'request_id': request_id,
                'company_id': state.get('company_id'), 'user_id': state.get('user_id'),
                'route': getattr(scope.get('route'), 'path', 'unmatched'),
                'duration': round((perf_counter() - started) * 1000, 2), 'status_code': status,
            })
