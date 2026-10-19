"""U8 genuine handwritten input proofs, separate from the frozen RAG30 controls."""
from io import BytesIO
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import unicodedata

from PIL import Image
from playwright.sync_api import expect
import pytest

from integration.test_answer_lifecycle import environment, operator
from browser.test_accounts import BACKEND, real_account_browser, register, login, navigate
from browser.test_documents import ready


FIXTURES=BACKEND/'tests/fixtures/answer_lifecycle'
ENGLISH=BACKEND.parent/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/real-handwritten-title-author-input-v1.png'
CONTRACT='harness/project/decisions/2026-10-14-ocr-word-types-and-model-specific-exceptions.md'
CURRENT_PRINTED=('299051d54faa065abc505cc39b8383ea338fd3020c775ea3e0ba514a7022328c',
                 'e7f1a72400fba517046f90d964e2fa0f4dac7781ee3b1bc5d2022f5f8cecbd87')
CURRENT_HANDWRITING=('aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223',
                     '7035e9cb8d7c6a9681d07eef9a364783e86ea4cd73faab2eabb4f43a101830c7')


def strict_ocr_tokens(text):
    return re.findall(r'\w+|[^\w\s]',text)


@pytest.mark.parametrize('raw',['die Seerose blüht auf dem Teich.','Die Seerose blüht auf dem Teich?',
                               'Die Seerose blüht auf dem Teich','Die Seerose blüht auf dem Teich. extra'])
def test_strict_ocr_acceptance_rejects_case_punctuation_and_added_text(raw):
    assert strict_ocr_tokens(raw)!=strict_ocr_tokens('Die Seerose blüht auf dem Teich.')


def printed_be_glyphs_match(source,raw):
    def clusters(text):
        values=[]
        for char in text:
            if unicodedata.category(char).startswith('M') and values:values[-1]+=char
            else:values.append(char)
        return values
    expected,actual=clusters(source),clusters(raw)
    if len(expected)!=len(actual):return False
    for original,recognized in zip(expected,actual):
        if original==recognized:continue
        if original not in ('ў','і','i'):return False
        variant=unicodedata.normalize('NFD',recognized)
        bases=('у',) if original=='ў' else ('і','i')
        if original in ('і','i') and len(variant)==1:return False
        if variant[0] not in bases or any(unicodedata.combining(char) not in (214,216,228,230,232,234) for char in variant[1:]):return False
    return True


def be_exception(language,role,source_kind,identity,*,source=None,raw=None):
    """User permission belongs to these exact bytes and the original source type."""
    if language!='be':return None
    if role=='printed' and source_kind=='printed' and tuple(identity)==CURRENT_PRINTED:
        if source is not None and raw is not None and printed_be_glyphs_match(source,raw):
            return 'current_Paddle_BE_printed_only_u_i_glyph_variants'
    if role=='handwriting' and source_kind=='handwritten' and tuple(identity)==CURRENT_HANDWRITING:
        return 'current_Qwen_BE_handwriting'
    return None


def test_current_be_word_permissions_are_strict_outside_exact_model_and_source_type():
    for raw in ['у музеї','у\u030c музеi\u0308']:
        assert be_exception('be','printed','printed',CURRENT_PRINTED,source='ў музеі',raw=raw)=='current_Paddle_BE_printed_only_u_i_glyph_variants'
        assert be_exception('be','handwriting','printed',CURRENT_HANDWRITING,source='ў музеі',raw=raw) is None
        assert be_exception('be','printed','handwritten',CURRENT_PRINTED,source='ў музеі',raw=raw) is None
    for raw in ['у школе','у музеї 1905','у\u030c музэї','у музеі\u0308\u0430','у\u0323 музеї','у музеi']:
        assert be_exception('be','printed','printed',CURRENT_PRINTED,source='ў музеі',raw=raw) is None
    assert be_exception('be','printed','printed',('future-model',CURRENT_PRINTED[1]),source='ў музеі',raw='у музеї') is None
    assert be_exception('be','printed','printed',(CURRENT_PRINTED[0],'future-projector'),source='ў музеі',raw='у музеї') is None
    assert be_exception('be','handwriting','handwritten',('future-model','future-projector'),source='слова',raw='іншае') is None
    # Both independently typed words share one hypothetical handwriting ROI;
    # the frame/model prediction cannot transfer the handwriting permission.
    same_crop=[{'source_kind':'handwritten','source':'слова','raw':'іншае'},
               {'source_kind':'printed','source':'ў','raw':'у'}]
    allowed=[be_exception('be','handwriting',word['source_kind'],CURRENT_HANDWRITING,
                         source=word['source'],raw=word['raw']) for word in same_crop]
    assert allowed==['current_Qwen_BE_handwriting',None]
    assert not printed_be_glyphs_match('möchte','mochte')


