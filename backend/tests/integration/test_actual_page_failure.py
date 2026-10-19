"""Twenty real native OCR pages: a failure-only hook after fifteen successes.

No successful OCR output or ready publication is fabricated. Both original
and explicit print-only mode use a genuine embedded handwritten source raster.
"""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image,ImageDraw,ImageFont
import psycopg
from psycopg.rows import dict_row
from playwright.sync_api import expect
import pytest

from integration.test_answer_lifecycle import environment,integrated_browser,operator
from browser.test_accounts import BACKEND,real_account_browser,register,login, navigate, open_sources
from browser.test_documents import ready


@pytest.fixture
def real_document_browser(real_account_browser,tmp_path):
    hook=tmp_path/'fault-documents.py';trace=tmp_path/'actual-finished-pages.jsonl'
    hook.write_text(f'''import json
from pathlib import Path
from app.ocr import DocumentOCR
from app.auth import AccessError
original_prepare=DocumentOCR.prepare_page
original_finish=DocumentOCR.finish_page
trace=Path({str(trace)!r})
def prepare(self,path,number,mode):
    if number==16:raise AccessError('u8_controlled_page_fault',422)
    return original_prepare(self,path,number,mode)
def finish(self,prepared,cancelled):
    result=original_finish(self,prepared,cancelled)
    with trace.open('a') as output:output.write(json.dumps({{'text':result['text'],'regions':result['regions'],'mode':prepared['mode'],'skips':prepared['skips']}},ensure_ascii=False)+'\\n')
    return result
DocumentOCR.prepare_page=prepare
DocumentOCR.finish_page=finish
from app.document_worker import main
main()
''')
    path=tmp_path/'document-worker.log'
    with path.open('xb') as stream:
        worker=subprocess.Popen([sys.executable,str(hook)],cwd=BACKEND,env=os.environ.copy(),stdout=stream,stderr=subprocess.STDOUT)
        try:yield real_account_browser,worker,path
        finally:
            worker.terminate()
            try:worker.wait(20)
            except subprocess.TimeoutExpired:worker.kill();worker.wait(10)


