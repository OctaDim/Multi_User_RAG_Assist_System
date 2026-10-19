"""Remaining U8 gaps through issued owners, real publisher and native contexts."""
import json
import os
import time

import psycopg
from psycopg.rows import dict_row
from playwright.sync_api import expect
import pytest

from integration.test_answer_lifecycle import environment,operator
from integration.test_terminal_lifecycle import controlled_native_browser,current,records
from browser.test_accounts import real_account_browser,register,login, navigate, open_sources
from browser.test_documents import real_document_browser,ready


def upload(page,name,text):
    navigate(page,'library')
    page.locator('#document-upload input').set_input_files({'name':name,'mimeType':'text/plain','buffer':text.encode()})
    page.get_by_role('button',name='Загрузить документы',exact=True).click();ready(page,name)
    navigate(page,'chat')
    open_sources(page)
    page.get_by_role('checkbox',name=name,exact=True).check()


@pytest.mark.parametrize('controlled_native_browser,phase',[('after','queued'),('after','streaming')],indirect=['controlled_native_browser'])
def test_issued_owner_revocation_during_actual_queue_and_native_stream(controlled_native_browser,environment,tmp_path,phase):
    ((browser,mailbox,frontend,api),_,_),marker,release,armed,native_log,_,_,second_api=controlled_native_browser
    contexts=[browser.new_context() for _ in range(3)]
    try:
        admin,holder,owner=[context.new_page() for context in contexts]
        operator(admin,mailbox,frontend)
        if phase=='queued':
            navigate(admin,'administration')
            form=admin.locator('#global-settings');form.locator('[name=max_active]').fill('1')
            form.get_by_role('button',name='Предпросмотр изменения',exact=True).click()
            form.get_by_role('button',name='Сохранить глобальные настройки',exact=True).click()
            expect(admin.locator('#status')).to_contain_text('Ревизия 1 сохранена')
            register(holder,mailbox,frontend,'u8-revoke-holder@owned.test');login(holder,'u8-revoke-holder@owned.test')
            upload(holder,'holder.txt',('The annual budget is 100 euros. The budget pays for library maintenance and its reading rooms. ')*45)
        email='u8-revoked@owned.test';register(owner,mailbox,frontend,email);login(owner,email)
        upload(owner,'revoked-owner.txt','The annual budget is 200 euros.')
        if phase=='streaming':armed.touch()
        active=holder if phase=='queued' else owner
        navigate(active,'chat')
        active.locator('#question').fill('What is the annual budget? Quote every supplied excerpt in full with citations.' if phase=='queued' else 'What is the annual budget?')
        active.get_by_role('button',name='Отправить вопрос',exact=True).click()
        if phase=='queued':
            expect(holder.locator('#history article')).to_have_count(1)
            holder_request=holder.locator('#history article').get_attribute('data-request')
            until=time.monotonic()+30
            while not any(value['event']=='native_allocate' and value['request']==holder_request for value in records(native_log)):
                assert time.monotonic()<until;holder.wait_for_timeout(50)
            # Let real native prefill advance in finite steps while the second
            # issued owner is searched/queued, then hold only native compute.
            navigate(owner,'chat')
            owner.locator('#question').fill('What is the annual budget?')
            owner.get_by_role('button',name='Отправить вопрос',exact=True).click()
            until=time.monotonic()+30
            while True:
                own_request=owner.locator('#history article').get_attribute('data-request') if owner.locator('#history article').count() else None
                row=current(environment,own_request) if own_request else None
                if row and row['state']=='queued':break
                assert time.monotonic()<until;owner.wait_for_timeout(50)
            armed.touch()
        until=time.monotonic()+45
        while not marker.exists():
            assert time.monotonic()<until;owner.wait_for_timeout(50)
        expect(owner.locator('#history article')).to_have_count(1)
        own_request=owner.locator('#history article').get_attribute('data-request')
        row=current(environment,own_request)
        with psycopg.connect(environment['dsn'],autocommit=True) as connection:
            assert connection.execute('SELECT email FROM accounts WHERE id=%s',(row['owner_id'],)).fetchone()[0]==email
        assert row['state']==('queued' if phase=='queued' else 'generating')
        assert phase=='queued' or row['answer_text']
        request_id=str(row['id']);prefix=row['answer_text']
        tab=json.loads(owner.evaluate("sessionStorage.getItem('rag:tab')"))
        credential=owner.evaluate("sessionStorage.getItem('rag:credential')")
        navigate(admin,'administration')
        admin.reload();form=admin.locator(f'form[data-account="{email}"]')
        form.locator('[name=disabled]').check();form.get_by_role('button',name='Сохранить права',exact=True).click()
        expect(admin.locator('#status')).to_contain_text('Права сохранены')
        revoked=current(environment,request_id)
        assert revoked['state']=='interrupted' and revoked['reason']=='account_changed'
        assert revoked['answer_text']==prefix
        # Fresh snapshot AND replay attempts on both independently running APIs
        # authenticate immediately; revoke cannot wait for the tab grace timer.
        refusals=admin.evaluate('''async ({apis,credential,tab,conversation})=>{
            const results=[];
            for(const api of apis)for(const path of ['/api/conversations/'+conversation,'/api/tabs/'+tab.id+'/events']){
                const response=await fetch(api+path,{headers:{Authorization:'Bearer '+credential,'X-Tab-Proof':tab.proof,'Last-Event-ID':'0'}});
                results.push({api,path,status:response.status,body:await response.text()});
            }return results;
        }''',{'apis':[api,second_api],'credential':credential,'tab':tab,'conversation':str(row['conversation_id'])})
        assert all(value['status']==401 for value in refusals),refusals
        release.touch();until=time.monotonic()+30
        while True:
            trace=records(native_log)
            if phase=='queued' or any(value['event']=='native_release' and value['request']==request_id for value in trace):break
            assert time.monotonic()<until;admin.wait_for_timeout(50)
        assert current(environment,request_id)['answer_text']==prefix
        allocations=[value for value in records(native_log) if value['event']=='native_allocate' and value['request']==request_id]
        assert len(allocations)==(0 if phase=='queued' else 1)
        with psycopg.connect(environment['dsn'],autocommit=True) as connection:
            assert connection.execute('SELECT count(*) FROM documents WHERE owner_id=%s',(row['owner_id'],)).fetchone()[0]==1
            assert connection.execute('SELECT count(*) FROM messages WHERE request_id=%s',(row['id'],)).fetchone()[0]>=1
        proof={'proof':'actual_issued_account_revocation','phase':phase,'request_id':request_id,'prefix':prefix,'refusals':refusals,'native_allocations':len(allocations)}
        (tmp_path/'issued-revoke-result.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False),flush=True)
    finally:
        release.touch(exist_ok=True)
        for context in contexts:context.close()


@pytest.mark.parametrize('controlled_native_browser',['after'],indirect=True)
def test_actual_tokenizer_oversize_refusal_preserves_draft_and_empty_history(controlled_native_browser,environment,tmp_path):
    ((browser,mailbox,frontend,_),_,_),_,_,_,native_log,_,_,_=controlled_native_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'u8-tokenizer@owned.test');login(page,'u8-tokenizer@owned.test')
        upload(page,'budget.txt','The annual budget is 100 euros.')
        from app.llama_runtime import Vocabulary
        question='quartz '*5000
        vocabulary=Vocabulary(os.environ['RAG_MODEL_PATH'])
        try:actual_tokens=len(vocabulary.tokenize(question))
        finally:vocabulary.close()
        assert actual_tokens>4096
        navigate(page,'chat')
        page.locator('#question').fill(question);page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#status')).to_contain_text('Вопрос превышает доступный контекст')
        expect(page.locator('#question')).to_have_value(question)
        expect(page.locator('#history')).to_have_text('В этой беседе пока нет сообщений.')
        with psycopg.connect(environment['dsn'],autocommit=True) as connection:
            assert connection.execute('SELECT count(*) FROM requests').fetchone()[0]==0
            assert connection.execute('SELECT count(*) FROM messages').fetchone()[0]==0
        assert not any(value['event']=='native_allocate' for value in records(native_log))
        page.reload();expect(page.locator('#question')).to_have_value(question)
        navigate(page,'chat')
        page.locator('#question').fill('What is the annual budget?')
        navigate(page,'chat')
        open_sources(page)
        page.get_by_role('checkbox',name='budget.txt',exact=True).check()
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#history article')).to_contain_text('Завершён',timeout=60000)
        assert len([value for value in records(native_log) if value['event']=='native_allocate'])==1
        print(json.dumps({'proof':'actual_tokenizer_pre_admission_refusal_draft_reload','actual_question_tokens':actual_tokens,'new_explicit_question_completed':True}),flush=True)
    finally:context.close()


