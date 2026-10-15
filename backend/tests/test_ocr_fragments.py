"""Fragment geometry and page assembly; native models are tested separately."""
from threading import Event

import pytest
from PIL import Image, ImageDraw

from app.auth import AccessError
from app.ocr import DocumentOCR, SKIP_TEXT


def line(text, box, kind='printed'):
    x0,y0,x1,y1=box
    return {'kind':kind,'text':text,'bbox':box,
            'polygon':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]}


@pytest.mark.parametrize('size',[(200,4700),(4700,200),(4700,4700),(2400,2400),(1,2401)])
def test_fragments_cover_every_pixel_with_bounded_overlapping_inputs(size):
    from app.ocr_fragments import fragment_boxes
    image=Image.new('RGB',size,'white')
    boxes=fragment_boxes(image)
    coverage=Image.new('1',size)
    draw=ImageDraw.Draw(coverage)
    for x0,y0,x1,y1 in boxes:
        assert 0<x1-x0<=2400 and 0<y1-y0<=2400
        draw.rectangle((x0,y0,x1-1,y1-1),fill=1)
    assert coverage.getextrema()==(1,1)
    xs=sorted({(box[0],box[2]) for box in boxes})
    ys=sorted({(box[1],box[3]) for box in boxes})
    for ranges in (xs,ys):
        assert all(left[1]-right[0]==128 for left,right in zip(ranges,ranges[1:]))
    if size==(2400,2400):
        assert boxes==[(0,0,2400,2400)]


def test_cut_uses_nearby_white_gap_instead_of_bisecting_text():
    from app.ocr_fragments import fragment_boxes
    image=Image.new('RGB',(200,3000),'white')
    ImageDraw.Draw(image).rectangle((0,2370,199,2420),fill='black')
    boxes=fragment_boxes(image)
    assert boxes[0][3]==2370
    assert boxes[1][1]==2242


def test_overlap_keeps_intact_geometry_and_repeated_words_at_other_locations():
    from app.ocr_fragments import merge_fragments
    fragments=[((0,0,200,2400),[
        line('Same',[10,100,80,120]),line('Intact',[10,2350,100,2390])]),
        ((0,2272,200,4672),[
            line('Clipped',[10,78,100,118]),line('Same',[10,1800,80,1820])])]
    page=merge_fragments(fragments)
    assert [row['text'] for row in page]==['Same','Intact','Same']
    assert page[1]['bbox']==[10,2350,100,2390]
    assert page[2]['polygon']==[[10,4072],[80,4072],[80,4092],[10,4092]]


def test_fragment_order_keeps_columns_between_full_width_heading_and_footer():
    from app.ocr_fragments import merge_fragments
    rows=merge_fragments([
        ((0,0,1000,2400),[line('Heading',[0,0,1000,40]),
                           line('Left top',[0,200,400,240]),line('Right top',[600,200,1000,240])]),
        ((0,2272,1000,4000),[line('Left bottom',[0,200,400,240]),
                              line('Right bottom',[600,200,1000,240]),line('Footer',[0,1600,1000,1640])])])
    assert [row['text'] for row in rows]==['Heading','Left top','Left bottom','Right top','Right bottom','Footer']


def long_image():
    image=Image.new('RGB',(200,3000),'white')
    draw=ImageDraw.Draw(image)
    for box in [(10,100,100,120),(10,2350,100,2370),(10,2800,100,2820)]:
        draw.rectangle(box,fill='black')
    return image


@pytest.mark.parametrize('first_detection',[False,True])
def test_split_before_detector_masks_overlap_handwriting_before_any_printed_ocr(first_detection):
    ocr=DocumentOCR.__new__(DocumentOCR)
    detections=iter([[{'kind':'handwritten','bbox':[10,2350,101,2371],
                       'detections':[{'bbox':[10,2350,101,2371]}]}] if first_detection else [],
                     [{'kind':'handwritten','bbox':[10,78,101,99],
                       'detections':[{'bbox':[10,78,101,99]}]}]])
    def detect(image):
        assert max(image.size)<=2400
        return next(detections)
    def recognize(image,cancelled):
        assert max(image.size)<=2400
        # Both overlapping views of the prohibited ink are blank before OCR.
        y=2350 if image.height==2400 else 78
        assert image.getpixel((20,y+5))==(255,255,255)
        return [line('Top',[10,100,100,120])] if image.height==2400 else [line('Bottom',[10,528,100,548])]
    def forbidden(*args):
        pytest.fail('Handwriting OCR must not run without permission')
    ocr.detect_handwriting=detect
    ocr.recognize=recognize
    ocr.transcribe=forbidden
    page=ocr.finish_page(ocr.prepare_image(long_image(),'skip_handwriting'),Event())
    assert page['text']==f'Top\n{SKIP_TEXT}\nBottom\n'
    assert page['regions'][1]['bbox']==[10,2350,101,2371]
    assert page['regions'][1]['detections'][0]['bbox']==[10,2350,101,2371]
    assert page['regions'][2]['bbox']==[10,2800,100,2820]
    for region in page['regions']:
        assert page['text'][region['start']:region['end']]==region['text']


