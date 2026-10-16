"""Offline model identity checks and explicit, staged artifact preparation.

Importing this module uses only the standard library. It never loads inference,
database code, or downloads artifacts as a side effect of verification.
"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import tomllib
from urllib.parse import quote
import urllib.request
import uuid


PROJECT_ROOT = Path(__file__).absolute().parents[2]
MANIFEST_PATH = PROJECT_ROOT / 'backend/config/models.toml'
PREPARATION = 'Run python3 backend/prepare_models.py --source EXISTING_DIRECTORY or --download explicitly.'


class ModelArtifactError(ValueError):
    """An actionable artifact or compatibility failure before component startup."""


def _fail(message):
    raise ModelArtifactError(f'{message}. {PREPARATION}')


def _no_symlinks(path):
    raw = Path(path).absolute()
    # Inspect before normalizing '..': normalization must not conceal a link.
    for part in reversed((raw, *raw.parents)):
        if part.is_symlink():
            _fail(f'Model path uses a symlink: {part}')
    return Path(os.path.abspath(raw))


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        _fail(f'Invalid artifact path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or value != path.as_posix() or path == PurePosixPath('.'):
        _fail(f'Invalid artifact path: {value!r}')
    return path


def load_manifest(path=None):
    try:
        with _no_symlinks(path or MANIFEST_PATH).open('rb') as stream:
            manifest = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        _fail(f'Cannot read model manifest: {error}')
    _validate_manifest(manifest)
    return manifest


def _validate_manifest(manifest):
    if manifest.get('schema_version') != 1 or not manifest.get('artifacts'):
        _fail('Invalid model manifest schema or empty artifact set')
    ids, paths = set(), set()
    for item in manifest['artifacts']:
        try:
            path = str(_relative(item['path']))
            _relative(item['remote_file'])
            if not re.fullmatch(r'[0-9a-f]{40}', item['revision']):
                _fail(f'Artifact {path} requires an immutable 40-digit revision')
            if not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
                _fail(f'Artifact {path} has no trusted SHA-256')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', item['source']):
                _fail(f'Artifact {path} has an invalid source repository')
            if type(item['size']) is not int or item['size'] <= 0 or not item['format'] or not item['profile']:
                _fail(f'Artifact {path} has invalid size/format/profile')
            if not item['id'] or item['id'] in ids or path in paths:
                _fail(f'Duplicate or empty artifact identity/path: {path}')
            ids.add(item['id'])
            paths.add(path)
        except (KeyError, TypeError) as error:
            _fail(f'Incomplete model manifest artifact: {error}')


def verify_directory(root, manifest=None):
    """Verify every manifest companion, offline; return artifact ID -> absolute path."""
    manifest = load_manifest() if manifest is None else manifest
    _validate_manifest(manifest)
    root = _no_symlinks(root)
    result = {}
    for item in manifest['artifacts']:
        path = _no_symlinks(root / item['path'])
        if not path.is_file():
            _fail(f'Missing model artifact: {path}')
        try:
            if path.stat().st_size != item['size']:
                _fail(f'Corrupt model artifact {path}: size differs from pinned manifest')
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            if digest.hexdigest() != item['sha256']:
                _fail(f'Corrupt model artifact {path}: SHA-256 differs from pinned manifest')
        except OSError as error:
            _fail(f'Cannot read model artifact {path}: {error}')
        result[item['id']] = path
    return result


def _check_profile(actual, expected, prefix):
    for key, wanted in expected.items():
        name = f'{prefix}.{key}'
        value = actual.get(key)
        if isinstance(wanted, dict) and isinstance(value, dict):
            _check_profile(value, wanted, name)
        elif value != wanted:
            _fail(f'Incompatible model profile: {name}; restore the manifest-compatible configuration')


def verify_installation(config):
    """Check merged service paths, merged runtime/OCR profiles, and all nine files.

    Service paths retain the existing backend-relative semantics. Only the exact
    manifest installation at project-root rag/local_models is accepted.
    """
    manifest = load_manifest()
    storage = _no_symlinks(PROJECT_ROOT / 'rag/local_models')
    expected = manifest['service_paths']
    models = config.get('models', {})
    for role, relative in expected.items():
        value = models.get(role)
        if role == 'handwriting' and not value:
            value = models.get('generation')
        if not isinstance(value, str) or not value.strip() or '\x00' in value:
            _fail(f'Missing models.{role}; configure backend-relative ../rag/local_models/{relative}')
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / 'backend' / candidate
        candidate = _no_symlinks(candidate)
        if candidate != storage / relative:
            _fail(f'Invalid models.{role}: expected project rag/local_models/{relative}')
    # The configuration module is itself stdlib-only; load lazily for lightweight import.
    from app.configuration import ConfigurationError, load_settings
    for name, profile in manifest['profiles'].items():
        try:
            actual = load_settings(name)
        except ConfigurationError as error:
            _fail(f'Cannot validate model profile {name}: {error}')
        _check_profile(actual, profile, name)
    return verify_directory(storage, manifest)


def _download_url(item):
    return (f"https://huggingface.co/{item['source']}/resolve/{item['revision']}/"
            + quote(item['remote_file'], safe='/'))


def _remove_source_files(source, manifest):
    # Unknown files belong to the operator. Delete only the verified companions.
    try:
        for item in manifest['artifacts']:
            (source / item['path']).unlink()
        directories = {parent for item in manifest['artifacts']
                       for parent in (source / item['path']).parents if parent != source and source in parent.parents}
        for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
    except OSError as error:
        _fail(f'Destination is verified; source cleanup incomplete: {error}; '
              'some source companions may already have been removed; retain the destination and inspect the source')


def prepare_models(*, source=None, download=False, move=False, destination=None, manifest=None):
    """Explicit preparation. Return verified paths; never replace a partial set.

    Stage on the destination filesystem, verify all companions, then publish by
    rename. A prior scaffold is retained in .local_models-backup-* for rollback.
    Complete matching installations are reverified and reused without replacing
    their files. Source cleanup is opt-in and follows destination verification.
    """
    manifest = load_manifest() if manifest is None else manifest
    _validate_manifest(manifest)
    if (source is None) == (not download) or (move and source is None):
        _fail('Choose exactly one of --source DIRECTORY or --download; --move requires --source')
    destination = _no_symlinks(destination or PROJECT_ROOT / 'rag/local_models')
    source = _no_symlinks(source) if source is not None else None
    if source is not None:
        if source == destination or source in destination.parents or destination in source.parents:
            _fail('Source and destination must be separate, non-overlapping directories')
        verify_directory(source, manifest)
    if destination.exists():
        if not destination.is_dir():
            _fail(f'Existing destination is not a directory: {destination}')
        contents = list(destination.iterdir())
        if any(path.name != '.gitignore' for path in contents):
            try:
                verified = verify_directory(destination, manifest)
            except ModelArtifactError as error:
                _fail(f'Existing destination is incomplete or corrupt; preserve/restore it before preparation: {error}')
            if move:
                verify_directory(source, manifest)
                _remove_source_files(source, manifest)
            return verified
        for path in contents:
            _no_symlinks(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.local_models-stage-', dir=destination.parent))
    backup = None
    try:
        for item in manifest['artifacts']:
            target = stage / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if source is not None:
                shutil.copyfile(_no_symlinks(source / item['path']), target)
            else:
                with urllib.request.urlopen(_download_url(item), timeout=60) as response, target.open('xb') as stream:
                    shutil.copyfileobj(response, stream)
        verify_directory(stage, manifest)
        if destination.exists():
            # Preserve the tracked scaffold and retain its prior directory.
            if (destination / '.gitignore').is_file():
                shutil.copyfile(destination / '.gitignore', stage / '.gitignore')
            backup = destination.parent / ('.local_models-backup-' + uuid.uuid4().hex)
            destination.rename(backup)
        else:
            (stage / '.gitignore').write_text('*\n!.gitignore\n')
        try:
            stage.rename(destination)
            verified = verify_directory(destination, manifest)
        except BaseException:
            # Restore the old directory, retaining a failed candidate for diagnosis.
            if destination.exists():
                destination.rename(stage)
            if backup is not None:
                backup.rename(destination)
            raise
        if move:
            verify_directory(source, manifest)
            _remove_source_files(source, manifest)
        return verified
    except (OSError, ValueError) as error:
        if isinstance(error, ModelArtifactError):
            raise
        _fail(f'Model preparation failed: {error}; inspect the source and retained prior directory before retrying')
    finally:
        if stage.exists():
            shutil.rmtree(stage)
