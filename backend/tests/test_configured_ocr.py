"""Changed OCR settings reach geometry, fragment assembly and model calls."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tomllib

import numpy as np
from PIL import Image, ImageDraw
import pytest

from app import ocr, ocr_fragments


@pytest.fixture
def configured(monkeypatch):
    with (Path(__file__).parents[1] / 'config/ocr.toml').open('rb') as source:
        settings = tomllib.load(source)
    # Supply new keys before extraction so RED proves consumption, not file loading.
    settings['execution'] = {'n_threads': 2, 'n_threads_batch': 3, 'n_batch': 64, 'n_ubatch': 32}
    settings['detector'] = {'intra_op_num_threads': 3, 'inter_op_num_threads': 2, 'confidence': .6}
    settings['geometry'] = {'render_width': 800, 'foreground_threshold': 180, 'padding': 1,
                            'component_min_height': 2, 'component_min_aspect': .5,
                            'component_min_pixels': 4, 'component_max_density': .95,
                            'region_union_overlap': .8}
    settings['fragments'] = {'limit': 20, 'overlap': 4, 'edge_tolerance': 1,
                             'duplicate_min_overlap': .95, 'duplicate_max_overlap': .95,
                             'spanning_width': .8}
    settings['decoding'] = {'max_tokens': 17}
    prompts = {'ocr': {'printed': 'Configured spotting task', 'handwriting': 'Configured transcription task'}}
    def load(name):
        return settings if name == 'ocr' else prompts
    monkeypatch.setattr(ocr, 'load_settings', load, raising=False)
    monkeypatch.setattr(ocr_fragments, 'load_settings', load, raising=False)
    return settings


def test_foreground_cutoff_is_shared_with_fragment_boundary_search(configured):
    image = Image.new('RGB', (10, 24), 'white')
    ImageDraw.Draw(image).rectangle((0, 18, 9, 19), fill=(200, 200, 200))
    assert not ocr.ink_mask(image).any()
    assert ocr_fragments.fragment_boxes(image) == [(0, 0, 10, 20), (0, 16, 10, 24)]


def test_fragment_duplicate_threshold_retains_distinct_overlapping_regions(configured):
    regions = ocr_fragments.merge_fragments([
        ((0, 0, 20, 20), [{'kind': 'printed', 'text': 'First', 'bbox': [0, 0, 10, 10]}]),
        ((0, 0, 20, 20), [{'kind': 'printed', 'text': 'Second', 'bbox': [2, 0, 12, 10]}]),
    ])
    assert [region['text'] for region in regions] == ['First', 'Second']


def test_connected_ink_uses_configured_component_rules_and_padding(configured):
    image = Image.new('RGB', (15, 15), 'white')
    ImageDraw.Draw(image).rectangle((5, 5, 7, 7), outline='black')
    recognizer = ocr.DocumentOCR.__new__(ocr.DocumentOCR)
    recognizer.detect_text_regions = lambda image: []
    assert recognizer.detect_handwriting(image) == [{
        'kind': 'handwritten', 'bbox': [4, 4, 9, 9],
        'detection_source': 'connected_ink', 'coordinate_source': 'original_ink_component',
    }]


def test_detector_uses_configured_confidence_and_padding(configured):
    recognizer = ocr.DocumentOCR.__new__(ocr.DocumentOCR)
    recognizer.config = {'id2label': {'0': 'handwritten'}}
    recognizer.detector = SimpleNamespace(run=lambda *_: (
        np.array([[[np.log(7 / 3)]]]), np.array([[[.5, .5, .25, .25]]]),
    ))
    image = Image.new('RGB', (640, 640), 'white')
    assert recognizer.detect_text_regions(image)[0]['bbox'] == [239, 239, 401, 401]
    configured['detector']['confidence'] = .8
    assert recognizer.detect_text_regions(image) == []


def test_model_calls_use_configured_tasks_and_output_limit(configured):
    calls = []
    raw = 'Printed' + ''.join(f'<|LOC_{value}|>' for value in [0, 0, 500, 0, 500, 500, 0, 500])
    def printed(**kwargs):
        calls.append(kwargs)
        return {'choices': [{'finish_reason': 'stop'}], 'usage': {'completion_tokens': 1}}
    def handwritten(**kwargs):
        calls.append(kwargs)
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'Handwritten'}}]}
    recognizer = ocr.DocumentOCR.__new__(ocr.DocumentOCR)
    recognizer.model = SimpleNamespace(create_chat_completion=printed, input_ids=np.array([1]),
                                       n_tokens=1, detokenize=lambda *_, **__: raw.encode())
    recognizer.handwriting_model = SimpleNamespace(chat_handler=handwritten)
    image = Image.new('RGB', (20, 20), 'white')
    assert recognizer._recognize(image)[0]['text'] == 'Printed'
    assert recognizer._transcribe(image) == 'Handwritten'
    assert [call['messages'][0]['content'][1]['text'] for call in calls] == [
        'Configured spotting task', 'Configured transcription task',
    ]
    assert [call['max_tokens'] for call in calls] == [17, 17]
    assert all(call['temperature'] == 0 for call in calls)
    assert calls[1]['enable_thinking'] is False


def test_native_and_detector_creation_use_configured_execution(configured, tmp_path, monkeypatch):
    root = tmp_path / 'models'
    (root / 'dfine').mkdir(parents=True)
    (root / 'dfine/config.json').write_text(json.dumps({'use_focal_loss': True}))
    (root / 'dfine/preprocessor_config.json').write_text(json.dumps({
        'do_normalize': False, 'size': {'height': 640, 'width': 640},
    }))
    digest = hashlib.sha256(b'model fixture').hexdigest()
    for role in ('printed', 'handwriting'):
        for key in ('model', 'projector'):
            configured[role][key] = f'{role}-{key}.gguf'
            configured[role][key + '_sha256'] = digest
            (root / configured[role][key]).write_bytes(b'model fixture')
    monkeypatch.setenv('RAG_OCR_DIR', str(root))
    monkeypatch.setenv('RAG_OCR_MODEL_PATH', str(root / configured['handwriting']['model']))
    executions, detectors = [], []
    def native_model(**kwargs):
        executions.append(kwargs)
        return SimpleNamespace(close=lambda: None)
    def detector(*args, **kwargs):
        detectors.append(kwargs['sess_options'])
        return object()
    monkeypatch.setattr(ocr, 'Llama', native_model)
    monkeypatch.setattr(ocr, 'MTMDChatHandler', lambda *_, **__: object())
    monkeypatch.setattr(ocr.ort, 'InferenceSession', detector)
    recognizer = ocr.DocumentOCR()
    try:
        assert len(executions) == 2
        for execution in executions:
            assert {key: execution[key] for key in configured['execution']} == configured['execution']
            assert execution['n_gpu_layers'] == 0
        assert detectors[0].intra_op_num_threads == 3
        assert detectors[0].inter_op_num_threads == 2
    finally:
        recognizer.close()


def test_pdf_render_uses_configured_width(configured, monkeypatch):
    scales = []
    image = Image.new('RGB', (800, 400), 'white')
    bitmap = SimpleNamespace(to_pil=lambda: image, close=lambda: None)
    def render(*, scale):
        scales.append(scale)
        return bitmap
    page = SimpleNamespace(get_width=lambda: 400, render=render, close=lambda: None)
    class PDF:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def __len__(self): return 1
        def __getitem__(self, _): return page
    monkeypatch.setattr(ocr.pdfium, 'PdfDocument', lambda _: PDF())
    assert ocr.render_pdf_page('unused.pdf', 1).size == (800, 400)
    assert scales == [2.0]