def test_clipped_overlap_line_is_replaced_by_intact_line_from_next_fragment():
    from app.ocr_fragments import merge_fragments
    rows=merge_fragments([((0,0,200,2400),[line('Truncated',[10,2380,100,2400])]),
                          ((0,2272,200,3000),[line('Full line',[10,108,100,138])])])
    assert rows==[line('Full line',[10,2380,100,2410])]


def test_complete_mode_transcribes_overlap_handwriting_once_in_original_coordinates():
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.detect_handwriting=lambda image:[{'kind':'handwritten',
        'bbox':[10,2350,101,2371] if image.height==2400 else [10,78,101,99]}]
    ocr.recognize=lambda image,cancelled:[]
    calls=[]
    def transcribe(image,cancelled):
        calls.append(image.size)
        return 'Handwritten note'
    ocr.transcribe=transcribe
    page=ocr.finish_page(ocr.prepare_image(long_image(),'complete'),Event())
    assert page['text']=='Handwritten note\n'
    assert page['regions'][0]['polygon']==[[10,2350],[101,2350],[101,2371],[10,2371]]
    assert calls==[(91,21)]


def test_empty_middle_fragment_does_not_invoke_native_recognition():
    image=Image.new('RGB',(200,6900),'white')
    draw=ImageDraw.Draw(image)
    draw.rectangle((10,100,100,120),fill='black')
    draw.rectangle((10,6800,100,6820),fill='black')
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.detect_handwriting=lambda image:[]
    results=iter([[line('First',[10,100,100,120])],[line('Last',[10,2256,100,2276])]])
    def recognize(image,cancelled):
        return next(results)
    ocr.recognize=recognize
    page=ocr.finish_page(ocr.prepare_image(image,'skip_handwriting'),Event())
    assert page['text']=='First\nLast\n'
    assert page['regions'][1]['bbox']==[10,6800,100,6820]


def test_masked_handwriting_does_not_turn_gray_paper_into_printed_ink():
    image=Image.new('RGB',(200,3000),(240,240,240))
    ImageDraw.Draw(image).rectangle((10,2350,100,2370),fill='black')
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.detect_handwriting=lambda image:[{'kind':'handwritten',
        'bbox':[10,2350,101,2371] if image.height==2400 else [10,78,101,99]}]
    def forbidden(*args):
        pytest.fail('Paper cannot become foreground after prohibited handwriting is masked')
    ocr.recognize=forbidden
    ocr.transcribe=forbidden
    page=ocr.finish_page(ocr.prepare_image(image,'skip_handwriting'),Event())
    assert page['text']==SKIP_TEXT+'\n'


@pytest.mark.parametrize('failure',['cancel','error'])
def test_fragment_failure_never_returns_partial_page(failure):
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.detect_handwriting=lambda image:[]
    cancelled=Event()
    calls=[]
    def recognize(image,event):
        calls.append(image.size)
        if len(calls)==1:
            if failure=='cancel':event.set()
            return [line('Partial page',[10,100,100,120])]
        raise AccessError('ocr_truncated',422)
    ocr.recognize=recognize
    with pytest.raises(AccessError,match='document_processing_cancelled' if failure=='cancel' else 'ocr_truncated'):
        ocr.finish_page(ocr.prepare_image(long_image(),'skip_handwriting'),cancelled)
    assert len(calls)==(1 if failure=='cancel' else 2)


def test_actual_native_long_image_keeps_seam_once_and_original_coordinates(tmp_path):
    from PIL import ImageFont
    image=Image.new('RGB',(1000,3000),'white')
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',40)
    for text,y in [('Budget 7319',100),('Invoice 4286',2340),('Budget 7319',2800)]:
        draw.text((80,y),text,font=font,fill='black')
    image.save(tmp_path/'long-printed-input.png')
    ocr=DocumentOCR()
    try:
        page=ocr.finish_page(ocr.prepare_image(image,'skip_handwriting'),Event())
    finally:
        ocr.close()
    import json
    (tmp_path/'long-printed-result.json').write_text(json.dumps(page,ensure_ascii=False,indent=2))
    assert page['text'].count('7319')==2,page
    assert page['text'].count('4286')==1,page
    assert not any(row['kind']=='skip' for row in page['regions']),page
    seam=next(row for row in page['regions'] if '4286' in row['text'])
    assert 2320<=seam['bbox'][1]<seam['bbox'][3]<=2400,page
    assert any(row['bbox'][1]>2750 and '7319' in row['text'] for row in page['regions']),page
    for region in page['regions']:
        assert page['text'][region['start']:region['end']]==region['text']
    print({'proof':'actual_native_fragment_overlap_original_geometry','page':page},flush=True)
