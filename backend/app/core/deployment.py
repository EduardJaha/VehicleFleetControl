"""Fail closed for staging/production, independently of local/test settings."""
from urllib.parse import urlsplit
from app.core.config import get_settings


def validate_deployment(settings=None):
    settings = settings or get_settings()
    if settings.environment not in {'production', 'staging'}:
        return
    if not settings.database_url.startswith('postgresql+psycopg://'):
        raise ValueError('Staging/production require PostgreSQL.')
    if settings.storage_provider != 's3':
        raise ValueError('Staging/production require durable S3 object storage.')
    if settings.s3_endpoint and urlsplit(settings.s3_endpoint).scheme != 'https':
        raise ValueError('Staging/production S3_ENDPOINT must use HTTPS.')
    if settings.frontend_url not in settings.cors_origins:
        raise ValueError('FRONTEND_URL must match a trusted HTTPS origin.')
    if settings.environment == 'production' and settings.email_backend != 'smtp':
        raise ValueError('Production requires an SMTP delivery configuration.')
    if settings.email_backend == 'smtp' and not settings.smtp_use_tls:
        raise ValueError('Staging/production SMTP must use TLS.')


if __name__ == '__main__':
    validate_deployment()
    print('Deployment configuration valid.')
