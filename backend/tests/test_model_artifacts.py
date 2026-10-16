"""Tiny artifacts exercise preparation without loading models or touching the network."""
import hashlib
from pathlib import Path

import pytest


def artifacts_module():
    try:
        from app import model_artifacts
    except ImportError:
        pytest.fail('model artifact verification/preparation is not implemented')
    return model_artifacts


@pytest.fixture
def model_set(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    artifacts = []
    for name, content in [('model.onnx', b'weights'), ('tokenizer.json', b'{}')]:
        (source / name).write_bytes(content)
        artifacts.append(dict(id=name, path=name, source='fixture/models',
            revision='1' * 40, remote_file=name, sha256=hashlib.sha256(content).hexdigest(),
            size=len(content), format='fixture', profile='fixture'))
    return source, dict(schema_version=1, artifacts=artifacts)


def test_verification_requires_every_companion_and_reports_preparation(model_set):
    api = artifacts_module()
    source, manifest = model_set
    (source / 'tokenizer.json').unlink()
    with pytest.raises(api.ModelArtifactError, match='tokenizer.json.*prepare_models.py'):
        api.verify_directory(source, manifest=manifest)


@pytest.mark.parametrize('content', [b'x', b'WEIGHTS'])
def test_verification_rejects_truncated_or_wrong_hash(model_set, content):
    api = artifacts_module()
    source, manifest = model_set
    (source / 'model.onnx').write_bytes(content)
    with pytest.raises(api.ModelArtifactError, match='model.onnx.*(size|SHA-256)'):
        api.verify_directory(source, manifest=manifest)


def test_verification_is_offline_and_rejects_symlink_escape(model_set, tmp_path, monkeypatch):
    api = artifacts_module()
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('network during verification'))
    source, manifest = model_set
    assert set(api.verify_directory(source, manifest=manifest)) == {'model.onnx', 'tokenizer.json'}
    outside = tmp_path / 'outside'
    outside.write_bytes(b'weights')
    (source / 'model.onnx').unlink()
    (source / 'model.onnx').symlink_to(outside)
    with pytest.raises(api.ModelArtifactError, match='symlink'):
        api.verify_directory(source, manifest=manifest)


@pytest.mark.parametrize('relative', ['../outside', '/tmp/outside'])
def test_manifest_paths_cannot_escape(model_set, relative):
    api = artifacts_module()
    source, manifest = model_set
    manifest['artifacts'][0]['path'] = relative
    with pytest.raises(api.ModelArtifactError, match='path'):
        api.verify_directory(source, manifest=manifest)


def test_preparation_verified_reuse_and_move_preserve_unrelated_files(model_set, tmp_path):
    api = artifacts_module()
    source, manifest = model_set
    destination = tmp_path / 'installed'
    api.prepare_models(source=source, destination=destination, manifest=manifest)
    assert (source / 'model.onnx').read_bytes() == b'weights'
    before = (destination / 'model.onnx').stat().st_ino
    (source / 'unrelated.txt').write_text('keep')
    api.prepare_models(source=source, destination=destination, manifest=manifest, move=True)
    assert (destination / 'model.onnx').stat().st_ino == before
    assert (source / 'unrelated.txt').read_text() == 'keep'
    assert not (source / 'model.onnx').exists()


def test_failed_source_or_stage_keeps_current_and_source(model_set, tmp_path, monkeypatch):
    api = artifacts_module()
    import shutil
    source, manifest = model_set
    destination = tmp_path / 'installed'
    destination.mkdir()
    (destination / '.gitignore').write_text('*\n!.gitignore\n')
    copyfile = shutil.copyfile
    def broken_copy(src, dst):
        copyfile(src, dst)
        Path(dst).write_bytes(b'broken')
    monkeypatch.setattr(shutil, 'copyfile', broken_copy)
    with pytest.raises(api.ModelArtifactError):
        api.prepare_models(source=source, destination=destination, manifest=manifest, move=True)
    assert (destination / '.gitignore').is_file()
    assert not (destination / 'model.onnx').exists()
    assert (source / 'model.onnx').read_bytes() == b'weights'
    (source / 'tokenizer.json').unlink()
    with pytest.raises(api.ModelArtifactError, match='tokenizer.json'):
        api.prepare_models(source=source, destination=destination, manifest=manifest)
    assert (destination / '.gitignore').is_file()


def test_partial_destination_is_preserved(model_set, tmp_path):
    api = artifacts_module()
    source, manifest = model_set
    destination = tmp_path / 'installed'
    destination.mkdir()
    (destination / 'model.onnx').write_bytes(b'old')
    with pytest.raises(api.ModelArtifactError, match='Existing destination'):
        api.prepare_models(source=source, destination=destination, manifest=manifest)
    assert (destination / 'model.onnx').read_bytes() == b'old'
    assert (source / 'model.onnx').read_bytes() == b'weights'