@pytest.fixture
def real_document_browser(real_account_browser,tmp_path):
    """Observe real prepared pixels before calling the real native recognizer."""
    hook=tmp_path/'observe-masks.py'
    hook.write_text(f'''import hashlib,json,os
from pathlib import Path
from app.ocr import DocumentOCR
original=DocumentOCR.finish_page
original_transcribe=DocumentOCR.transcribe
trace=Path({str(tmp_path/'actual-pre-recognition-masks.jsonl')!r})
identities={{}}
def identity(model,projector):
    paths=(model,projector)
    if paths not in identities:
        identities[paths]=[]
        for path in paths:
            with open(path,'rb') as source:identities[paths].append(hashlib.file_digest(source,'sha256').hexdigest())
    return identities[paths]
def finish(self,prepared,cancelled):
    self.observed_source_mode=prepared['mode']
    self.observed_handwriting_calls=[]
    image=prepared['image']
    for region in prepared['handwriting']:
        x0,y0,x1,y1=region['bbox']
        assert image.crop((x0,y0,x1,y1)).getextrema()==((255,255),(255,255),(255,255))
    record={{'mode':prepared['mode'],'image_sha256':hashlib.sha256(image.tobytes()).hexdigest(),
        'size':image.size,'skips':prepared['skips'],'handwriting':prepared['handwriting'],
        'printed_model':self.model.model_path,'handwriting_model':self.handwriting_model.model_path,
        'printed_identity':identity(self.model.model_path,str(Path(os.environ['RAG_OCR_DIR'])/'PaddleOCR-VL-1.5-mmproj.gguf')),
        'handwriting_identity':identity(self.handwriting_model.model_path,str(Path(os.environ['RAG_OCR_DIR'])/'mmproj-F16.gguf'))}}
    with trace.open('a') as out:out.write(json.dumps(record,ensure_ascii=False)+'\\n')
    result=original(self,prepared,cancelled)
    with (trace.parent/'actual-printed-texts.jsonl').open('a') as out:
        out.write(json.dumps({{'mode':prepared['mode'],'printed_text':' '.join(row['text'] for row in result['regions'] if row['kind']=='printed'),
            'handwritten_text':' '.join(row['text'] for row in result['regions'] if row['kind']=='handwritten'),
            'handwriting_calls':self.observed_handwriting_calls,'regions':result['regions']}},ensure_ascii=False)+'\\n')
    return result
def transcribe(self,image,cancelled=None):
    assert self.observed_source_mode=='complete'
    self.observed_handwriting_calls.append({{'mode':self.observed_source_mode,'size':image.size,
        'sha256':hashlib.sha256(image.tobytes()).hexdigest()}})
    return original_transcribe(self,image,cancelled)
DocumentOCR.finish_page=finish
DocumentOCR.transcribe=transcribe
from app.document_worker import main
main()
''')
    log=tmp_path/'document-worker.log'
    with log.open('xb') as stream:
        worker=subprocess.Popen([sys.executable,str(hook)],cwd=BACKEND,env=os.environ.copy(),stdout=stream,stderr=subprocess.STDOUT)
        try:yield real_account_browser,worker,log
        finally:
            worker.terminate()
            try:worker.wait(20)
            except subprocess.TimeoutExpired:worker.kill();worker.wait(10)


