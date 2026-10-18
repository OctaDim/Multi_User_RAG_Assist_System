"""Run the standalone public frontend using only Python's standard library."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit('Frontend requires Python 3.11 or newer; run with python3.11+ before reading TOML')

import argparse
from functools import partial
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import math
from pathlib import Path
import signal
import tomllib
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent


def load_config(local_path=None):
    with (ROOT / 'config/service.toml').open('rb') as stream:
        config = tomllib.load(stream)
    local = Path(local_path) if local_path is not None else ROOT / 'config/service.local.toml'
    if local_path is not None or local.exists():
        with local.open('rb') as stream:
            overrides = tomllib.load(stream)
        for section, values in overrides.items():
            if section not in config or not isinstance(values, dict):
                raise ValueError(f'Unknown configuration section: {section}')
            for key, value in values.items():
                if key not in config[section]:
                    raise ValueError(f'Unknown configuration key: {section}.{key}')
                config[section][key] = value
    return config


def validate_config(config):
    server = config['server']
    if not isinstance(server['host'], str) or not server['host'].strip() or '\x00' in server['host']:
        raise ValueError('Invalid configuration key: server.host')
    if type(server['port']) is not int or not 0 <= server['port'] <= 65535:
        raise ValueError('Invalid configuration key: server.port')
    if (type(server['poll_seconds']) not in (int, float) or not math.isfinite(server['poll_seconds'])
            or server['poll_seconds'] <= 0):
        raise ValueError('Invalid configuration key: server.poll_seconds')
    origin = config['api']['origin']
    if not isinstance(origin, str):
        raise ValueError('Invalid configuration key: api.origin')
    parsed = urlsplit(origin)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('Invalid configuration key: api.origin') from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or any(char.isspace() for char in origin) or port == 0):
        raise ValueError('Invalid configuration key: api.origin')
    if type(config['client']['reconnect_ms']) is not int or not 0 < config['client']['reconnect_ms'] <= 2**31-1:
        raise ValueError('Invalid configuration key: client.reconnect_ms')
    if type(config['client']['request_timeout_ms']) is not int or not 0 < config['client']['request_timeout_ms'] <= 2**31-1:
        raise ValueError('Invalid configuration key: client.request_timeout_ms')
    for key in ('composer_rows', 'correction_rows', 'short_id_chars'):
        if type(config['ui'][key]) is not int or config['ui'][key] <= 0:
            raise ValueError(f'Invalid configuration key: ui.{key}')
        if key.endswith('_rows') and config['ui'][key] > 2**32-1:
            raise ValueError(f'Invalid configuration key: ui.{key}')


class PublicFiles(BaseHTTPRequestHandler):
    def __init__(self, *args, config, **kwargs):
        self.config = config
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.respond(head=False)

    def do_HEAD(self):
        self.respond(head=True)

    def respond(self, *, head):
        try:
            path = unquote(urlsplit(self.path).path)
            if path in ('/', '/index.html'):
                text = (ROOT / 'index.html').read_text(encoding='utf-8')
                body = text.replace('__RAG_API_ORIGIN__', escape(self.config['api']['origin'].rstrip('/'), quote=True))
                body = body.replace('__RAG_RECONNECT_MS__', str(self.config['client']['reconnect_ms']))
                body = body.replace('__RAG_REQUEST_TIMEOUT_MS__', str(self.config['client']['request_timeout_ms']))
                for key in ('composer_rows', 'correction_rows', 'short_id_chars'):
                    body = body.replace(f'__RAG_{key.upper()}__', str(self.config['ui'][key]))
                body = body.encode('utf-8')
                content_type = 'text/html; charset=utf-8'
            elif path.startswith('/src/') and '..' not in path.split('/') and '\\' not in path:
                target = (ROOT / path.lstrip('/')).resolve()
                public = (ROOT / 'src').resolve()
                # A resolved path must remain in src, and no link may grant access
                # to an unintended file, including a config placed inside src.
                relative = Path(path.lstrip('/'))
                if (not target.is_relative_to(public) or any(part.is_symlink() for part in
                        [ROOT / relative, *(ROOT / relative).parents]) or not target.is_file()):
                    raise FileNotFoundError
                content_type = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'}[target.suffix]
                body = target.read_bytes()
            else:
                raise FileNotFoundError
        except (OSError, ValueError, KeyError):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if not head:
            self.wfile.write(body)


def create_server(config):
    validate_config(config)
    # AF_INET6 is selected for an explicit IPv6 bind address.
    if ':' in config['server']['host']:
        import socket
        class Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6
    else:
        Server = ThreadingHTTPServer
    return Server((config['server']['host'], config['server']['port']), partial(PublicFiles, config=config))


def main():
    parser = argparse.ArgumentParser(description='Run the RAG frontend')
    parser.add_argument('--config', type=Path, help='Local TOML overrides instead of config/service.local.toml')
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        with create_server(config) as server:
            signal.signal(signal.SIGTERM, signal.default_int_handler)
            host, port = server.server_address[:2]
            display_host = f'[{host}]' if ':' in host else host
            print(f'Frontend listening on http://{display_host}:{port}', flush=True)
            try:
                server.serve_forever(poll_interval=config['server']['poll_seconds'])
            except KeyboardInterrupt:
                pass
        return 0
    except (OSError, ValueError, KeyError):
        print('Frontend startup failed: check configuration keys, TOML syntax and bind address/port', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
