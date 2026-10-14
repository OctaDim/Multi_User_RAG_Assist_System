"""Actual four-language Paddle publication and masked PDF/DOCX source links."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import time
from zipfile import ZipFile

from playwright.sync_api import expect
from PIL import Image

from integration.test_answer_lifecycle import environment,operator
from integration.test_multilingual_documents import real_document_browser,strict_ocr_tokens,be_exception,CURRENT_PRINTED
from browser.test_accounts import BACKEND,real_account_browser,register,login
from browser.test_documents import ready
from app.ocr import SKIP_TEXT


PROOF=BACKEND.parent/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof'


def test_actual_four_language_printed_pdf_docx_and_forbidden_hand_pixels(real_document_browser,tmp_path):
    (browser,mailbox,frontend,api),worker,log=real_document_browser
    contexts=[browser.new_context(),browser.new_context()]
    try:
        admin,owner=[context.new_page() for context in contexts]
        operator(admin,mailbox,frontend)
        email='u8-printed-four-languages@owned.test';register(owner,mailbox,frontend,email);login(owner,email)
        admin.reload();card=admin.locator('article').filter(has=admin.locator(f'form[data-account="{email}"]'));card.locator('summary').click()
        policy=card.locator('form[data-policy]');policy.locator('[name=handwriting]').uncheck()
        policy.get_by_role('button',name='Сохранить ограничения документов',exact=True).click()
        expect(admin.locator('#status')).to_have_text('Ограничения документов сохранены.')
        package=BytesIO()
        with ZipFile(package,'w') as archive:
            archive.writestr('[Content_Types].xml','''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>''')
            archive.writestr('_rels/.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>''')
            archive.writestr('word/_rels/document.xml.rels','''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/printed.png"/></Relationships>''')
            archive.writestr('word/document.xml','''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body><w:p><w:r><w:t>Original DOCX body.</w:t></w:r></w:p><w:p><w:r><w:drawing><wp:inline><wp:extent cx="5029200" cy="5867400"/><wp:docPr id="1" name="Four language printed source"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="printed.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="5029200" cy="5867400"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p></w:body></w:document>''')
            archive.writestr('word/media/printed.png',(PROOF/'printed-four-languages-v1.png').read_bytes())
        gray_image=Image.open(PROOF/'printed-four-languages-v1.png').convert('L').point(lambda value:128 if value<180 else 255)
        gray_png=BytesIO();gray_image.save(gray_png,format='PNG')
        gray_package=BytesIO()
        with ZipFile(BytesIO(package.getvalue())) as original,ZipFile(gray_package,'w') as archive:
            for name in original.namelist():
                archive.writestr(name,gray_png.getvalue() if name=='word/media/printed.png' else original.read(name))
        samples=[('four-language.pdf',(PROOF/'printed-four-languages-v1.pdf').read_bytes(),False),
                 ('mixed-four-language.pdf',(PROOF/'mixed-real-title-fixture-v1.pdf').read_bytes(),True),
                 ('printed-four-language.docx',package.getvalue(),False),
                 ('gray-printed-four-language.docx',gray_package.getvalue(),False)]
        gt=json.loads((PROOF/'printed-four-languages-v1.json').read_text())['expected_lines']
        expected_tokens=[(word,language) for language,line in zip(['en','en','de','ru','be'],gt) for word in strict_ocr_tokens(line)]
        records=[]
        for name,content,has_hand in samples:
            owner.locator('#document-upload input').set_input_files({'name':name,'mimeType':'application/octet-stream','buffer':content})
            owner.get_by_role('button',name='Загрузить документы',exact=True).click()
            item=owner.locator('#documents li').filter(has=owner.get_by_text(name,exact=True))
            if name.endswith('.pdf'):
                until=time.monotonic()+30
                while 'OCR рукописей не разрешён' not in item.inner_text():
                    assert worker.poll() is None and time.monotonic()<until,item.inner_text()
                    owner.get_by_role('button',name='Обновить статусы документов',exact=True).click();owner.wait_for_timeout(100)
                item.get_by_role('button',name='Загрузить только печатный текст',exact=True).click()
            item=ready(owner,name,timeout=180);identifier=item.get_attribute('data-document')
            credential=owner.evaluate("sessionStorage.getItem('rag:credential')")
            result=owner.evaluate('''async ({api,credential,id})=>{
                const headers={Authorization:'Bearer '+credential};
                const result=await(await fetch(api+'/api/documents/'+id,{headers})).json();
                const original=new Uint8Array(await(await fetch(api+'/api/documents/'+id+'/original',{headers})).arrayBuffer());
                return {result,original:Array.from(original)};
            }''',{'api':api,'credential':credential,'id':identifier})
            assert bytes(result['original'])==content
            pages=result['result']['pages'];page=pages[-1]
            text=page['text'].replace(SKIP_TEXT,'')
            raw_tokens=strict_ocr_tokens(text)
            assert len(raw_tokens)==len(expected_tokens),{'name':name,'recognized':page['text'],'expected':gt}
            actual_mask=json.loads((tmp_path/'actual-pre-recognition-masks.jsonl').read_text().splitlines()[-1])
            assert tuple(actual_mask['printed_identity'])==CURRENT_PRINTED
            comparisons=[]
            for (source,language),raw in zip(expected_tokens,raw_tokens):
                exception=be_exception(language,'printed','printed',actual_mask['printed_identity'],source=source,raw=raw)
                assert source==raw or exception,{'source':source,'raw':raw,'language':language}
                comparisons.append({'source':source,'raw':raw,'language':language,'source_kind':'printed',
                                    'permitted_difference':source!=raw,'exception':exception if source!=raw else None})
            regions=page['regions']
            assert all(row['kind'] in ['printed','skip'] for row in regions)
            assert all(row['polygon'] and 0<=row['bbox'][0]<row['bbox'][2] and 0<=row['bbox'][1]<row['bbox'][3] for row in regions if row['kind']=='printed')
            if has_hand:
                assert page['text'].count(SKIP_TEXT)==2 and 'dreams' not in page['text'].casefold() and 'hughes' not in page['text'].casefold()
            if name.endswith('.docx'):
                assert len(pages)==2 and pages[0]['text'].strip()=='Original DOCX body.'
            item.get_by_role('button',name='Открыть документ',exact=True).click()
            expect(owner.locator('#document-correction textarea').last).to_have_value(re.compile('The annual budget is 100 euros.'))
            records.append({'name':name,'text':page['text'],'regions':regions,'words_and_punctuation':comparisons,
                            'original_sha256':hashlib.sha256(content).hexdigest()})
            (tmp_path/'actual-printed-four-language-results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
        masks=[json.loads(line) for line in (tmp_path/'actual-pre-recognition-masks.jsonl').read_text().splitlines()]
        assert len(masks)==4 and masks[1]['mode']=='skip_handwriting' and len(masks[1]['skips'])==2,masks
        assert all(not mask['handwriting'] and not mask['skips'] for mask in masks[2:]),masks
        assert worker.poll() is None
        (tmp_path/'actual-printed-four-language-results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'proof':'actual_issued_four_language_Paddle_pdf_docx_originals_true_LOC_forbidden_hand_pixels','results':records,'worker_log':str(log)},ensure_ascii=False),flush=True)
    finally:
        for context in contexts:context.close()
