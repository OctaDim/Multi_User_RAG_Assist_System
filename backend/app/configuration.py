"""Installation configuration; inference dependencies must not be imported here."""
import math
import os
from pathlib import Path
import tomllib
from urllib.parse import urlsplit

from app.resources import resource_path


class ConfigurationError(ValueError):
    pass


def _merge(defaults, overrides, prefix=''):
    for key, value in overrides.items():
        name = f'{prefix}{key}'
        if key not in defaults:
            raise ConfigurationError(f'Unknown configuration key: {name}')
        if isinstance(defaults[key], dict):
            if not isinstance(value, dict):
                raise ConfigurationError(f'Expected a section: {name}')
            _merge(defaults[key], value, name + '.')
        else:
            defaults[key] = value


def load_service_config(local_path=None):
    directory = resource_path('config')
    if local_path is None and os.environ.get('RAG_SERVICE_CONFIG'):
        local_path = Path(os.environ['RAG_SERVICE_CONFIG'])
    try:
        with (directory / 'service.toml').open('rb') as stream:
            config = tomllib.load(stream)
        local = Path(local_path) if local_path is not None else directory / 'service.local.toml'
        if local_path is not None or local.exists():
            with local.open('rb') as stream:
                _merge(config, tomllib.load(stream))
        return config
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError('Cannot read service configuration; check TOML files and --config path') from error


def section_path(value):
    path = Path(value).expanduser()
    return Path(os.path.abspath(path if path.is_absolute() else resource_path('config').parent / path))


def _number(value, key, *, integer=False, maximum=None):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or value <= 0:
        raise ConfigurationError(f'Invalid configuration key: {key}')
    if maximum is not None and value > maximum:
        raise ConfigurationError(f'Invalid configuration key: {key}')


def _string(value, key, *, required=True):
    if not isinstance(value, str) or '\x00' in value or (required and not value.strip()):
        raise ConfigurationError(f'Missing or invalid configuration key: {key}')


def launch_environment(config):
    """Validate before starting children; return only the component environment."""
    _string(config['api']['host'], 'api.host')
    _number(config['api']['port'], 'api.port', integer=True, maximum=65535)
    origin = config['api']['frontend_origin']
    _string(origin, 'api.frontend_origin')
    parsed = urlsplit(origin)
    try:
        origin_port = parsed.port
    except ValueError:
        raise ConfigurationError('Invalid configuration key: api.frontend_origin') from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or any(char.isspace() for char in origin) or origin_port == 0):
        raise ConfigurationError('Invalid configuration key: api.frontend_origin')
    for section, keys in {
        'database': ('ready_timeout_seconds', 'retry_seconds', 'connect_timeout_seconds'),
        'supervisor': ('poll_seconds', 'shutdown_timeout_seconds', 'kill_timeout_seconds'),
        'smtp': ('timeout_seconds',),
    }.items():
        for key in keys:
            _number(config[section][key], f'{section}.{key}', integer=key == 'connect_timeout_seconds')
    _string(config['database']['dsn'], 'database.dsn')
    for key in ('generation', 'embedding', 'ocr'):
        _string(config['models'][key], f'models.{key}')
    for section, key in (('launcher', 'python'), ('storage', 'originals')):
        _string(config[section][key], f'{section}.{key}')
    _string(config['models']['handwriting'], 'models.handwriting', required=False)
    smtp = config['smtp']
    for key in ('host', 'sender', 'username', 'password'):
        _string(smtp[key], f'smtp.{key}', required=False)
    _number(smtp['port'], 'smtp.port', integer=True, maximum=65535)
    if smtp['security'] not in smtp['ports'] or smtp['security'] not in ('starttls', 'ssl', 'plain'):
        raise ConfigurationError('Invalid configuration key: smtp.security')
    if bool(smtp['username']) != bool(smtp['password']):
        raise ConfigurationError('smtp.username and smtp.password must be configured together')
    if bool(smtp['host']) != bool(smtp['sender']) or '\n' in smtp['sender'] or '\r' in smtp['sender']:
        raise ConfigurationError('Configure smtp.host and smtp.sender together')
    if smtp['security'] == 'plain' and smtp['host'] not in ('', 'localhost', '127.0.0.1', '::1'):
        raise ConfigurationError('smtp.security requires TLS for a remote server')
    environment = {
        'RAG_DATABASE_URL': config['database']['dsn'],
        'RAG_FRONTEND_ORIGIN': origin.rstrip('/'),
        'RAG_MODEL_PATH': str(section_path(config['models']['generation'])),
        'RAG_E5_DIR': str(section_path(config['models']['embedding'])),
        'RAG_OCR_DIR': str(section_path(config['models']['ocr'])),
        'RAG_OCR_MODEL_PATH': str(section_path(config['models']['handwriting'] or config['models']['generation'])),
        'RAG_ORIGINALS_DIR': str(section_path(config['storage']['originals'])),
    }
    for key, variable in {'host': 'HOST', 'port': 'PORT', 'sender': 'FROM', 'security': 'SECURITY',
                          'username': 'USERNAME', 'password': 'PASSWORD', 'timeout_seconds': 'TIMEOUT'}.items():
        environment['RAG_SMTP_' + variable] = str(smtp[key])
    return environment
