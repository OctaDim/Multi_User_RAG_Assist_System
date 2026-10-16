"""One entrypoint for the complete backend, including its prepared virtualenv."""
import argparse
import os
from pathlib import Path
import sys

from app.configuration import ConfigurationError, launch_environment, load_service_config, section_path


def main():
    parser = argparse.ArgumentParser(description='Run the RAG API, document worker and generation service')
    parser.add_argument('--config', type=Path, help='Local TOML overrides instead of config/service.local.toml')
    args = parser.parse_args()
    try:
        selected = args.config if args.config is not None else os.environ.get('RAG_SERVICE_CONFIG')
        selected = Path(os.path.abspath(Path(selected).expanduser())) if selected else None
        config = load_service_config(selected)
        environment = launch_environment(config)
        environment['RAG_SERVICE_CONFIG'] = str(selected) if selected is not None else ''
        python = section_path(config['launcher']['python'])
        if not python.is_file() or not os.access(python, os.X_OK):
            raise ConfigurationError('launcher.python is unavailable; prepare backend dependencies with uv sync')
        # Keep the virtualenv path, not its resolved symlink target: Python needs
        # that location to discover pyvenv.cfg and installed backend dependencies.
        if os.path.abspath(sys.executable) != str(python):
            os.execv(str(python), [str(python), str(Path(__file__).absolute()), *sys.argv[1:]])
        from app.launcher import launch
        return launch(config, environment)
    except ConfigurationError as error:
        print(f'Backend configuration error: {error}. See backend/config/service.local.example.toml', file=sys.stderr)
    except ImportError:
        print('Backend dependencies unavailable; prepare the environment with uv sync --project backend --frozen', file=sys.stderr)
    except (OSError, ValueError):
        print('Backend startup failed: check configuration, Python executable and resource paths', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
