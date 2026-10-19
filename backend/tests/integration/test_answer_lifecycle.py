"""U8 acceptance through real issuers, publishers and independent HTTP processes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from playwright.sync_api import expect
import pytest

from app.db import migrate
from browser.test_accounts import BACKEND, real_account_browser, register, login, navigate, open_sources, api_wait_ms
from browser.test_documents import real_document_browser, ready


@pytest.fixture
def environment(postgres):
    """Production migrations only: zero fixture principals, sessions or ready chunks."""
    name = 'u8_' + uuid4().hex
    with psycopg.connect(postgres, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    dsn = make_conninfo(postgres, dbname=name)
    asyncio.run(migrate(dsn))
    try:
        yield {'dsn': dsn}
    finally:
        with psycopg.connect(postgres, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def operator(page, mailbox, frontend):
    email = 'u8-operator@owned.test'
    invitation = subprocess.run([sys.executable, '-m', 'app.accounts', '--email', email],
        cwd=BACKEND, env=os.environ.copy(), check=True, capture_output=True, text=True).stdout.strip()
    register(page, mailbox, frontend, email, invitation)
    login(page, email)


@pytest.fixture
def integrated_browser(real_document_browser, environment, tmp_path):
    """Two real API processes, the production supervisor, publisher and static UI."""
    processes, streams = [], []
    logs = {}
    trace_launcher = tmp_path/'trace-generation.py'
    trace_launcher.write_text('''import logging
logging.basicConfig(level=logging.DEBUG,format='%(message)s')
logging.getLogger('psycopg').setLevel(logging.WARNING)
logging.getLogger('psycopg.pool').setLevel(logging.WARNING)
from app import generation
original_finish=generation.Coordinator.finish
async def traced_finish(self,request_id,state,reason):
    generation.trace('native_finish_attempt',request=str(request_id),epoch=self.epoch,
                     step=self.step_number,revision=self.revision,state=state,reason=reason)
    return await original_finish(self,request_id,state,reason)
generation.Coordinator.finish=traced_finish
original=generation.subprocess.Popen
def spawn(args,**kwargs):
    if '--worker' in args:args=[args[0],__file__,*args[3:]]
    return original(args,**kwargs)
generation.subprocess.Popen=spawn
generation.main()
''')
    try:
        for name, args in [('api-2', [str(BACKEND/'.venv/bin/rag-api'), '--port', '0']),
                           ('generation', [sys.executable, str(trace_launcher)])]:
            path = tmp_path/f'{name}.log'
            stream = path.open('xb'); streams.append(stream); logs[name] = path
            process = subprocess.Popen(args, cwd=BACKEND, env=os.environ.copy(), stdout=stream, stderr=subprocess.STDOUT)
            processes.append(process)
        deadline = time.monotonic()+45
        with psycopg.connect(environment['dsn'], autocommit=True) as connection:
            while True:
                assert all(process.poll() is None for process in processes), {name:path.read_text() for name,path in logs.items()}
                match = re.search(r'Uvicorn running on (http://127\.0\.0\.1:\d+)', logs['api-2'].read_text())
                healthy = connection.execute('SELECT healthy_until>clock_timestamp() FROM coordinator_lease').fetchone()[0]
                if match and healthy: break
                assert time.monotonic()<deadline, 'Owned U8 processes did not become healthy'
                time.sleep(.05)
        yield real_document_browser, match.group(1), logs
    finally:
        for process in reversed(processes):
            process.terminate()
            try: process.wait(20)
            except subprocess.TimeoutExpired: process.kill(); process.wait(10)
        for stream in streams: stream.close()
        if 'generation' in logs:
            children = [json.loads(line)['pid'] for line in logs['generation'].read_text().splitlines()
                        if line.startswith('{"event": "native_spawn"')]
            assert all(not Path(f'/proc/{pid}').exists() for pid in children), 'Native child was not reaped'


def test_real_super_admin_settings_preview_apply_and_readonly_models(real_account_browser, environment, tmp_path):
    browser, mailbox, frontend, api_url = real_account_browser
    context = browser.new_context()
    try:
        page = context.new_page()
        operator(page, mailbox, frontend)
        navigate(page,'administration')
        form = page.locator('#global-settings')
        expect(form).to_be_visible()
        expect(form.locator('[name=max_active]')).to_have_value('12')
        expect(form.locator('[name=step_width]')).to_have_value('3')
        expect(form.locator('[name=n_ctx]')).to_be_disabled()
        expect(form.locator('[name=n_ctx]')).to_have_value('4096')
        expect(form.locator('[name=model]')).to_be_disabled()
        for key, expected in [('n_threads','4'),('n_threads_batch','8'),('thinking','false')]:
            expect(form.locator(f'[name={key}]')).to_be_disabled()
            expect(form.locator(f'[name={key}]')).to_have_value(expected)
        expect(form).to_contain_text('multilingual-e5-small')
        form.locator('[name=max_active]').fill('6')
        form.locator('[name=step_width]').fill('2')
        form.get_by_role('button', name='Предпросмотр изменения', exact=True).click()
        expect(form.locator('.settings-preview')).to_contain_text('12 → 6')
        expect(form.locator('.settings-preview')).to_contain_text('3 → 2')
        expect(form.locator('.settings-preview')).to_contain_text('весь сервис')
        expect(form.locator('.settings-preview')).to_contain_text('неизвест')
        with psycopg.connect(environment['dsn'], autocommit=True) as connection:
            assert connection.execute('SELECT revision FROM settings').fetchone()[0] == 0
        form.get_by_role('button', name='Сохранить глобальные настройки', exact=True).click()
        expect(page.locator('#status')).to_contain_text('Ревизия 1 сохранена')
        expect(form.locator('.settings-revision')).to_contain_text('Ожидает применения')
        page.reload()
        expect(form.locator('[name=max_active]')).to_have_value('6')
        expect(form.locator('[name=step_width]')).to_have_value('2')
        readonly = page.evaluate('''async url => {
            const response=await fetch(url+'/api/settings',{method:'PATCH',headers:{
                Authorization:'Bearer '+sessionStorage.getItem('rag:credential'),'Content-Type':'application/json'},
                body:JSON.stringify({n_ctx:2048})});return response.status;
        }''', api_url)
        assert readonly == 422
        for width, name in [(1280, 'desktop'), (375, 'mobile')]:
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path/f'settings-{name}.png'), full_page=True)
        form.locator('[name=max_active]').focus()
        page.keyboard.press('Tab')
        assert form.locator('[name=step_width]').evaluate('element => element === document.activeElement')
        page.get_by_role('button', name='Выйти', exact=True).click()
        register(page, mailbox, frontend, 'u8-user@owned.test')
        login(page, 'u8-user@owned.test')
        expect(form).to_be_hidden()
        print(json.dumps({'proof':'real_issuer_settings_ui','origins':[frontend,api_url],
            'saved_revision':1,'read_only_direct_write_status':readonly,'screenshots':str(tmp_path)}),flush=True)
    finally:
        context.close()


def test_thirty_real_accounts_ten_concurrent_owners_share_two_api_native_limits(integrated_browser, environment):
    ((browser, mailbox, frontend, first), publisher, publisher_log), second, logs = integrated_browser
    contexts=[]; pages=[]; credentials=[]; operations=[]
    try:
        admin_context=browser.new_context();contexts.append(admin_context)
        admin=admin_context.new_page();operator(admin,mailbox,frontend)
        for index in range(29):
            context=browser.new_context();contexts.append(context)
            page=context.new_page();email=f'u8-load-{index}@owned.test'
            register(page,mailbox,frontend,email);login(page,email)
            if index>=10:
                context.close();continue
            # Every ready document comes through the UI and the actual E5 worker.
            name=f'private-budget-{index}.txt'
            content=(f'The annual budget for library {index} is {100+index} euros. '
                     'The budget pays for maintenance of the library and its reading rooms. ')*45
            navigate(page,'library')
            page.locator('#document-upload input').set_input_files({'name':name,'mimeType':'text/plain','buffer':content.encode()})
            page.get_by_role('button',name='Загрузить документы',exact=True).click();ready(page,name,timeout=45)
            navigate(page,'chat')
            open_sources(page)
            page.get_by_role('checkbox',name=name,exact=True).check()
            pages.append(page)
            credentials.append(page.evaluate('''() => ({token:sessionStorage.getItem('rag:credential'),
                tab:JSON.parse(sessionStorage.getItem('rag:tab')),
                conversation:sessionStorage.getItem('rag:conversation'),
                document:document.querySelector('#question-sources input:checked').value})'''))
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            assert connection.execute('SELECT count(*) AS n FROM accounts').fetchone()['n']==30
            assert connection.execute('SELECT count(*) AS n FROM accounts WHERE verified AND NOT paid').fetchone()['n']==30
            assert connection.execute('SELECT count(*) AS n FROM documents WHERE ready').fetchone()['n']==10
        # Three owners have a second genuine conversation; all admissions then
        # run simultaneously through the two real APIs with issued credentials.
        for index in range(13):
            actor=credentials[index%10]
            if index>=10:
                conversation=pages[index%10].evaluate('''async ({url,token}) => (await (await fetch(url+'/api/conversations',
                    {method:'POST',headers:{Authorization:'Bearer '+token}})).json()).id''',{'url':second,'token':actor['token']})
            else:conversation=actor['conversation']
            operations.append({'base':first if index%2 else second,'token':actor['token'],'proof':actor['tab']['proof'],
                'conversation':conversation,'body':{'operation_key':str(uuid4()),'question':f'What is the annual budget for library {index%10} and its reading rooms? Quote every supplied excerpt in full with citations.',
                    'document_ids':[actor['document']],'tab_id':actor['tab']['id']}})
        submit='''async operations => await Promise.all(operations.map(async operation => {
            const response=await fetch(operation.base+'/api/conversations/'+operation.conversation+'/answers',{
                method:'POST',headers:{Authorization:'Bearer '+operation.token,'X-Tab-Proof':operation.proof,'Content-Type':'application/json'},body:JSON.stringify(operation.body)});
            return {status:response.status,body:await response.json()};
        }))'''
        responses=admin.evaluate(submit,operations[:10])
        deadline=time.monotonic()+90
        while True:
            trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            if len([row for row in trace if row['event']=='native_allocate'])==10:break
            assert time.monotonic()<deadline,'Ten genuine owners did not receive native contexts'
            admin.wait_for_timeout(50)
        responses.extend(admin.evaluate(submit,operations[10:]))
        assert all(row['status']==200 for row in responses),responses
        identifiers={row['body']['id'] for row in responses}
        deadline=time.monotonic()+90
        while True:
            trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            allocations=[row for row in trace if row['event']=='native_allocate']
            with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                states=connection.execute('SELECT state FROM requests').fetchall()
            if len(allocations)>=12 and sum(row['state']=='queued' for row in states)==1:break
            assert time.monotonic()<deadline,{name:path.read_text()[-3000:] for name,path in logs.items()}
            admin.wait_for_timeout(50)
        assert len(allocations)==12 and len({row['context'] for row in allocations})==12,allocations
        assert all(row['max_active']==12 for row in allocations)
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            requests=connection.execute('SELECT r.*,a.email FROM requests r JOIN accounts a ON a.id=r.owner_id').fetchall()
            print(json.dumps({'load_states':{str(row['id']):row['state'] for row in requests}}),flush=True)
            assert len(requests)==13,requests
            assert sum(row['state']=='queued' for row in requests)==1,[(str(row['id']),row['state']) for row in requests]
            for row in requests:
                expected=int(row['email'].split('@')[0].rsplit('-',1)[1])
                assert row['passport']['passed'] and row['passport']['found'],row['passport']
                assert all(f'library {expected} ' in item['text'] for item in row['passport']['passed']),row['passport']
                assert {item['document_id'] for item in row['passport']['passed']}==set(map(str,row['scope']))
        steps=[row for row in trace if row['event']=='native_step']
        assert steps and all(row['step_width']==3 and len(row['promoted'])<=3 for row in steps)
        expected={row['request'] for row in allocations}
        deadline=time.monotonic()+30
        while True:
            trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            steps=[row for row in trace if row['event']=='native_step']
            fair=any(len(promoted:= [item['request'] for row in steps[start:start+4] for item in row['promoted']])==12
                and set(promoted)==expected for start in range(len(steps)))
            if fair:break
            assert time.monotonic()<deadline,'No fair round across the twelve genuine admitted contexts'
            admin.wait_for_timeout(50)
        navigate(admin,'administration')
        form=admin.locator('#global-settings')
        form.locator('[name=max_active]').fill('6');form.locator('[name=step_width]').fill('2')
        form.get_by_role('button',name='Предпросмотр изменения',exact=True).click()
        form.get_by_role('button',name='Сохранить глобальные настройки',exact=True).click()
        expect(admin.locator('#status')).to_contain_text('Ревизия 1 сохранена')
        deadline=time.monotonic()+30
        while True:
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                applied=connection.execute('SELECT applied_revision FROM settings').fetchone()[0]==1
            trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            if applied and any(row['event']=='native_step' and row['revision']==1 for row in trace):break
            assert time.monotonic()<deadline
            admin.wait_for_timeout(50)
        form.get_by_role('button',name='Обновить применение настроек',exact=True).click()
        expect(form.locator('.settings-revision')).to_contain_text('Применена: 1')
        trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
        new_steps=[row for row in trace if row['event']=='native_step' and row['revision']==1]
        assert new_steps and all(row['step_width']==2 and len(row['promoted'])<=2 for row in new_steps)
        active=set();preserved_excess=False
        for row in trace:
            if row['event']=='native_allocate': active.add(row['request'])
            elif row['event']=='native_release': active.remove(row['request'])
            elif row['event']=='native_step' and row['revision']==1 and len(active)>6: preserved_excess=True
        assert preserved_excess, 'Shrink must preserve excess active contexts'
        # Exercise actual OCR publication while the generation/API/DB workload
        # is running. Unchanged source fixture combines four printed languages
        # and real English handwriting, exercising both fixed OCR contexts.
        navigate(pages[0],'library')
        pages[0].locator('#document-upload input').set_input_files({'name':'joint-scanned-budget.pdf',
            'mimeType':'application/pdf','buffer':(BACKEND.parent/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/mixed-real-title-fixture-v1.pdf').read_bytes()})
        pages[0].get_by_role('button',name='Загрузить документы',exact=True).click()
        deadline=time.monotonic()+45
        overlap_step=None;overlap_confirmed=False
        while True:
            with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                job=connection.execute("SELECT f.state FROM document_files f WHERE f.name='joint-scanned-budget.pdf'").fetchone()
            trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            latest=next((row for row in reversed(trace) if row['event']=='native_step' and row['promoted']),None)
            if job and job['state']=='processing' and latest:
                if overlap_step is None:overlap_step=latest['step']
                elif latest['step']>overlap_step:
                    overlap_confirmed=True;break
            assert time.monotonic()<deadline,'No real OCR/generation workload overlap'
            admin.wait_for_timeout(50)
        # Full five-line Paddle + two real Qwen crops alongside twelve native
        # contexts exceeds the old single-recognizer 120-second hardware bound.
        try:
            ready(pages[0],'joint-scanned-budget.pdf',timeout=300)
        except AssertionError:
            with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                failed_job=connection.execute("SELECT state,error,failure_page FROM document_files WHERE name='joint-scanned-budget.pdf'").fetchone()
                failed_lease=connection.execute('SELECT epoch,healthy_until>clock_timestamp() AS healthy FROM coordinator_lease').fetchone()
            print(json.dumps({'proof':'actual_joint_OCR_failure_diagnostic','job':failed_job,'lease':failed_lease,
                'publisher_alive':publisher.poll() is None,'publisher_tail':publisher_log.read_text()[-4000:],
                'native_tail':logs['generation'].read_text()[-4000:]},default=str),flush=True)
            raise
        trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
        sample_contexts={}
        for value in trace:
            if value['event']=='native_allocate':sample_contexts[value['request']]=value['context']
            elif value['event']=='native_release':sample_contexts.pop(value['request'],None)
        if len(sample_contexts)!=12:
            with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                interrupted=connection.execute("SELECT r.id,r.state,r.reason,a.email,t.connected,t.confirmed,t.deadline,t.ack_until FROM requests r JOIN accounts a ON a.id=r.owner_id JOIN tabs t ON t.id=r.origin_tab ORDER BY r.created_at").fetchall()
                activity=connection.execute("SELECT pid,state,wait_event_type,wait_event,query,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE datname=current_database() ORDER BY pid").fetchall()
            (logs['generation'].parent/'actual-joint-interruption-diagnostic.json').write_text(json.dumps({'requests':interrupted,'activity':activity},default=str,ensure_ascii=False,indent=2)+'\n')
        assert len(sample_contexts)==12,{'actual_contexts_at_memory_sample':sample_contexts}
        generation_pid=next(value['pid'] for value in trace if value['event']=='native_spawn')
        memory={}
        for role,pid in [('fixed_two_OCR_models',publisher.pid),('twelve_generation_contexts',generation_pid)]:
            metrics={}
            for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
                key,_,value=line.partition(':')
                if key in ('Rss','Pss','Swap','SwapPss'):metrics[key+'_kib']=int(value.split()[0])
            memory[role]={'pid':pid,**metrics}
        memory['scope']='PSS and swap of the two actual native processes; excludes API/browser/PostgreSQL processes'
        memory['combined_native_pss_kib']=sum(memory[key]['Pss_kib'] for key in ['fixed_two_OCR_models','twelve_generation_contexts'])
        memory['combined_native_swap_kib']=sum(memory[key]['Swap_kib'] for key in ['fixed_two_OCR_models','twelve_generation_contexts'])
        memory['actual_physical_contexts_at_sample']=sample_contexts
        print(json.dumps({'proof':'actual_fixed_two_OCR_models_joint_native_memory','memory':memory}),flush=True)
        trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
        assert overlap_confirmed,'No measured native prefill/token compute during actual OCR processing'
        queued=next(row for row in requests if row['state']=='queued')
        queued_index=next(index for index,row in enumerate(responses) if row['body']['id']==str(queued['id']))
        queued_stop=admin.evaluate('''async ({id,operation}) => (await fetch(operation.base+'/api/answers/'+id+'/stop',
            {method:'POST',headers:{Authorization:'Bearer '+operation.token}})).status''',
            {'id':str(queued['id']),'operation':operations[queued_index]})
        assert queued_stop==200
        # AE28: an actual newly admitted question at six physical contexts
        # remains queued; the seventh close ACK creates five, then one admits.
        active_rows=[(row,operation) for row,operation in zip(responses,operations) if row['body']['id']!=str(queued['id'])]
        for row,operation in active_rows[:6]:
            assert admin.evaluate('''async ({id,operation})=>(await fetch(operation.base+'/api/answers/'+id+'/stop',{
                method:'POST',headers:{Authorization:'Bearer '+operation.token}})).status''',{'id':row['body']['id'],'operation':operation})==200
        def live(events):
            active={}
            for value in events:
                if value['event']=='native_allocate':active[value['request']]=value['context']
                elif value['event']=='native_release':active.pop(value['request'],None)
            return active
        deadline=time.monotonic()+30
        while len(live([json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]))!=6:
            assert time.monotonic()<deadline;admin.wait_for_timeout(50)
        actor=credentials[0]
        conversation=admin.evaluate('''async ({api,token})=>(await(await fetch(api+'/api/conversations',{
            method:'POST',headers:{Authorization:'Bearer '+token}})).json()).id''',{'api':second,'token':actor['token']})
        new_operation={'base':second,'token':actor['token'],'proof':actor['tab']['proof'],'conversation':conversation,
            'body':dict(operations[0]['body'],operation_key=str(uuid4()))}
        new_response=admin.evaluate(submit,[new_operation])[0];assert new_response['status']==200,new_response
        admitted_at_five=new_response['body']['id'];deadline=time.monotonic()+30
        while True:
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                state=connection.execute('SELECT state FROM requests WHERE id=%s',(admitted_at_five,)).fetchone()[0]
            events=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            if state=='queued':break
            assert time.monotonic()<deadline;admin.wait_for_timeout(50)
        assert len(live(events))==6 and not any(value['event']=='native_allocate' and value['request']==admitted_at_five for value in events)
        sixth_boundary=max(value['step'] for value in events if value['event']=='native_step')
        deadline=time.monotonic()+30
        while True:
            events=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            if any(value['event']=='native_step' and value['step']>sixth_boundary for value in events):break
            assert time.monotonic()<deadline;admin.wait_for_timeout(50)
        assert len(live(events))==6 and not any(value['event']=='native_allocate' and value['request']==admitted_at_five for value in events)
        row,operation=active_rows[6]
        assert admin.evaluate('''async ({id,operation})=>(await fetch(operation.base+'/api/answers/'+id+'/stop',{
            method:'POST',headers:{Authorization:'Bearer '+operation.token}})).status''',{'id':row['body']['id'],'operation':operation})==200
        deadline=time.monotonic()+30
        while True:
            events=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            admission_index=next((index for index,value in enumerate(events) if value['event']=='native_allocate' and value['request']==admitted_at_five),None)
            if admission_index is not None:break
            assert time.monotonic()<deadline;admin.wait_for_timeout(50)
        assert len(live(events[:admission_index]))==5
        assert events[admission_index]['physical_active']==events[admission_index]['max_active']==6
        assert events[admission_index]['revision']==1
        assert admin.evaluate('''async ({id,operation})=>(await fetch(operation.base+'/api/answers/'+id+'/stop',{
            method:'POST',headers:{Authorization:'Bearer '+operation.token}})).status''',{'id':admitted_at_five,'operation':new_operation})==200
        stop_results=admin.evaluate('''async rows => await Promise.all(rows.map(async ({id,operation}) => {
            const response=await fetch(operation.base+'/api/answers/'+id+'/stop',{method:'POST',headers:{Authorization:'Bearer '+operation.token}});
            return response.status;
        }))''',[{'id':row['body']['id'],'operation':operation} for index,(row,operation) in enumerate(zip(responses,operations)) if index!=queued_index])
        assert stop_results==[200]*12
        deadline=time.monotonic()+30
        while True:
            trace=[json.loads(line) for line in logs['generation'].read_text().splitlines() if line.startswith('{"event": "native_')]
            released={row['request'] for row in trace if row['event']=='native_release'}
            allocated={row['request'] for row in trace if row['event']=='native_allocate'}
            if released==allocated:break
            assert time.monotonic()<deadline,'Physical release ACKs did not arrive'
            admin.wait_for_timeout(50)
        assert str(queued['id']) not in allocated,'Stopped queued request acquired a native context'
        assert publisher.poll() is None
        print(json.dumps({'proof':'thirty_issued_accounts_ten_real_concurrent_owners','accounts':30,'owners':10,
            'http_admissions':13,'native_active':12,'queued':1,'step_width':3,'api_origins':[first,second],
            'hot_revision':1,'hot_max_active':6,'hot_step_width':2,'joint_actual_ocr_published':True,
            'fixed_Paddle_and_Qwen_actual_OCR':True,'new_question_queued_at_six_admitted_after_five':admitted_at_five,
            'ocr_overlap_step':overlap_step,'fair_twelve_context_round':True,
            'request_ids':sorted(identifiers),'actual_ui_smtp_publication':True,'native_log':str(logs['generation'])}),flush=True)
    finally:
        for context in contexts: context.close()


def test_frozen_thirty_questions_use_real_multilingual_documents(integrated_browser, environment, tmp_path):
    ((browser,mailbox,frontend,first),_,_),second,logs=integrated_browser
    fixtures=BACKEND/'tests/fixtures/answer_lifecycle'
    controls_path=fixtures/'control-questions-v1.json'
    controls=json.loads(controls_path.read_text())
    matchers=json.loads((fixtures/'control-matchers-v5.json').read_text())
    assert hashlib.sha256(controls_path.read_bytes()).hexdigest()==matchers['controls_sha256']
    for name,digest in controls['corpus_hashes'].items():
        assert hashlib.sha256((fixtures/name).read_bytes()).hexdigest()==digest
    assert len(controls['questions'])==30
    context=browser.new_context();results=[];errors=[]
    try:
        page=context.new_page();register(page,mailbox,frontend,'u8-quality@owned.test');login(page,'u8-quality@owned.test')
        files=sorted({item['document'] for item in controls['questions']})
        navigate(page,'library')
        page.locator('#document-upload input').set_input_files([str(fixtures/name) for name in files])
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        for name in files:ready(page,name,timeout=300)
        navigate(page,'chat')
        for index,item in enumerate(controls['questions']):
            if index:
                previous=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
                page.get_by_role('button',name='Новая беседа',exact=True).click()
                expect(page.locator('#conversations button[aria-current=true]')).not_to_have_attribute('data-conversation',previous,timeout=api_wait_ms(page))
            open_sources(page)
            for checkbox in page.locator('#question-sources input').all():checkbox.uncheck()
            navigate(page,'chat')
            open_sources(page)
            page.get_by_role('checkbox',name=item['document'],exact=True).check()
            navigate(page,'chat')
            page.locator('#question').fill(item['question'])
            page.get_by_role('button',name='Отправить вопрос',exact=True).click()
            expect(page.locator('#history article')).to_have_count(1,timeout=120000)
            expect(page.locator('#history article')).to_contain_text('Завершён',timeout=180000)
            with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                row=connection.execute('SELECT * FROM requests ORDER BY created_at DESC LIMIT 1').fetchone()
                binding=connection.execute('SELECT * FROM graph_bindings WHERE request_id=%s',(row['id'],)).fetchone()
            async def saved_prompt():
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                async with await psycopg.AsyncConnection.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                    value=await AsyncPostgresSaver(connection).aget_tuple({'configurable':{'thread_id':binding['thread_id']}})
                    return value.checkpoint['channel_values']['prompt']
            with ThreadPoolExecutor(max_workers=1) as executor:prompt=executor.submit(asyncio.run,saved_prompt()).result(15)
            answer=row['answer_text'];passed=row['passport']['passed']
            concepts=matchers['replacements'].get(item['id'],item['required_concepts'])
            missing=[concept for concept in concepts if concept.casefold() not in answer.casefold()]
            missing.extend(' OR '.join(group) for group in matchers.get('alternatives',{}).get(item['id'],[])
                if not any(value.casefold() in answer.casefold() for value in group))
            snapshot=page.evaluate('''async ({url,conversation}) => (await (await fetch(url+'/api/conversations/'+conversation,
                {headers:{Authorization:'Bearer '+sessionStorage.getItem('rag:credential')}})).json())''',
                {'url':second,'conversation':str(row['conversation_id'])})
            citations=next(value['citations'] for value in snapshot['requests'] if value['id']==str(row['id']))
            failures=[]
            if missing:failures.append({'missing_concepts':missing})
            if not passed:failures.append('no retrieved/passed evidence')
            if not citations:failures.append('no source citation')
            if any(citation['document_id'] not in set(map(str,row['scope'])) for citation in citations):failures.append('citation outside selected scope')
            if failures:errors.append({'id':item['id'],'failures':failures})
            result={'id':item['id'],'question':item['question'],'expected':item['expected_source_answer'],
                    'answer':answer,'passport':row['passport'],'citations':citations,'prompt':prompt,'failures':failures,
                    'request_id':str(row['id']),'state':row['state'],'semantic_audit':'pending caller review'}
            results.append(result)
            print(json.dumps({'control':item['id'],'answer':answer,'failures':failures},ensure_ascii=False),flush=True)
        output=tmp_path/'control-results.json'
        output.write_text(json.dumps({'controls_sha256':matchers['controls_sha256'],'results':results,
            'total':30,'mechanical_correct':30-len(errors),'errors':errors,'semantic_audit':'pending caller review'},ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'proof':'predeclared_thirty_real_document_questions','results':str(output),'errors':errors}),flush=True)
        assert not errors, errors
    finally:
        (tmp_path/'control-partial-results.json').write_text(json.dumps({'results':results,'errors':errors,
            'completed_count':len(results),'semantic_audit':'pending caller review'},ensure_ascii=False,indent=2)+'\n')
        context.close()