def raster_pdf(path):
    """Faithful source-raster placement on white page; no handwriting synthesis."""
    original=Image.open(path).convert('RGB')
    image=original.copy()
    if image.width>616:
        image=image.resize((616,round(image.height*616/image.width)),Image.Resampling.LANCZOS)
    canvas=Image.new('RGB',(640,640),'white')
    canvas.paste(image,((640-image.width)//2,(640-image.height)//2))
    output=BytesIO();canvas.save(output,format='PDF',resolution=150)
    return output.getvalue()


def test_genuine_four_language_handwriting_publication_and_permission_masks(real_document_browser,tmp_path):
    (browser,mailbox,frontend,_),worker,log=real_document_browser
    strict_gt={row['language']:row for row in json.loads((FIXTURES/'handwriting-strict-gt-v1.json').read_text())}
    for row in strict_gt.values():
        assert hashlib.sha256((BACKEND.parent/row['source']).read_bytes()).hexdigest()==row['source_sha256']
    samples=[('en',raster_pdf(ENGLISH),['dreams','langston','hughes']),
             ('ru',raster_pdf(FIXTURES/'handwritten-ru-august.png'),['август']),
             ('de',raster_pdf(FIXTURES/'handwritten-de-row5.jpg'),['die','seerose','blüht','auf','dem','teich']),
             ('be',(FIXTURES/'handwritten-be-kupala.pdf').read_bytes(),['беларусы','крыўду','людзьмі'])]
    contexts=[browser.new_context() for _ in range(2)]
    records=[]
    try:
        admin,owner=[context.new_page() for context in contexts]
        operator(admin,mailbox,frontend)
        register(owner,mailbox,frontend,'u8-genuine-handwriting@owned.test');login(owner,'u8-genuine-handwriting@owned.test')
        for language,content,expected in samples:
            name=f'genuine-{language}.pdf'
            navigate(owner,'library')
            owner.locator('#document-upload input').set_input_files({'name':name,'mimeType':'application/pdf','buffer':content})
            owner.get_by_role('button',name='Загрузить документы',exact=True).click()
            item=ready(owner,name,timeout=240)
            item.get_by_role('button',name='Открыть документ',exact=True).click()
            text=owner.locator('#document-correction textarea').input_value()
            missing=[word for word in expected if word not in text.casefold()]
            records.append({'language':language,'expected_legible_source':expected,'recognized':text,'missing':missing,'actual_words':re.findall(r'\w+',text.casefold()),
                'source_kind':'handwritten','acceptance':'pending_actual_identity_and_source_kind',
                'original_sha256':hashlib.sha256(content).hexdigest()})
            print(json.dumps(records[-1],ensure_ascii=False),flush=True)
        # Independent source GT was recorded before recognition. Retain every
        # raw result even if a candidate fails one language.
        result_path=tmp_path/'genuine-handwriting-results.json'
        result_path.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
        admin.reload()
        navigate(admin,'administration')
        card=admin.locator('article').filter(has=admin.locator('form[data-account="u8-genuine-handwriting@owned.test"]'))
        card.locator('summary').click()
        policy=card.locator('form[data-policy]');policy.locator('[name=handwriting]').uncheck()
        policy.get_by_role('button',name='Сохранить ограничения документов').click()
        expect(admin.locator('#status')).to_have_text('Ограничения документов сохранены.')
        for language,content,forbidden in samples:
            name=f'forbidden-{language}.pdf'
            navigate(owner,'library')
            owner.locator('#document-upload input').set_input_files({'name':name,'mimeType':'application/pdf','buffer':content})
            owner.get_by_role('button',name='Загрузить документы',exact=True).click()
            item=owner.locator('#documents li').filter(has=owner.get_by_text(name,exact=True))
            expect(item).to_contain_text('OCR рукописей не разрешён')
            item.get_by_role('button',name='Загрузить только печатный текст',exact=True).click()
            item=ready(owner,name,timeout=240);item.get_by_role('button',name='Открыть документ',exact=True).click()
            text=owner.locator('#document-correction textarea').input_value()
            assert 'Рукописный текст пропущен.' in text, {'language':language,'recognized':text}
            assert all(word not in text.casefold() for word in forbidden),{'language':language,'recognized':text}
        assert worker.poll() is None
        printed=[json.loads(line) for line in (tmp_path/'actual-printed-texts.jsonl').read_text().splitlines()]
        footer=json.loads((BACKEND.parent/'harness/project/testing/evidence/work/2026-10-14-answer-lifecycle-u8-integration/2026-10-14-parent-be-printed-footer-independent-gt-v1.json').read_text())['printed_footer_exact']
        assert len(printed)==8
        assert all(not row['handwriting_calls'] and not row['handwritten_text'] for row in printed[4:]),printed
        assert all(not row['printed_text'] for index,row in enumerate(printed) if index%4!=3),printed
        masks=[json.loads(line) for line in (tmp_path/'actual-pre-recognition-masks.jsonl').read_text().splitlines()]
        assert len(masks)==8 and all(row['skips'] for row in masks[4:]),masks
        assert all(Path(row['printed_model']).samefile(Path(os.environ['RAG_OCR_DIR'])/'PaddleOCR-VL-1.5.gguf') and Path(row['handwriting_model']).samefile(os.environ['RAG_MODEL_PATH']) for row in masks)
        assert all(tuple(row['printed_identity'])==CURRENT_PRINTED and tuple(row['handwriting_identity'])==CURRENT_HANDWRITING for row in masks),masks
        # Original BE handwriting ends above the independently read printed
        # footer (y1112). Its words never enter the Qwen handwriting allowance.
        assert all(region['bbox'][3]<1100 for region in masks[3]['handwriting']),masks[3]
        footer_records=[]
        for index in [3,7]:
            raw=printed[index]['printed_text'];identity=masks[index]['printed_identity']
            source_words,raw_words=footer.split(),raw.split()
            assert len(source_words)==len(raw_words),{'source':footer,'raw':raw}
            words=[]
            for source_word,raw_word in zip(source_words,raw_words):
                exact=source_word==raw_word
                exception=be_exception('be','printed','printed',identity,source=source_word,raw=raw_word)
                assert exact or exception=='current_Paddle_BE_printed_only_u_i_glyph_variants',{'source':source_word,'raw':raw_word}
                words.append({'source':source_word,'raw':raw_word,'actual_source_kind':'printed',
                    'source_kind_basis':'independent original printed footer GT, never predicted region kind',
                    'exact_match':exact,'permitted_difference':not exact,'exception':exception if not exact else None})
            exact=all(word['exact_match'] for word in words)
            footer_records.append({'source_kind':'printed','role':'printed','identity':identity,'original_gt':footer,
                'raw':raw,'exact_match':exact,'permitted_difference':not exact,'words':words,'contract':CONTRACT})
        for index,row in enumerate(records):
            identity=masks[index]['handwriting_identity']
            row['evaluated_raw_handwriting']=printed[index]['handwritten_text']
            row['page_source_kinds']=sorted({region['kind'] for region in printed[index]['regions']})
            row['source_kind_basis']='independently viewed genuine handwritten body; BE printed footer begins y1112, outside all Qwen crops ending y940'
            row['actual_words']=re.findall(r'\w+',row['evaluated_raw_handwriting'])
            row['actual_tokens']=strict_ocr_tokens(row['evaluated_raw_handwriting'])
            row['expected_source_text']=strict_gt[row['language']]['text'] if row['language'] in strict_gt else None
            exception=be_exception(row['language'],'handwriting',row['source_kind'],identity)
            exact=row['expected_source_text'] is not None and row['actual_tokens']==strict_ocr_tokens(row['expected_source_text'])
            assert exact or exception=='current_Qwen_BE_handwriting',records
            row.update({'identity':identity,'acceptance':'exact' if exact else 'user_permitted_current_model_difference',
                'exception':exception,'contract':CONTRACT if exception else None})
        assert be_exception('be','handwriting','handwritten',('future-model','future-projector')) is None
        assert be_exception('be','printed','printed',('future-model','future-projector')) is None
        assert be_exception('be','handwriting','printed',CURRENT_HANDWRITING)!='current_Qwen_BE_handwriting'
        result_path.write_text(json.dumps({'handwriting':records,'printed_footer':footer_records},ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'proof':'actual_ui_issuer_four_language_handwriting_and_pre_recognition_masks',
            'results':str(result_path),'worker_log':str(log)}),flush=True)
    finally:
        for context in contexts:context.close()
