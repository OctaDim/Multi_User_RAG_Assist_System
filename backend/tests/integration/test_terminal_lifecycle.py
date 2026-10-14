"""Actual issued owners/publication/native contexts; deterministic failure boundaries.

Fault cases inject only the native exception after a real allocation/computation;
no successful response, OCR, model text, principal or publication is fabricated.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import re
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row
from playwright.sync_api import expect
import pytest

from integration.test_answer_lifecycle import environment
from integration.test_transport_lifecycle import CutProxy, through_proxy
from browser.test_accounts import BACKEND, real_account_browser, register, login
from browser.test_documents import real_document_browser, ready


@pytest.fixture
def controlled_native_browser(real_document_browser,environment,tmp_path,request):
    marker,release,armed=[tmp_path/name for name in ['native-pause','native-release','native-armed']]
    mode=request.param
    hook=tmp_path/'native-worker.py'
    hook.write_text(f'''import logging,time
from pathlib import Path
from app.llama_runtime import LlamaContext
logging.basicConfig(level=logging.DEBUG)
original=LlamaContext.advance
marker=Path({str(marker)!r});release=Path({str(release)!r});armed=Path({str(armed)!r})
mode={mode!r}
def advance(self):
    if armed.exists() and not marker.exists() and ('before' in mode or (len(self.output_tokens)>=3 and not self._decoder.getstate()[0])):
        marker.write_text('inside allocated real native context')
        while not release.exists():time.sleep(.01)
        if mode.startswith('fault'):raise RuntimeError('controlled native decode failure')
    return original(self)
LlamaContext.advance=advance
from app.generation import main
main()
''')
    launcher=tmp_path/'native-supervisor.py'
    launcher.write_text(f'''from app import generation
original=generation.subprocess.Popen
def spawn(args,**kwargs):
    if '--worker' in args:args=[args[0],{str(hook)!r},*args[3:]]
    return original(args,**kwargs)
generation.subprocess.Popen=spawn
generation.main()
''')
    with psycopg.connect(environment['dsn'],autocommit=True) as connection:
        previous_epoch=connection.execute('SELECT epoch FROM coordinator_lease WHERE id=1').fetchone()[0]
    native_log=tmp_path/'generation.log'
    with native_log.open('xb') as stream:
        process=subprocess.Popen([sys.executable,str(launcher)],cwd=BACKEND,env=os.environ.copy(),stdout=stream,stderr=subprocess.STDOUT)
        processes=[process]
        api_stream=(tmp_path/'api-2.log').open('xb')
        second_api=subprocess.Popen([str(BACKEND/'.venv/bin/rag-api'),'--port','0'],cwd=BACKEND,env=os.environ.copy(),stdout=api_stream,stderr=subprocess.STDOUT)
        try:
            until=time.monotonic()+30
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                while True:
                    epoch,healthy=connection.execute('SELECT epoch,healthy_until>clock_timestamp() FROM coordinator_lease WHERE id=1').fetchone()
                    if epoch>previous_epoch and healthy:break
                    assert process.poll() is None and time.monotonic()<until,native_log.read_text()[-2000:]
                    time.sleep(.05)
            until=time.monotonic()+15
            while True:
                match=re.search(r'Uvicorn running on (http://127\.0\.0\.1:\d+)',(tmp_path/'api-2.log').read_text())
                if match:break
                assert second_api.poll() is None and time.monotonic()<until
                time.sleep(.05)
            yield real_document_browser,marker,release,armed,native_log,processes,launcher,match.group(1)
        finally:
            second_api.terminate()
            try:second_api.wait(15)
            except subprocess.TimeoutExpired:second_api.kill();second_api.wait(10)
            api_stream.close()
            release.touch(exist_ok=True)
            for process in reversed(processes):
                if process.poll() is None:process.terminate()
                try:process.wait(15)
                except subprocess.TimeoutExpired:process.kill();process.wait(10)
            spawns=[json.loads(line[line.index('{'):]) for line in native_log.read_text().splitlines() if '"event": "native_spawn"' in line]
            assert all(not Path(f"/proc/{row['pid']}").exists() for row in spawns)


def current(environment,request_id=None):
    with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
        if request_id:return connection.execute('SELECT * FROM requests WHERE id=%s',(request_id,)).fetchone()
        return connection.execute('SELECT * FROM requests ORDER BY created_at DESC LIMIT 1').fetchone()


def records(log):
    return [json.loads(line[line.index('{'):]) for line in log.read_text().splitlines() if '"event": "native_' in line]


@pytest.mark.parametrize('controlled_native_browser,outcome',[
    ('after','complete_during_grace'),('after','stop_during_grace'),
    ('fault_before','error_before'),('fault_after','error_during_grace'),
    ('before','crash_before'),('after','crash_after')],indirect=['controlled_native_browser'])
def test_actual_native_terminal_paths_no_retry_and_preserved_history(controlled_native_browser,environment,tmp_path,outcome):
    ((browser,mailbox,frontend,api),_,_),marker,release,armed,native_log,processes,launcher,second_api=controlled_native_browser
    parsed=urlsplit(api);proxy=CutProxy((parsed.hostname,parsed.port));context=browser.new_context()
    second=urlsplit(second_api);observer_proxy=CutProxy((second.hostname,second.port))
    try:
        owner,observer=context.new_page(),context.new_page();through_proxy(owner,proxy);through_proxy(observer,observer_proxy)
        email=f'u8-terminal-{outcome}@owned.test'
        register(owner,mailbox,frontend,email);login(owner,email)
        owner.locator('#document-upload input').set_input_files({'name':'terminal-budget.txt','mimeType':'text/plain','buffer':b'The annual budget is 100 euros.'})
        owner.get_by_role('button',name='Загрузить документы',exact=True).click();ready(owner,'terminal-budget.txt')
        owner.get_by_role('checkbox',name='terminal-budget.txt',exact=True).check()
        # A completed real answer must survive the same recovery event.
        completed_id=None
        if outcome.startswith('crash'):
            owner.locator('#question').fill('What is the annual budget?')
            owner.get_by_role('button',name='Отправить вопрос',exact=True).click()
            expect(owner.locator('#history article')).to_contain_text('Завершён',timeout=60000)
            completed=current(environment);completed_id=completed['id'];completed_text=completed['answer_text']
        observer.goto(frontend);login(observer,email)
        observer.locator('#question').fill('Independent observer draft')
        armed.touch()
        owner.locator('#question').fill('What is the annual budget?')
        owner.get_by_role('button',name='Отправить вопрос',exact=True).click()
        until=time.monotonic()+40
        while not marker.exists():
            assert time.monotonic()<until,native_log.read_text()[-2000:]
            owner.wait_for_timeout(50)
        row=current(environment);identifier=row['id'];prefix=row['answer_text']
        assert bool(prefix)==('before' not in outcome),(outcome,prefix)
        card=observer.locator('#history article').last
        expect(card).to_contain_text('Ответ формируется',timeout=10000)
        origin_deadline=None;completed_observed=None
        if 'grace' in outcome:
            proxy.cut()
            until=time.monotonic()+5
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                while origin_deadline is None:
                    origin_deadline=connection.execute('SELECT deadline FROM tabs WHERE id=%s',(row['origin_tab'],)).fetchone()[0]
                    assert time.monotonic()<until,'Real origin disconnect was not observed'
                    if origin_deadline is None:observer.wait_for_timeout(50)
        if outcome=='complete_during_grace':
            observer.wait_for_timeout(6000);release.touch()
            expect(card).to_contain_text('Завершён',timeout=10000)
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                completed_observed=connection.execute('SELECT clock_timestamp()').fetchone()[0]
            assert completed_observed<origin_deadline,'Completion was not observed during the actual stored grace interval'
            observer.wait_for_timeout(6000)
            assert current(environment,identifier)['state']=='completed'
        elif outcome=='stop_during_grace':
            start=time.monotonic();card.get_by_role('button',name='Остановить ответ',exact=True).click()
            expect(card).to_contain_text('Прерван',timeout=2000)
            assert time.monotonic()-start<3
            release.touch()
        elif outcome.startswith('error'):
            release.touch();expect(card).to_contain_text('Ошибка',timeout=15000)
        else:
            old_pid=next(row['pid'] for row in records(native_log) if row['event']=='native_spawn')
            os.kill(old_pid,signal.SIGKILL)
            # R35 applies after real service recovery. This supervisor exits
            # on a dead coordinator; there is deliberately no automatic retry.
            processes[0].wait(20)
            assert processes[0].returncode!=0
            assert not Path(f'/proc/{old_pid}').exists()
            with native_log.open('ab') as stream:
                replacement=subprocess.Popen([sys.executable,str(launcher)],cwd=BACKEND,env=os.environ.copy(),stdout=stream,stderr=subprocess.STDOUT)
            processes.append(replacement)
            expect(card).to_contain_text('Прерван',timeout=20000)
            until=time.monotonic()+30
            while Path(f'/proc/{old_pid}').exists():
                assert time.monotonic()<until,'Old native process not reaped';observer.wait_for_timeout(50)
            assert current(environment,completed_id)['state']=='completed'
            assert current(environment,completed_id)['answer_text']==completed_text
            assert sum(row['event']=='native_allocate' and row['request']==str(completed_id) for row in records(native_log))==1
        row=current(environment,identifier)
        expected='completed' if outcome=='complete_during_grace' else 'failed' if outcome.startswith('error') else 'interrupted'
        assert row['state']==expected,row
        if expected!='completed':assert row['answer_text']==prefix
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            messages=connection.execute("SELECT * FROM messages WHERE request_id=%s AND role='assistant'",(identifier,)).fetchall()
            if not prefix and expected!='completed':assert not messages
            elif expected!='completed':assert len(messages)==1 and messages[0]['excluded']
            assert connection.execute('SELECT count(*) AS n FROM requests').fetchone()['n']==(2 if completed_id else 1)
        expect(observer.locator('#question')).to_have_value('Independent observer draft')
        proxy.enabled=True
        expect(owner.locator('#answer-connection')).to_contain_text('Соединение установлено',timeout=8000)
        assert sum(row['event']=='native_allocate' and row['request']==str(identifier) for row in records(native_log))==1
        if not outcome.startswith('crash'):
            until=time.monotonic()+20
            while not any(row['event']=='native_release' and row['request']==str(identifier) for row in records(native_log)):
                assert time.monotonic()<until,'Physical context release not acknowledged';observer.wait_for_timeout(50)
        if outcome.startswith('crash'):
            # Recovery publishes lost-request terminals before replacement
            # weights finish loading. Refusal during that interval is correct;
            # wait for actual health, then make the explicit next operation.
            until=time.monotonic()+30
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                while not connection.execute('SELECT healthy_until>clock_timestamp() FROM coordinator_lease').fetchone()[0]:
                    assert time.monotonic()<until;observer.wait_for_timeout(50)
        # A new request is only sent by this explicit UI operation. It must
        # build a fresh checkpoint from admissible history across API2.
        observer.get_by_role('checkbox',name='terminal-budget.txt',exact=True).check()
        observer.locator('#question').fill('What is the annual budget now?')
        observer.get_by_role('button',name='Отправить вопрос',exact=True).click()
        # A previously completed last card cannot acknowledge a new question.
        until=time.monotonic()+15
        while current(environment)['id']==identifier:
            assert time.monotonic()<until,observer.locator('#status').inner_text();observer.wait_for_timeout(50)
        followup_id=current(environment)['id']
        new_card=observer.locator(f'#history article[data-request="{followup_id}"]')
        expect(new_card).to_contain_text('Завершён',timeout=60000)
        followup=current(environment)
        assert followup['id']!=identifier
        if expected!='completed':assert str(identifier) not in followup['passport']['history_requests']
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            binding=connection.execute('SELECT * FROM graph_bindings WHERE request_id=%s',(followup['id'],)).fetchone()
            old_binding=connection.execute('SELECT * FROM graph_bindings WHERE request_id=%s',(identifier,)).fetchone()
        assert binding['thread_id']!=old_binding['thread_id']
        async def saved_prompt():
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            async with await psycopg.AsyncConnection.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                checkpoint=await AsyncPostgresSaver(connection).aget_tuple({'configurable':{'thread_id':binding['thread_id']}})
                return checkpoint.checkpoint['channel_values']['prompt']
        with ThreadPoolExecutor(max_workers=1) as executor:prompt=executor.submit(asyncio.run,saved_prompt()).result(15)
        if expected!='completed':
            assert str(identifier) not in prompt
            conversation_prompt=prompt.split('<conversation>\n',1)[1].split('</conversation>',1)[0]
            assert conversation_prompt.count('<turn>')==(1 if completed_id else 0),conversation_prompt
            if prefix:assert f'Assistant: {prefix}\n</turn>' not in conversation_prompt
            if completed_id:
                normalized_completed=re.sub(r'\[source:([1-9][0-9]?)\]',r'[past-source:\1]',completed_text)
                assert normalized_completed in conversation_prompt
        (tmp_path/'explicit-followup-prompt.json').write_text(json.dumps({'old_request':str(identifier),'new_request':str(followup['id']),
            'old_state':expected,'history_requests':followup['passport']['history_requests'],'prompt':prompt,'old_thread':old_binding['thread_id'],'new_thread':binding['thread_id']},ensure_ascii=False,indent=2)+'\n')
        observer.bring_to_front()
        observer.screenshot(path=str(tmp_path/'terminal.png'),full_page=True)
        print(json.dumps({'proof':'actual_issued_native_terminal','outcome':outcome,'request_id':str(identifier),
            'state':expected,'origin_deadline':str(origin_deadline),'completed_observed':str(completed_observed),'preserved_prefix':prefix,'completed_history':str(completed_id) if completed_id else None,
            'no_retry_allocation_count':1,'api_origins':[api,second_api],'explicit_followup':str(followup['id']),'native_log':str(native_log)}),flush=True)
    finally:
        release.touch(exist_ok=True);context.close();proxy.close();observer_proxy.close()