def test_download_rejects_mutable_revision_before_network(model_set, monkeypatch, tmp_path):
    api = artifacts_module()
    import urllib.request
    source, manifest = model_set
    manifest['artifacts'][0]['revision'] = 'main'
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('mutable download'))
    with pytest.raises(api.ModelArtifactError, match='revision'):
        api.prepare_models(download=True, destination=tmp_path / 'installed', manifest=manifest)


def test_download_uses_pinned_url_and_verifies_full_set(model_set, tmp_path, monkeypatch):
    api = artifacts_module()
    import io
    import urllib.request
    source, manifest = model_set
    urls = []
    def response(url, **kwargs):
        urls.append(url)
        return io.BytesIO((source / url.rsplit('/', 1)[-1]).read_bytes())
    monkeypatch.setattr(urllib.request, 'urlopen', response)
    destination = tmp_path / 'installed'
    api.prepare_models(download=True, destination=destination, manifest=manifest)
    assert urls == [
        'https://huggingface.co/fixture/models/resolve/' + '1' * 40 + '/model.onnx',
        'https://huggingface.co/fixture/models/resolve/' + '1' * 40 + '/tokenizer.json']
    assert (destination / 'tokenizer.json').read_bytes() == b'{}'


def test_installation_rejects_outside_paths_and_incompatible_profile(tmp_path, monkeypatch):
    api = artifacts_module()
    from app import configuration
    monkeypatch.setattr(api, 'PROJECT_ROOT', tmp_path)
    config = {'models': dict(generation='/tmp/model.gguf', embedding='../rag/local_models/e5',
                            ocr='../rag/local_models/ocr', handwriting='')}
    with pytest.raises(api.ModelArtifactError, match='models.generation.*rag/local_models'):
        api.verify_installation(config)
    config['models']['generation'] = '../rag/local_models/Qwen3.5-2B-Q4_K_M.gguf'
    original = configuration.load_settings
    def incompatible(name):
        value = original(name)
        if name == 'runtime':
            value['embedding']['query_prefix'] = 'wrong: '
        return value
    monkeypatch.setattr(configuration, 'load_settings', incompatible)
    with pytest.raises(api.ModelArtifactError, match='profile.*embedding.query_prefix'):
        api.verify_installation(config)


