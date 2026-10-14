"""Spotting format boundary tests use actual saved native output, no mocked OCR."""
import json
from pathlib import Path
import pytest
from app.auth import AccessError


PROOF = Path(__file__).resolve().parents[2]/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof'


@pytest.mark.parametrize('gray',[0,128,240])
def test_single_color_ink_reaches_printed_page_text(gray):
    from PIL import Image,ImageDraw
    from app.ocr import DocumentOCR,ink_mask
    image=Image.new('RGB',(80,30),'white')
    ImageDraw.Draw(image).text((5,5),'Budget',fill=(gray,gray,gray),font_size=12)
    # Crisp embedded PNG: exactly one foreground level, no antialias levels.
    image=image.convert('L').point(lambda value:gray if value<245 else 255).convert('RGB')
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.detect_handwriting=lambda image:[]
    ocr.recognize=lambda image,cancelled:[{'kind':'printed','text':'Budget','bbox':[5,5,60,20]}]
    assert ink_mask(image).any()
    assert not ink_mask(Image.new('RGB',image.size,'white')).any()
    assert ocr.finish_page(ocr.prepare_image(image,'complete'),None)['text']=='Budget\n'


@pytest.mark.parametrize('handwritten',[False,True])
def test_complete_page_preserves_printed_columns_when_inserting_handwriting(handwritten):
    from PIL import Image
    from app.ocr import DocumentOCR
    lines=[{'kind':'printed','text':text,'bbox':bbox} for text,bbox in [
        ('Left top',[0,0,40,10]),('Left bottom',[0,40,40,50]),
        ('Right top',[60,0,100,10]),('Right bottom',[60,40,100,50])]]
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.recognize=lambda image,cancelled:lines
    ocr.transcribe=lambda image,cancelled:'Note'
    image=Image.new('RGB',(100,60),'white')
    prepared={'image':image,'original':image,'printed_ink':True,'mode':'complete','skips':[],
              'handwriting':[{'kind':'handwritten','bbox':[0,20,40,30]}] if handwritten else []}
    page=ocr.finish_page(prepared,None)
    assert page['text']==('Left top\nNote\nLeft bottom\nRight top\nRight bottom\n' if handwritten
                          else 'Left top\nLeft bottom\nRight top\nRight bottom\n')
    for region in page['regions']:
        assert page['text'][region['start']:region['end']]==region['text']


def test_handwriting_only_columns_keep_original_geometry_order():
    from PIL import Image
    from app.ocr import DocumentOCR
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.transcribe=lambda image,cancelled:'Left' if image.width==40 else 'Right'
    image=Image.new('RGB',(100,30),'white')
    page=ocr.finish_page({'image':image,'original':image,'printed_ink':False,'mode':'complete','skips':[],
                          'handwriting':[{'kind':'handwritten','bbox':[0,0,40,20]},
                                         {'kind':'handwritten','bbox':[60,0,99,20]}]},None)
    assert page['text']=='Left\nRight\n'


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