def twenty_mixed_pages():
    genuine=Image.open(BACKEND.parent/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/real-handwritten-title-author-input-v1.png').convert('RGB')
    page=Image.new('RGB',(640,640),'white');page.paste(genuine,(130,100))
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
    ImageDraw.Draw(page).text((35,400),'The annual budget is 100 euros.',font=font,fill='black')
    output=BytesIO();page.save(output,format='PDF',resolution=150,save_all=True,append_images=[page.copy() for _ in range(19)])
    return output.getvalue()


@pytest.mark.parametrize('skip',[False,True],ids=['whole-pdf','explicit-print-only'])
def test_actual_twenty_page_failure_excludes_fifteen_native_successes_and_keeps_neighbor(integrated_browser,environment,tmp_path,skip):
    ((browser,mailbox,frontend,_),worker,_),_,_=integrated_browser
    contexts=[browser.new_context(),browser.new_context()]
    try:
        admin,owner=[context.new_page() for context in contexts]
        operator(admin,mailbox,frontend)
        email='u8-page-failure@owned.test';register(owner,mailbox,frontend,email);login(owner,email)
        if skip:
            navigate(admin,'administration')
            admin.reload();card=admin.locator('article').filter(has=admin.locator(f'form[data-account="{email}"]'));card.locator('summary').click()
            policy=card.locator('form[data-policy]');policy.locator('[name=handwriting]').uncheck()
            policy.get_by_role('button',name='Сохранить ограничения документов').click()
            expect(admin.locator('#status')).to_have_text('Ограничения документов сохранены.')
        content=twenty_mixed_pages();(tmp_path/'actual-twenty-page-original.pdf').write_bytes(content)
        navigate(owner,'library')
        owner.locator('#document-upload input').set_input_files([
            {'name':'twenty-mixed.pdf','mimeType':'application/pdf','buffer':content},
            {'name':'healthy-neighbor.txt','mimeType':'text/plain','buffer':b'The current annual budget is 10 euros.'}])
        owner.get_by_role('button',name='Загрузить документы',exact=True).click()
        bad=owner.locator('#documents li').filter(has=owner.get_by_text('twenty-mixed.pdf',exact=True))
        if skip:
            expect(bad).to_contain_text('OCR рукописей не разрешён')
            bad.get_by_role('button',name='Загрузить только печатный текст',exact=True).click()
        # Measured fixed CPU models take about 70–80 seconds per complete
        # page here. Keep a finite bound sufficient for fifteen real pages.
        deadline=time.monotonic()+2000
        while 'Обработка неуспешна' not in bad.inner_text():
            assert worker.poll() is None and time.monotonic()<deadline,bad.inner_text()
            try:
                # A read may consume the configured30s timeout before a manual
                # retry becomes available; give that transition its own margin.
                owner.get_by_role('button',name='Обновить статусы документов',exact=True).click(timeout=45000)
            except Exception:
                with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                    activity=connection.execute("SELECT pid,state,wait_event_type,wait_event,query,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE datname=current_database() ORDER BY pid").fetchall()
                    files=connection.execute('SELECT name,state,error,failure_page FROM document_files').fetchall()
                (tmp_path/'actual-refresh-stall-diagnostic.json').write_text(json.dumps({'activity':activity,'files':files,
                    'worker_alive':worker.poll() is None,'source_inputs_unchanged':True,
                    'browser':owner.evaluate('''() => ({timeout:document.querySelector('meta[name=request-timeout-ms]').content,
                      library:document.querySelector('#library-status').textContent,status:document.querySelector('#status').textContent,
                      refresh:document.querySelector('#refresh-documents').outerHTML})''')},default=str,ensure_ascii=False,indent=2)+'\n')
                raise
            owner.wait_for_timeout(250)
        expect(bad).to_contain_text('страница 16')
        bad.get_by_role('button',name='Открыть отчёт об обработке',exact=True).click()
        report=owner.get_by_role('dialog',name='Отчёт об обработке документа')
        expect(report).to_contain_text('twenty-mixed.pdf')
        expect(report).to_contain_text('Этап: обработка документа')
        expect(report).to_contain_text('Страница: 16')
        expect(report).to_contain_text('Причина: u8_controlled_page_fault')
        expect(report).to_contain_text('Документ целиком недоступен для поиска.')
        if skip:expect(report).to_contain_text('Режим: только печатный текст; рукописные участки пропущены.')
        owner.screenshot(path=str(tmp_path/'actual-page-16-failure-report.png'),full_page=True)
        report.get_by_role('button',name='Закрыть отчёт',exact=True).click()
        ready(owner,'healthy-neighbor.txt',timeout=300)
        pages=[json.loads(line) for line in (tmp_path/'actual-finished-pages.jsonl').read_text().splitlines()]
        assert len(pages)==15 and all('100' in page['text'] for page in pages),pages
        if skip:
            assert all(page['mode']=='skip_handwriting' and page['skips'] and 'Рукописный текст пропущен.' in page['text'] for page in pages),pages
            assert all('dreams' not in page['text'].casefold() and 'hughes' not in page['text'].casefold() for page in pages)
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            bad_row=connection.execute("SELECT d.*,f.state,f.failure_page,f.mode,f.original_sha256 FROM documents d JOIN document_files f ON f.document_id=d.id WHERE f.name='twenty-mixed.pdf'").fetchone()
            assert not bad_row['ready'] and not bad_row['published_revision'] and bad_row['failure_page']==16 and bad_row['state']=='failed'
            assert bad_row['original_sha256']==hashlib.sha256(content).hexdigest()
            assert not connection.execute('SELECT 1 FROM available_source_revisions WHERE document_id=%s',(bad_row['id'],)).fetchone()
            assert connection.execute('SELECT count(*) AS n FROM document_page_texts p JOIN source_revisions r ON r.id=p.revision_id WHERE r.document_id=%s',(bad_row['id'],)).fetchone()['n']==15
        navigate(owner,'chat')
        open_sources(owner)
        for checkbox in owner.locator('#question-sources input').all():checkbox.uncheck()
        # Failed files are deliberately absent from selectable ready sources.
        open_sources(owner)
        assert owner.get_by_role('checkbox',name='twenty-mixed.pdf',exact=True).count()==0
        api=integrated_browser[0][0][3]
        refused=owner.evaluate('''async ({api,document})=>{
            const tab=JSON.parse(sessionStorage.getItem('rag:tab'));
            const response=await fetch(api+'/api/conversations/'+sessionStorage.getItem('rag:conversation')+'/answers',{
                method:'POST',headers:{Authorization:'Bearer '+sessionStorage.getItem('rag:credential'),
                    'X-Tab-Proof':tab.proof,'Content-Type':'application/json'},
                body:JSON.stringify({operation_key:crypto.randomUUID(),question:'What is the annual budget?',
                    document_ids:[document],tab_id:tab.id})});
            return {status:response.status,body:await response.json()};
        }''',{'api':api,'document':str(bad_row['id'])})
        assert refused=={'status':409,'body':{'error':'no_ready_sources'}},refused
        navigate(owner,'chat')
        owner.locator('#question').fill('What is the annual budget?')
        owner.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(owner.locator('#history article')).to_contain_text('Завершён',timeout=180000)
        navigate(owner,'chat')
        open_sources(owner)
        owner.get_by_role('checkbox',name='healthy-neighbor.txt',exact=True).check()
        owner.locator('#question').fill('What is the annual budget?')
        owner.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(owner.locator('#history article')).to_have_count(2)
        expect(owner.locator('#history article').last).to_contain_text('Завершён',timeout=180000)
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            requests=connection.execute('SELECT * FROM requests ORDER BY created_at').fetchall()
            assert len(requests)==2
            assert [request['passport']['scope_mode'] for request in requests]==['all','selected']
            for request in requests:
                assert all(row['document_id']!=str(bad_row['id']) for row in request['passport']['available']+request['passport']['passed'])
                assert all('100' not in fragment['text'] for fragment in request['passport']['passed'])
                assert '10' in request['answer_text']
            request=requests[-1]
            assert str(bad_row['id']) not in request['passport']['selected']
            assert all(row['document_id']!=str(bad_row['id']) for row in request['passport']['available']+request['passport']['passed'])
            assert all('100' not in fragment['text'] for fragment in request['passport']['passed'])
            assert '10' in request['answer_text']
        owner.bring_to_front();owner.screenshot(path=str(tmp_path/'whole-file-failed-report.png'),full_page=True)
        print(json.dumps({'proof':'actual_twenty_page_atomic_failure','skip':skip,'completed_actual_native_pages':15,'failure_page':16,'original_sha256':bad_row['original_sha256'],'request_id':str(request['id']),'passport':request['passport']},default=str,ensure_ascii=False),flush=True)
    finally:
        for context in contexts:context.close()
