"""One entrypoint for the complete backend, including its prepared virtualenv."""
import sys

# This guard must precede tomllib and application imports, including configuration.
if sys.version_info[:2] != (3, 12):
    raise SystemExit('Backend requires Python 3.12; run with python3.12 and prepare dependencies with uv sync --project backend --frozen')

import argparse
import os
from pathlib import Path

from bootstrap import BootstrapError, check_native, early_signals, ensure_environment
from app.configuration import ConfigurationError, launch_environment, load_service_config, section_path
from app.model_artifacts import ModelArtifactError, verify_installation


def main():
    parser = argparse.ArgumentParser(description='Run the RAG API, document worker and generation service')
    parser.add_argument('--config', type=Path, help='Local TOML overrides instead of config/service.local.toml')
    args = parser.parse_args()
    with early_signals():
        try:
            selected = args.config if args.config is not None else os.environ.get('RAG_SERVICE_CONFIG')
            selected = Path(os.path.abspath(Path(selected).expanduser())) if selected else None
            config = load_service_config(selected)
            environment = launch_environment(config)
            environment['RAG_SERVICE_CONFIG'] = str(selected) if selected is not None else ''
            python = section_path(config['launcher']['python'])
            ensure_environment(python, Path(__file__).absolute().parent)
            # Preserve the venv path: resolving the symlink loses pyvenv.cfg.
            if os.path.abspath(sys.executable) != str(python):
                os.execv(str(python), [str(python), str(Path(__file__).absolute()), *sys.argv[1:]])
            os.environ['RAG_SERVICE_CONFIG'] = environment['RAG_SERVICE_CONFIG']
            verify_installation(config)
            check_native(Path(__file__).absolute().parent, environment)
            from app.launcher import launch
            return launch(config, environment)
        except ConfigurationError as error:
            print(f'Backend configuration error: {error}. See backend/config/service.local.example.toml', file=sys.stderr)
        except (BootstrapError, ModelArtifactError) as error:
            print(f'Backend startup failed: {error}', file=sys.stderr)
        except ImportError:
            print('Backend dependencies unavailable; prepare the environment with uv sync --project backend --frozen', file=sys.stderr)
        except (OSError, ValueError):
            print('Backend startup failed: check configuration, Python executable and resource paths', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
