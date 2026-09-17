import json
import logging
from types import SimpleNamespace

import pytest

from app.core import observability


@pytest.mark.parametrize('formatter', [observability.JsonFormatter, observability.ConsoleFormatter])
def test_startup_messages_are_readable_without_formatting_arguments(formatter):
    record = logging.LogRecord('uvicorn.error', logging.INFO, '', 1,
                               'Started server process [%d]', ('token=secret',), None)
    output = formatter().format(record)
    assert 'Started server process.' in output
    assert 'secret' not in output
    record.msg = 'Application startup complete.'
    assert 'Application startup complete.' in formatter().format(record)


@pytest.mark.parametrize('formatter', [observability.JsonFormatter, observability.ConsoleFormatter])
def test_unknown_messages_and_exception_values_remain_private(formatter):
    record = logging.LogRecord('uvicorn.error', logging.ERROR, '', 1,
                               'password=secret %s', ('token=hidden',),
                               (ValueError, ValueError('private-value'), None))
    output = formatter().format(record)
    assert 'ValueError' in output
    for sensitive in ('secret', 'hidden', 'private-value'):
        assert sensitive not in output


def test_console_request_keeps_correlation_without_null_fields():
    record = logging.LogRecord('fleet.request', logging.INFO, '', 1, 'request', (), None)
    record.event = 'http_request'
    record.route = '/vehicles/{id}'
    record.status_code = 200
    record.duration = 4.5
    record.request_id = 'request-123'
    output = observability.ConsoleFormatter().format(record)
    assert output == 'INFO:     /vehicles/{id} 200 (4.5 ms) request_id=request-123'


@pytest.mark.parametrize('environment', ['development', 'test', 'staging', 'production'])
def test_environment_selects_log_format(environment, monkeypatch, capsys):
    # Restore global logger state after exercising the real configuration.
    for name in ('', 'uvicorn', 'uvicorn.error', 'uvicorn.access', 'gunicorn.error', 'gunicorn.access'):
        logger = logging.getLogger(name)
        for attribute in ('handlers', 'level', 'propagate'):
            monkeypatch.setattr(logger, attribute, getattr(logger, attribute))
    monkeypatch.setattr(observability, 'get_settings', lambda: SimpleNamespace(environment=environment))
    observability.configure_logging()
    logging.getLogger('uvicorn.error').info('Application startup complete.')
    output = capsys.readouterr().out.strip()
    if environment in {'staging', 'production'}:
        payload = json.loads(output)
        assert payload['message'] == 'Application startup complete.'
        assert payload['level'] == 'INFO'
        assert payload['request_id'] is None
    else:
        assert output == 'INFO:     Application startup complete.'