@pytest.mark.parametrize('controlled_native_browser',['after'],indirect=True)
def test_actual_native_completed_outputs_are_isolated_between_issued_owners(controlled_native_browser,environment,tmp_path):
    ((browser,mailbox,frontend,_),_,_),_,_,_,native_log,_,_,_=controlled_native_browser
    contexts=[browser.new_context(),browser.new_context()]
    try:
        pages=[context.new_page() for context in contexts]
        for index,page in enumerate(pages):
            register(page,mailbox,frontend,f'u8-isolated-{index}@owned.test');login(page,f'u8-isolated-{index}@owned.test')
            upload(page,f'budget-{index}.txt',f'The annual budget is {(index+1)*100} euros.')
        for page in pages:
            navigate(page,'chat')
            page.locator('#question').fill('What is the annual budget?');page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        for page in pages:expect(page.locator('#history article')).to_contain_text('Завершён',timeout=60000)
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            rows=connection.execute('SELECT r.*,a.email FROM requests r JOIN accounts a ON a.id=r.owner_id ORDER BY a.email').fetchall()
        assert len(rows)==2
        for index,row in enumerate(rows):
            expected=str((index+1)*100);foreign=str((2-index)*100)
            assert expected in row['answer_text'] and foreign not in row['answer_text'],row['answer_text']
            assert all(expected in span['text'] and foreign not in span['text'] for span in row['passport']['passed'])
            navigate(pages[index],'evidence')
            expect(pages[index].locator('#early-fragments')).to_contain_text('Сохранённые основания')
        assert len({value['context'] for value in records(native_log) if value['event']=='native_allocate'})==2
        proof=[{'owner':row['email'],'answer':row['answer_text'],'passport':row['passport']} for row in rows]
        (tmp_path/'actual-isolated-outputs.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'proof':'actual_completed_native_output_isolation','results':proof},ensure_ascii=False),flush=True)
    finally:
        for context in contexts:context.close()
