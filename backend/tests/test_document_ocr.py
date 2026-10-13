"""Spotting format boundary tests use actual saved native output, no mocked OCR."""
import json
from pathlib import Path
import pytest
from app.auth import AccessError


PROOF = Path(__file__).resolve().parents[2]/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof'


def test_native_coordinate_tokens_place_skip_blocks_without_recognizing_handwriting():
    from app.ocr import parse_spotting, compose_page, SKIP_TEXT
    raw=json.loads((PROOF/'native-spotting-result-v2.json').read_text())['raw_special_output']
    lines=parse_spotting(raw,1200,1400)
    assert [line['text'] for line in lines]==json.loads((PROOF/'printed-four-languages-v1.json').read_text())['expected_lines']
    assert all(0<=line['bbox'][0]<line['bbox'][2]<=1200 and 0<=line['bbox'][1]<line['bbox'][3]<=1400 for line in lines)
    skips=[{'kind':'skip','text':SKIP_TEXT,'bbox':[104,783,458,908]}, {'kind':'skip','text':SKIP_TEXT,'bbox':[252,916,795,1034]}]
    page=compose_page(lines,skips)
    assert page['text'].count(SKIP_TEXT)==2
    assert 'Dreams' not in page['text'] and 'Hughes' not in page['text']
    assert page['text'].find(SKIP_TEXT)>page['text'].find('Гадавы бюджэт')
    for region in page['regions']:
        assert page['text'][region['start']:region['end']]==region['text']


@pytest.mark.parametrize('raw', ['Unlocated OCR text', 'x'+''.join('<|LOC_1001|>' for _ in range(8)), 'x'+''.join('<|LOC_0|>' for _ in range(8))])
def test_invalid_or_degenerate_native_coordinates_fail_whole_page(raw):
    from app.ocr import parse_spotting
    with pytest.raises(AccessError):
        parse_spotting(raw,1200,1400)


def test_documented_wrapped_locations_are_not_part_of_recognized_text():
    from app.ocr import parse_spotting
    coordinates=''.join(f'<|LOC_{value}|>' for value in [10,20,100,20,100,50,10,50])
    lines=parse_spotting('<|TEXT_START|>Budget<|TEXT_END|><|LOC_BEGIN|>'+coordinates+'<|LOC_END|>',1000,1000)
    assert len(lines)==1 and lines[0]['text']=='Budget' and lines[0]['bbox']==[10,20,100,50]


def test_diagonal_zero_area_polygon_is_rejected():
    from app.ocr import parse_spotting
    raw='Budget'+''.join(f'<|LOC_{value}|>' for value in [10,10,20,20,30,30,40,40])
    with pytest.raises(AccessError,match='invalid_ocr_coordinates'):
        parse_spotting(raw,1000,1000)


async def test_actual_native_abort_and_close_wait_for_c_return():
    import asyncio
    from threading import Event
    from PIL import Image
    from app.ocr import DocumentOCR
    class HeldCancellation(Event):
        def __init__(self):
            super().__init__();self.calls=0;self.entered=Event();self.release=Event()
        def is_set(self):
            self.calls+=1
            if self.calls>1:
                self.entered.set()
                self.release.wait(20)
            return super().is_set()
    ocr=DocumentOCR()
    cancel=HeldCancellation()
    image=Image.open(PROOF/'mixed-pdf-printed-only-input-v1.png').convert('RGB')
    future=asyncio.create_task(asyncio.to_thread(ocr.recognize,image,cancel))
    closing=None
    try:
        assert await asyncio.to_thread(cancel.entered.wait,15)
        closing=asyncio.create_task(asyncio.to_thread(ocr.close))
        await asyncio.sleep(.1)
        assert not closing.done()
        cancel.set();cancel.release.set()
        with pytest.raises(AccessError,match='document_processing_cancelled'):
            await future
        await closing
        assert ocr.model._ctx.ctx is None
        print('Actual native abort callback entered C; context close waited for C return before physical free.')
    finally:
        cancel.set();cancel.release.set()
        await asyncio.gather(future,return_exceptions=True)
        if closing is not None:await closing
        else:ocr.close()
