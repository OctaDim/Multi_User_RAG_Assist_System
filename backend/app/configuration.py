"""Installation configuration; inference dependencies must not be imported here."""
import math
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from string import Formatter
import tomllib
from urllib.parse import urlsplit

from app.resources import resource_path


class ConfigurationError(ValueError):
    pass


def load_settings(name):
    """Read a validated process snapshot; local profiles share the service owner.

    Return a copy so component or administrative merges cannot corrupt defaults.
    Changes to files require restarting the backend processes.
    """
    if name not in ('policy', 'runtime', 'ocr', 'documents', 'prompts'):
        raise ConfigurationError('Unknown application configuration profile')
    selected = os.environ.get('RAG_SERVICE_CONFIG')
    directory = Path(selected).absolute().parent if selected else resource_path('config')
    return deepcopy(_settings_snapshot(name, str(directory)))


@lru_cache(maxsize=32)
def _settings_snapshot(name, directory):
    try:
        with (resource_path('config') / f'{name}.toml').open('rb') as stream:
            defaults = tomllib.load(stream)
        config = deepcopy(defaults)
        local = Path(directory) / f'{name}.local.toml'
        if local.exists():
            with local.open('rb') as stream:
                _merge(config, tomllib.load(stream))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f'Cannot read {name} configuration; check TOML files') from error
    _validate_shape(config, defaults)
    _validate_settings(name, config)
    return config


def _validate_shape(value, default, key=''):
    if isinstance(default, dict):
        if not isinstance(value, dict) or value.keys() != default.keys():
            raise ConfigurationError(f'Invalid configuration key: {key}')
        for field in default:
            _validate_shape(value[field], default[field], f'{key}.{field}'.lstrip('.'))
    elif isinstance(default, list):
        if not isinstance(value, list):
            raise ConfigurationError(f'Invalid configuration key: {key}')
        for item in value:
            _validate_shape(item, default[0], key)
    elif type(default) in (int, float):
        if type(value) not in ((int,) if type(default) is int else (int, float)) or not math.isfinite(value):
            raise ConfigurationError(f'Invalid configuration key: {key}')
    elif type(value) is not type(default) or (isinstance(value, str) and '\x00' in value):
        raise ConfigurationError(f'Invalid configuration key: {key}')


def _require(condition, key):
    if not condition:
        raise ConfigurationError(f'Invalid configuration key: {key}')


def _positive_sections(config, sections, *, zero=()):
    for section in sections:
        for key, value in config[section].items():
            if type(value) in (int, float):
                full = f'{section}.{key}'
                _require(value >= 0 if full in zero else value > 0, full)


def _template(value, fields, key):
    try:
        parsed = list(Formatter().parse(value))
        actual = {field for _, field, _, _ in parsed if field is not None}
        valid = actual == set(fields) and all(not spec and not conversion for _, _, spec, conversion in parsed)
    except ValueError:
        valid = False
    _require(valid, key)


def _native_bounds(config, section, unsigned=(), signed=()):
    for keys, maximum in ((unsigned, 2**32-1), (signed, 2**31-1)):
        for key in keys:
            _number(config[section][key], f'{section}.{key}', integer=True, maximum=maximum)


