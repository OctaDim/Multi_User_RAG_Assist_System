"""Actual issuer, socket upload interruption and whole published source scope."""
import json
import socket
import time
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from playwright.sync_api import expect

from integration.test_answer_lifecycle import environment,integrated_browser,operator
from browser.test_accounts import real_account_browser,register,login, navigate
from browser.test_documents import real_document_browser,ready


def test_real_partial_upload_and_failed_file_never_expand_selected_source_scope(integrated_browser,environment,tmp_path):
    ((browser,mailbox,frontend,api),worker,worker_log),_,logs=integrated_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'u8-whole-source@owned.test');login(page,'u8-whole-source@owned.test')
        navigate(page,'library')
        page.locator('#document-upload input').set_input_files([
            {'name':'whole-budget.txt','mimeType':'text/plain','buffer':b'The annual budget is 100 euros.'},
            {'name':'broken.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.7\nIncomplete invalid original with no pages'}])
        page.get_by_role('button',name='Загрузить документы',exact=True).click();ready(page,'whole-budget.txt')
        bad=page.locator('#documents li').filter(has=page.get_by_text('broken.pdf',exact=True))
        deadline=time.monotonic()+30
        while 'Обработка неуспешна' not in bad.inner_text():
            assert time.monotonic()<deadline,bad.inner_text()
            page.get_by_role('button',name='Обновить статусы документов',exact=True).click();page.wait_for_timeout(100)
        bad.get_by_role('button',name='Открыть отчёт об обработке',exact=True).click()
        report=page.get_by_role('dialog',name='Отчёт об обработке документа')
        expect(report).to_contain_text('broken.pdf')
        expect(report).to_contain_text('Этап: обработка документа')
        expect(report).to_contain_text('Страница: не определена')
        expect(report).to_contain_text('Причина: Не удалось обработать документ.')
        expect(report).to_contain_text('Документ целиком недоступен для поиска.')
        page.screenshot(path=str(tmp_path/'failed-file-report-desktop.png'),full_page=True)
        page.set_viewport_size({'width':375,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path/'failed-file-report-mobile.png'),full_page=True)
        report.get_by_role('button',name='Закрыть отчёт',exact=True).click()
        expect(report).not_to_be_visible()
        page.set_viewport_size({'width':1280,'height':900})
        token=page.evaluate("sessionStorage.getItem('rag:credential')")
        admitted=page.evaluate('''async ({api,token}) => (await (await fetch(api+'/api/documents/uploads',{method:'POST',
            headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({files:[{name:'interrupted.txt',size:64}]})})).json())''',{'api':api,'token':token})
        identifier=admitted['documents'][0]['id']
        parsed=urlsplit(api)
        with socket.create_connection((parsed.hostname,parsed.port),timeout=10) as stream:
            headers=f'PUT /api/documents/{identifier}/original HTTP/1.1\r\nHost: {parsed.netloc}\r\nAuthorization: Bearer {token}\r\nContent-Length: 64\r\nContent-Type: application/octet-stream\r\n\r\n'
            stream.sendall(headers.encode()+b'partial');stream.shutdown(socket.SHUT_RDWR)
        deadline=time.monotonic()+15
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            while True:
                interrupted=connection.execute('SELECT d.*,f.state,f.error,f.original_sha256 FROM documents d JOIN document_files f ON f.document_id=d.id WHERE d.id=%s',(identifier,)).fetchone()
                if interrupted['state']=='failed':break
                assert time.monotonic()<deadline,interrupted;page.wait_for_timeout(50)
            assert not interrupted['ready'] and not interrupted['published_revision'] and not interrupted['original_sha256']
            files=connection.execute('SELECT d.id,f.name,d.ready,d.published_revision FROM documents d JOIN document_files f ON f.document_id=d.id ORDER BY f.created_at').fetchall()
            assert len(files)==3 and sum(row['ready'] for row in files)==1
        statuses=page.evaluate('''async ({api,token,id}) => await Promise.all(['','/original'].map(async suffix =>
            (await fetch(api+'/api/documents/'+id+suffix,{headers:{Authorization:'Bearer '+token}})).status))''',{'api':api,'token':token,'id':identifier})
        assert statuses==[409,409],statuses
        actor=page.evaluate('''() => ({tab:JSON.parse(sessionStorage.getItem('rag:tab')),conversation:sessionStorage.getItem('rag:conversation')})''')
        operation={'operation_key':str(uuid4()),'question':'What is the annual budget?','tab_id':actor['tab']['id'],'document_ids':[str(row['id']) for row in files]}
        response=page.evaluate('''async ({api,token,actor,operation}) => {
            const response=await fetch(api+'/api/conversations/'+actor.conversation+'/answers',{method:'POST',
            headers:{Authorization:'Bearer '+token,'X-Tab-Proof':actor.tab.proof,'Content-Type':'application/json'},body:JSON.stringify(operation)});
            return {status:response.status,body:await response.json()};}''',{'api':api,'token':token,'actor':actor,'operation':operation})
        assert response['status']==200,response
        navigate(page,'chat')
        expect(page.locator('#history article')).to_contain_text('Завершён',timeout=60000)
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            row=connection.execute('SELECT * FROM requests WHERE id=%s',(response['body']['id'],)).fetchone()
            good=str(next(file['id'] for file in files if file['ready']))
            assert {entry['document_id'] for entry in row['passport']['passed']}=={good},row['passport']
            assert len(row['passport']['selected'])==3 and len(row['passport']['available'])==1,row['passport']
            assert len(row['passport']['excluded'])==2,row['passport']
            assert '100' in row['answer_text']
        (tmp_path/'whole-source-result.json').write_text(json.dumps({'request_id':str(row['id']),'passport':row['passport'],'answer':row['answer_text'],'interrupted_upload':identifier},default=str,ensure_ascii=False,indent=2)+'\n')
        assert worker.poll() is None
        # A closed report must not retain another owner's filename in the DOM.
        page.get_by_role('button',name='Выйти',exact=True).click()
        expect(page.locator('#authentication')).to_be_visible()
        expect(page.locator('#document-report')).to_have_text('')
        register(page,mailbox,frontend,'u8-report-next-owner@owned.test');login(page,'u8-report-next-owner@owned.test')
        assert page.locator('#document-report').inner_text()==''
        expect(page.locator('#documents')).not_to_contain_text('broken.pdf')
        print(json.dumps({'proof':'actual_issuer_partial_upload_failed_file_selected_scope','request_id':str(row['id']),'ready':1,'selected':3,'unready':2,'worker_log':str(worker_log),'generation_log':str(logs['generation'])}),flush=True)
    finally:context.close()