def test_full_manifest_companions_are_required_and_import_is_lightweight(tmp_path):
    api = artifacts_module()
    manifest = api.load_manifest()
    assert {item['path'] for item in manifest['artifacts']} == {
        'e5/model_quantized.onnx', 'e5/tokenizer.json', 'Qwen3.5-2B-Q4_K_M.gguf',
        'ocr/mmproj-F16.gguf', 'ocr/PaddleOCR-VL-1.5.gguf',
        'ocr/PaddleOCR-VL-1.5-mmproj.gguf', 'ocr/dfine/model.onnx',
        'ocr/dfine/config.json', 'ocr/dfine/preprocessor_config.json'}
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c',
        "import sys; import app.model_artifacts; assert not ({'numpy','onnxruntime','llama_cpp','app.db'} & sys.modules.keys())"],
        cwd=Path(__file__).parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_installation_accepts_complete_set_independently_of_cwd(model_set, tmp_path, monkeypatch):
    api = artifacts_module()
    source, manifest = model_set
    destination = tmp_path / 'rag/local_models'
    api.prepare_models(source=source, destination=destination, manifest=manifest)
    manifest['service_paths'] = {'generation': 'model.onnx', 'embedding': '.', 'ocr': '.', 'handwriting': 'model.onnx'}
    manifest['profiles'] = {}
    monkeypatch.setattr(api, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(api, 'load_manifest', lambda: manifest)
    monkeypatch.chdir(tmp_path.parent)
    config = {'models': {'generation': '../rag/local_models/model.onnx',
                         'embedding': '../rag/local_models', 'ocr': '../rag/local_models', 'handwriting': ''}}
    result = api.verify_installation(config)
    assert result['model.onnx'] == destination / 'model.onnx'


def test_publication_failure_restores_previous_scaffold(model_set, tmp_path, monkeypatch):
    api = artifacts_module()
    source, manifest = model_set
    destination = tmp_path / 'installed'
    destination.mkdir()
    (destination / '.gitignore').write_text('original scaffold')
    rename = Path.rename
    def fail_publication(path, target):
        if path.name.startswith('.local_models-stage-'):
            raise OSError('simulated publication failure')
        return rename(path, target)
    monkeypatch.setattr(Path, 'rename', fail_publication)
    with pytest.raises(api.ModelArtifactError, match='publication failure'):
        api.prepare_models(source=source, destination=destination, manifest=manifest, move=True)
    assert (destination / '.gitignore').read_text() == 'original scaffold'
    assert (source / 'model.onnx').read_bytes() == b'weights'


def test_source_rejects_symlink_hidden_by_dotdot(model_set, tmp_path):
    api = artifacts_module()
    source, manifest = model_set
    (tmp_path / 'link').symlink_to(source, target_is_directory=True)
    with pytest.raises(api.ModelArtifactError, match='symlink'):
        api.verify_directory(tmp_path / 'link/../source', manifest=manifest)


def test_invalid_profile_has_actionable_model_error(monkeypatch):
    api = artifacts_module()
    from app import configuration
    def invalid(name):
        raise configuration.ConfigurationError('invalid profile')
    monkeypatch.setattr(configuration, 'load_settings', invalid)
    config = {'models': {'generation': '../rag/local_models/Qwen3.5-2B-Q4_K_M.gguf',
                         'embedding': '../rag/local_models/e5', 'ocr': '../rag/local_models/ocr', 'handwriting': ''}}
    with pytest.raises(api.ModelArtifactError, match='profile.*prepare_models.py'):
        api.verify_installation(config)


def test_operational_runtime_tuning_does_not_change_artifact_compatibility(model_set, tmp_path, monkeypatch):
    api = artifacts_module()
    from app import configuration
    source, tiny = model_set
    manifest = api.load_manifest()
    manifest['artifacts'] = tiny['artifacts']
    manifest['service_paths'] = {'generation': 'model.onnx', 'embedding': '.', 'ocr': '.', 'handwriting': 'model.onnx'}
    destination = tmp_path / 'rag/local_models'
    api.prepare_models(source=source, destination=destination, manifest=manifest)
    original = configuration.load_settings
    def tuned(name):
        settings = original(name)
        if name == 'runtime':
            settings['generation'].update(max_active=6, step_width=2, n_threads=2, n_threads_batch=2, n_ctx=8192)
            settings['embedding']['intra_op_threads'] = 2
        return settings
    monkeypatch.setattr(configuration, 'load_settings', tuned)
    monkeypatch.setattr(api, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(api, 'load_manifest', lambda: manifest)
    config = {'models': {'generation': '../rag/local_models/model.onnx',
                         'embedding': '../rag/local_models', 'ocr': '../rag/local_models', 'handwriting': ''}}
    assert api.verify_installation(config)['model.onnx'] == destination / 'model.onnx'


def test_move_cleanup_failure_reports_verified_destination_and_partial_source(model_set, tmp_path, monkeypatch):
    api = artifacts_module()
    source, manifest = model_set
    destination = tmp_path / 'installed'
    unlink = Path.unlink
    def fail_second_file(path, *args, **kwargs):
        if path == source / 'tokenizer.json':
            raise PermissionError('simulated cleanup failure')
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail_second_file)
    with pytest.raises(api.ModelArtifactError, match='Destination is verified; source cleanup incomplete'):
        api.prepare_models(source=source, destination=destination, manifest=manifest, move=True)
    assert (destination / 'model.onnx').read_bytes() == b'weights'
    assert (destination / 'tokenizer.json').read_bytes() == b'{}'
    assert not (source / 'model.onnx').exists()
    assert (source / 'tokenizer.json').read_bytes() == b'{}'


@pytest.mark.parametrize('existing_set', [False, True], ids=['empty-directory', 'verified-reuse'])
def test_preparation_restores_missing_git_exclusions(model_set, tmp_path, existing_set):
    import subprocess
    api = artifacts_module()
    source, manifest = model_set
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(repo)], check=True)
    destination = repo / 'rag/local_models'
    destination.mkdir(parents=True)
    if existing_set:
        for item in manifest['artifacts']:
            (destination / item['path']).write_bytes((source / item['path']).read_bytes())
    api.prepare_models(source=source, destination=destination, manifest=manifest)
    model_paths = ['rag/local_models/' + item['path'] for item in manifest['artifacts']]
    result = subprocess.run(['git', '-C', str(repo), 'check-ignore', *model_paths],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.splitlines() == model_paths
    scaffold = subprocess.run(['git', '-C', str(repo), 'check-ignore', 'rag/local_models/.gitignore'],
                              capture_output=True, text=True)
    assert scaffold.returncode == 1, 'The exclusion scaffold must remain trackable'
