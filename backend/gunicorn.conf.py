import os

bind = '0.0.0.0:8000'
workers = int(os.getenv('WEB_CONCURRENCY', '2'))
worker_class = 'uvicorn_worker.UvicornWorker'
timeout = 180
graceful_timeout = 180
keepalive = 5
# Only the dedicated proxy subnet may supply the client IP/protocol.
forwarded_allow_ips = os.getenv('FORWARDED_ALLOW_IPS', '127.0.0.1')
accesslog = None  # RequestTelemetryMiddleware emits redacted JSON access events.
errorlog = '-'

logconfig_dict = {
    'version': 1, 'disable_existing_loggers': False,
    'formatters': {'json': {'()': 'app.core.observability.JsonFormatter'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'json', 'stream': 'ext://sys.stdout'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {'gunicorn.error': {'handlers': ['console'], 'level': 'INFO', 'propagate': False}},
}