def test_real_small_handwriting_crop_is_detected_before_permission_masking():
    """Actual pinned detector, genuine raster; recognition is never run to classify."""
    import os
    import onnxruntime as ort
    from PIL import Image
    from app.ocr import DocumentOCR
    root = Path(os.environ['RAG_OCR_DIR'])/'dfine'
    detector = DocumentOCR.__new__(DocumentOCR)
    detector.config = json.loads((root/'config.json').read_text())
    options = ort.SessionOptions(); options.intra_op_num_threads=2; options.inter_op_num_threads=1
    detector.detector = ort.InferenceSession(str(root/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    image = Image.open(PROOF/'real-handwritten-title-author-input-v1.png').convert('RGB')
    regions = detector.detect_handwriting(image)
    # Both actual handwritten lines must be covered; recognizing first and
    # redacting afterward cannot discharge the permission contract.
    assert len(regions) == 2, regions
    assert all(0 <= row['bbox'][0] < row['bbox'][2] <= image.width and
               0 <= row['bbox'][1] < row['bbox'][3] <= image.height for row in regions)
    print({'proof':'actual_small_handwriting_detection','size':image.size,'regions':regions},flush=True)


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


def test_ocr_loads_fixed_paddle_and_qwen_handwriting_profiles():
    import hashlib
    import os
    from app.ocr import DocumentOCR
    root=Path(os.environ['RAG_OCR_DIR'])
    ocr=DocumentOCR()
    try:
        for model,weight,projector,weight_hash,projector_hash in [
            (ocr.model,root/'PaddleOCR-VL-1.5.gguf',root/'PaddleOCR-VL-1.5-mmproj.gguf',
             '299051d54faa065abc505cc39b8383ea338fd3020c775ea3e0ba514a7022328c','e7f1a72400fba517046f90d964e2fa0f4dac7781ee3b1bc5d2022f5f8cecbd87'),
            (ocr.handwriting_model,Path(os.environ['RAG_MODEL_PATH']),root/'mmproj-F16.gguf',
             'aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223','7035e9cb8d7c6a9681d07eef9a364783e86ea4cd73faab2eabb4f43a101830c7')]:
            assert Path(model.model_path).samefile(weight)
            assert Path(model.chat_handler.clip_model_path).samefile(projector)
            for path,digest in [(weight,weight_hash),(projector,projector_hash)]:
                with path.open('rb') as source:assert hashlib.file_digest(source,'sha256').hexdigest()==digest
        assert ocr.handwriting_model.n_ctx()==4096
        print({'proof':'actual_RAG64_paddle_printed_qwen_handwriting_profiles'},flush=True)
    finally:ocr.close()
    assert ocr.model._ctx.ctx is None and ocr.handwriting_model._ctx.ctx is None


def test_original_english_and_missed_russian_ink_are_both_masked():
    import os
    import onnxruntime as ort
    from PIL import Image
    from app.ocr import DocumentOCR
    root=Path(os.environ['RAG_OCR_DIR'])/'dfine'
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.config=json.loads((root/'config.json').read_text())
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    ocr.detector=ort.InferenceSession(str(root/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    en=Image.open(PROOF/'real-handwritten-title-author-input-v1.png').convert('RGB')
    ru=Image.open(Path(__file__).parent/'fixtures/answer_lifecycle/handwritten-ru-august.png').convert('RGB')
    image=Image.new('RGB',(1200,700),'white');image.paste(en,(130,100));image.paste(ru,(620,420))
    detected=ocr.detect_text_regions(image)
    assert detected and not any(row['bbox'][1]>=420 for row in detected),detected
    prepared=ocr.prepare_image(image,'skip_handwriting')
    # Independent pixel masks distinguish black cursive from gray graph-paper
    # ruling and red cursive from neutral Russian paper. No recognizer sees GT.
    import numpy as np
    for original,(x,y) in [(en,(130,100)),(ru,(620,420))]:
        pixels=np.asarray(original).astype(int)
        ink=np.asarray(original.convert('L'))<100 if original is en else ((pixels[:,:,0]>pixels[:,:,1]+20)&(pixels[:,:,0]>pixels[:,:,2]+20))
        masked=np.asarray(prepared['image'].crop((x,y,x+original.width,y+original.height)))
        assert np.all(masked[ink]==255), {'origin':(x,y),'remaining':int(np.count_nonzero(masked[ink]!=255)), 'regions':prepared['handwriting']}
    assert any(row.get('detection_source')=='connected_ink' for row in prepared['handwriting'])
    print({'proof':'original_EN_RU_all_ink_masked_before_printed_recognition','detected':detected,'regions':prepared['handwriting']},flush=True)


async def test_actual_handwriting_abort_and_both_contexts_close_after_c_return():
    import asyncio
    import os
    from threading import Event
    from PIL import Image
    from app.ocr import DocumentOCR
    class HeldCancellation(Event):
        def __init__(self):
            super().__init__();self.calls=0;self.entered=Event();self.release=Event()
        def is_set(self):
            self.calls+=1
            if self.calls>1:
                self.entered.set();self.release.wait(20)
            return super().is_set()
    ocr=DocumentOCR();cancel=HeldCancellation()
    image=Image.open(Path(__file__).parent/'fixtures/answer_lifecycle/handwritten-ru-august.png').convert('RGB')
    future=asyncio.create_task(asyncio.to_thread(ocr.transcribe,image,cancel));closing=None
    try:
        assert await asyncio.to_thread(cancel.entered.wait,15)
        rss=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
        closing=asyncio.create_task(asyncio.to_thread(ocr.close));await asyncio.sleep(.1)
        assert not closing.done()
        cancel.set();cancel.release.set()
        with pytest.raises(AccessError,match='document_processing_cancelled'):await future
        await closing
        assert ocr.model._ctx.ctx is None and ocr.handwriting_model._ctx.ctx is None
        assert ocr.handwriting_model.chat_handler.mtmd_ctx is None
        print({'proof':'actual_Qwen_F16_handwriting_abort_C_return_both_contexts_close','rss_during_actual_handwriting_bytes':rss},flush=True)
    finally:
        cancel.set();cancel.release.set();await asyncio.gather(future,return_exceptions=True)
        if closing is not None:await closing
        else:ocr.close()


def test_genuine_be_expanded_regions_do_not_duplicate_the_same_ink_crop():
    import os
    import onnxruntime as ort
    from app.ocr import DocumentOCR,render_pdf_page
    root=Path(os.environ['RAG_OCR_DIR'])/'dfine'
    ocr=DocumentOCR.__new__(DocumentOCR);ocr.config=json.loads((root/'config.json').read_text())
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    ocr.detector=ort.InferenceSession(str(root/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    image=render_pdf_page(Path(__file__).parent/'fixtures/answer_lifecycle/handwritten-be-kupala.pdf',1)
    regions=ocr.detect_handwriting(image)
    for index,left in enumerate(regions):
        a=left['bbox']
        for right in regions[index+1:]:
            b=right['bbox'];overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            assert overlap<.8*min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1])),regions
    assert all(row['bbox'][3]<1100 for row in regions),regions  # Printed source footer begins below y1100.
    print({'proof':'actual_BE_ink_region_union_preserves_printed_footer','regions':regions},flush=True)