def _validate_settings(name, config):
    if name == 'policy':
        _positive_sections(config, ('inputs', 'security', 'accounts', 'tabs', 'generation', 'ingestion'))
        inputs, security, tabs = config['inputs'], config['security'], config['tabs']
        for key in inputs:
            # Public lengths must fit the browser's signed WebIDL long fields.
            _number(inputs[key], f'inputs.{key}', integer=True, maximum=2**31-1)
        for field in ('email', 'password'):
            _require(inputs[field + '_min'] <= inputs[field + '_max'], f'inputs.{field}')
        _require(inputs['email_max'] <= 254, 'inputs.email_max')
        _require(tabs['heartbeat_seconds'] < tabs['ack_timeout_seconds'], 'tabs.heartbeat_seconds')
        _require(tabs['heartbeat_seconds'] + tabs['poll_seconds'] < tabs['ack_timeout_seconds'], 'tabs.poll_seconds')
        gen = config['generation']
        _require(gen['renewal_poll_seconds'] < gen['lease_seconds'], 'generation.renewal_poll_seconds')
        _require((security['token_bytes'] * 8 + 5) // 6 <= inputs['token_max'], 'inputs.token_max')
        profiles = [dict(n=security['scrypt_n'], r=security['scrypt_r'], p=security['scrypt_p'],
                         dklen=security['scrypt_dklen'], salt_bytes=security['salt_bytes'])] + security['legacy_scrypt']
        _require(security['scrypt_maxmem'] < 2**31-1, 'security.scrypt_maxmem')
        for profile in profiles:
            _require(all(value > 0 for value in profile.values()), 'security.legacy_scrypt')
            n = profile['n']
            _require(n > 1 and n & (n-1) == 0, 'security.scrypt_n')
            _require(128 * profile['r'] * (n + profile['p'] + 2) < security['scrypt_maxmem'], 'security.scrypt_maxmem')
        _require('\n' not in config['mail']['subject'] and '\r' not in config['mail']['subject'], 'mail.subject')
        _template(config['mail']['verification_template'], ('origin', 'token', 'expiry'), 'mail.verification_template')
    elif name == 'runtime':
        _positive_sections(config, ('generation', 'embedding', 'native'))
        _native_bounds(config, 'generation', ('n_ctx',), ('n_threads', 'n_threads_batch'))
        _native_bounds(config, 'native', ('prefill_batch',), ('token_capacity_padding', 'piece_capacity'))
        # The existing citation protocol has two decimal digits.
        _number(config['rag']['retrieval_limit'], 'rag.retrieval_limit', integer=True, maximum=99)
        _number(config['rag']['response_reserve'], 'rag.response_reserve', integer=True)
        _require(-1 <= config['rag']['min_similarity'] <= 1, 'rag.min_similarity')
        _require(config['rag']['response_reserve'] < config['generation']['n_ctx'], 'rag.response_reserve')
        _require(config['embedding']['max_length'] <= 512, 'embedding.max_length')
        _require(config['native']['prefill_batch'] <= config['generation']['n_ctx'], 'native.prefill_batch')
    elif name == 'ocr':
        _positive_sections(config, ('execution', 'detector', 'geometry', 'fragments', 'decoding'),
                           zero=('geometry.padding', 'fragments.edge_tolerance', 'decoding.max_tokens'))
        for section, fields in {'detector': ('confidence',), 'geometry': ('region_union_overlap', 'component_max_density'),
                                'fragments': ('duplicate_min_overlap', 'duplicate_max_overlap', 'spanning_width')}.items():
            for key in fields:
                _require(0 < config[section][key] <= 1, f'{section}.{key}')
        _require(config['geometry']['foreground_threshold'] <= 255, 'geometry.foreground_threshold')
        _require(2*config['fragments']['overlap'] < config['fragments']['limit'], 'fragments.overlap')
        _require(config['execution']['n_ubatch'] <= config['execution']['n_batch'], 'execution.n_ubatch')
        _require(config['execution']['n_batch'] <= min(config[k]['n_ctx'] for k in ('printed', 'handwriting')), 'execution.n_batch')
        _native_bounds(config, 'execution', ('n_batch', 'n_ubatch'), ('n_threads', 'n_threads_batch'))
        _native_bounds(config, 'detector', signed=('intra_op_num_threads', 'inter_op_num_threads'))
        for profile in ('printed', 'handwriting'):
            _native_bounds(config, profile, ('n_ctx',))
    elif name == 'documents':
        _positive_sections(config, ('limits',))
    elif name == 'prompts':
        for section in config.values():
            for key, value in section.items():
                _string(value, key)
        _template(config['rag']['template'], ('system', 'prior', 'excerpts', 'question', 'markers'), 'rag.template')


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
    if type(config['api']['allow_loopback_origins']) is not bool:
        raise ConfigurationError('Invalid configuration key: api.allow_loopback_origins')
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
        'RAG_ALLOW_LOOPBACK_ORIGINS': '1' if config['api']['allow_loopback_origins'] else '0',
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
