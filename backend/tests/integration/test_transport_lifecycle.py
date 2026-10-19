"""Genuine issuer/publisher requests through socket proxies and both real APIs."""
import json
import os
from pathlib import Path
import re
import select
import socket
from socketserver import BaseRequestHandler, ThreadingTCPServer
import subprocess
import sys
from threading import Lock, Thread
import time
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from playwright.sync_api import expect
import pytest

from integration.test_answer_lifecycle import environment
from browser.test_accounts import BACKEND, real_account_browser, register, login, navigate, open_conversations, open_sources
from browser.test_documents import real_document_browser, ready



@pytest.fixture
def paused_native_browser(real_document_browser,environment,tmp_path,request):
    marker,release=tmp_path/'native-pause',tmp_path/'native-release'
    mode=request.param
    hook=tmp_path/'native-worker.py'
    hook.write_text(f'''import logging,time
from pathlib import Path
from app.llama_runtime import LlamaContext
logging.basicConfig(level=logging.DEBUG)
original=LlamaContext.advance
marker=Path({str(marker)!r});release=Path({str(release)!r})
def advance(self):
    if not marker.exists() and ({mode!r}=='before' or (len(self.output_tokens)>=3 and not self._decoder.getstate()[0])):
        marker.write_text('inside real native context')
        while not release.exists():time.sleep(.01)
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
    log_path=tmp_path/'generation.log'
    with log_path.open('xb') as log:
        process=subprocess.Popen([sys.executable,str(launcher)],cwd=BACKEND,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
        try:
            until=time.monotonic()+30
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                while True:
                    row=connection.execute('SELECT epoch,healthy_until>clock_timestamp() FROM coordinator_lease WHERE id=1').fetchone()
                    if row[0]>previous_epoch and row[1]:break
                    assert process.poll() is None and time.monotonic()<until,log_path.read_text()
                    time.sleep(.05)
            yield real_document_browser,marker,release,log_path,mode
        finally:
            release.touch(exist_ok=True)
            process.terminate()
            try:process.wait(15)
            except subprocess.TimeoutExpired:process.kill();process.wait(10)
            records=[json.loads(line) for line in log_path.read_text().splitlines() if line.startswith('{"event": "native_spawn"')]
            assert all(not Path(f"/proc/{row['pid']}").exists() for row in records)


class CutProxy(ThreadingTCPServer):
    daemon_threads=True
    def __init__(self,target):
        self.target=target;self.enabled=True;self.connections=set();self.lock=Lock()
        super().__init__(('127.0.0.1',0),Pipe)
        self.thread=Thread(target=self.serve_forever,daemon=True);self.thread.start()

    def cut(self):
        self.enabled=False
        with self.lock:
            for stream in list(self.connections):
                try:stream.shutdown(socket.SHUT_RDWR)
                except OSError:pass

    def close(self):
        self.cut();self.shutdown();self.server_close();self.thread.join()


class Pipe(BaseRequestHandler):
    def handle(self):
        server=self.server
        if not server.enabled:return
        with socket.create_connection(server.target,timeout=10) as upstream:
            streams=[self.request,upstream]
            with server.lock:server.connections.update(streams)
            try:
                while server.enabled:
                    for source in select.select(streams,[],[],.1)[0]:
                        data=source.recv(65536)
                        if not data:return
                        streams[1 if source is streams[0] else 0].sendall(data)
            except OSError:
                pass
            finally:
                with server.lock:server.connections.difference_update(streams)


def through_proxy(page,proxy):
    url=f'http://127.0.0.1:{proxy.server_address[1]}'
    # Deployment configuration only. Fetch still traverses actual sockets;
    # the proxy copies bytes unchanged and never fabricates HTTP responses.
    page.add_init_script(script=f'''new MutationObserver((records,observer)=>{{
        const meta=document.querySelector('meta[name="api-origin"]');
        if(meta){{meta.content={json.dumps(url)};observer.disconnect();}}
    }}).observe(document,{{childList:true,subtree:true}});''')
    return url


@pytest.mark.parametrize('paused_native_browser',['after'],indirect=True)
def test_actual_two_tab_admission_proxy_recovery_background_and_origin_timeout(paused_native_browser,environment,tmp_path):
    ((browser,mailbox,frontend,first),_,_),marker,release,native_log,_=paused_native_browser
    api_log=tmp_path/'api-2.log'
    with api_log.open('xb') as stream:
        process=subprocess.Popen([str(BACKEND/'.venv/bin/rag-api'),'--port','0'],cwd=BACKEND,
            env=os.environ.copy(),stdout=stream,stderr=subprocess.STDOUT)
        proxies=[];context=browser.new_context()
        try:
            until=time.monotonic()+15
            while True:
                match=re.search(r'Uvicorn running on (http://127\.0\.0\.1:\d+)',api_log.read_text())
                if match:break
                assert process.poll() is None and time.monotonic()<until,api_log.read_text()
                time.sleep(.05)
            second=match.group(1)
            for api in [first,second]:
                parsed=urlsplit(api);proxies.append(CutProxy((parsed.hostname,parsed.port)))
            pages=[context.new_page(),context.new_page()]
            origins=[through_proxy(page,proxy) for page,proxy in zip(pages,proxies)]
            email='u8-proxy-owner@owned.test'
            register(pages[0],mailbox,frontend,email);login(pages[0],email)
            navigate(pages[0],'library')
            pages[0].locator('#document-upload input').set_input_files({'name':'proxy-budget.txt','mimeType':'text/plain',
                'buffer':b'The annual budget is 100 euros.'})
            pages[0].get_by_role('button',name='Загрузить документы',exact=True).click();ready(pages[0],'proxy-budget.txt')
            shared=pages[0].evaluate("async api=>{const id=sessionStorage.getItem('rag:conversation');await fetch(api+'/api/conversations',{method:'POST',headers:{Authorization:'Bearer '+sessionStorage.getItem('rag:credential'),'Content-Type':'application/json'},body:JSON.stringify({id})});return id;}",origins[0])
            pages[0].reload();expect(pages[0].locator('html')).to_have_attribute('data-ready','true')
            pages[1].goto(frontend);login(pages[1],email)
            pages[1].evaluate("id=>sessionStorage.setItem('rag:conversation',id)",shared)
            pages[1].reload();expect(pages[1].locator('html')).to_have_attribute('data-ready','true')
            credentials=[]
            for index,page in enumerate(pages):
                navigate(page,'chat')
                page.locator('#question').fill(f'Independent unsent tab draft {index}')
                navigate(page,'chat')
                open_sources(page)
                page.get_by_role('checkbox',name='proxy-budget.txt',exact=True).check()
                credentials.append(page.evaluate('''() => ({token:sessionStorage.getItem('rag:credential'),
                    tab:JSON.parse(sessionStorage.getItem('rag:tab')),conversation:sessionStorage.getItem('rag:conversation'),
                    document:document.querySelector('#question-sources input:checked').value})'''))
                expect(page.locator('#answer-connection')).to_contain_text('Соединение установлено')
            requests=[{'base':origins[index],'token':actor['token'],'proof':actor['tab']['proof'],'conversation':actor['conversation'],
                'body':{'operation_key':str(uuid4()),'question':['What is the annual budget?','What is the approved annual budget?'][index],
                    'tab_id':actor['tab']['id'],'document_ids':[actor['document']]}} for index,actor in enumerate(credentials)]
            replies=pages[0].evaluate('''async rows=>await Promise.all(rows.map(async row=>{
                const response=await fetch(row.base+'/api/conversations/'+row.conversation+'/answers',{method:'POST',
                    headers:{Authorization:'Bearer '+row.token,'X-Tab-Proof':row.proof,'Content-Type':'application/json'},body:JSON.stringify(row.body)});
                return {status:response.status,body:await response.json()};}))''',requests)
            assert sorted(row['status'] for row in replies)==[200,409],replies
            winner=next(index for index,row in enumerate(replies) if row['status']==200)
            owner,observer=pages[winner],pages[1-winner];proxy=proxies[winner]
            request_id=replies[winner]['body']['id'];conversation=credentials[winner]['conversation']
            expect(owner.locator('#history article')).to_have_count(1)
            expect(observer.locator('#history article')).to_have_count(1)
            until=time.monotonic()+30
            while not marker.exists():
                assert time.monotonic()<until;owner.wait_for_timeout(50)
            expect(owner.locator('#history .answer-text')).not_to_have_text('')
            with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                prefix=connection.execute('SELECT answer_text FROM requests WHERE id=%s',(request_id,)).fetchone()['answer_text']
            expect(owner.locator('#history .answer-text')).to_have_text(prefix)
            proxy.cut();owner.wait_for_timeout(5000);proxy.enabled=True
            expect(owner.locator('#answer-connection')).to_have_text('В этой беседе уже выполняется запрос.',timeout=8000)
            expect(owner.locator('#history .answer-text')).to_have_text(prefix)
            navigate(owner,'chat')
            owner.locator('#question').fill('Origin A draft')
            owner.get_by_role('button',name='Новая беседа',exact=True).click()
            expect(owner.locator('#conversations li')).to_have_count(1)
            background=owner.locator('#chat').get_attribute('data-conversation')
            navigate(owner,'chat')
            owner.locator('#question').fill('Origin B draft')
            open_conversations(owner)
            owner.locator(f'#conversations button[data-conversation="{conversation}"]').click()
            expect(owner.locator('#question')).to_have_value('Origin A draft')
            open_conversations(owner)
            owner.get_by_role('button',name='Новая беседа',exact=True).click()
            expect(owner.locator('#chat')).to_have_attribute('data-conversation',background)
            expect(owner.locator('#question')).to_have_value('Origin B draft')
            expect(owner.locator('#history')).to_have_text('В этой беседе пока нет сообщений.')
            with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                row=connection.execute('SELECT * FROM requests WHERE id=%s',(request_id,)).fetchone()
                assert row['state']=='generating' and row['answer_text']==prefix
            proxy.cut()
            expect(observer.locator('#history')).to_contain_text('Соединение вкладки потеряно',timeout=18000)
            expect(observer.locator('#question')).to_have_value(f'Independent unsent tab draft {1-winner}')
            proxy.enabled=True
            expect(owner.locator('#answer-connection')).to_contain_text('Соединение установлено',timeout=8000)
            release.touch()
            with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                row=connection.execute('SELECT * FROM requests WHERE id=%s',(request_id,)).fetchone()
                assert row['state']=='interrupted' and row['reason']=='tab_timeout'
                assert row['answer_text']==prefix
                assert connection.execute('SELECT count(*) AS n FROM requests').fetchone()['n']==1
                assistant=connection.execute("SELECT * FROM messages WHERE request_id=%s AND role='assistant'",(request_id,)).fetchone()
                assert assistant['excluded']
            owner.screenshot(path=str(tmp_path/'background-after-origin-timeout.png'),full_page=True)
            print(json.dumps({'proof':'genuine_two_api_proxy_tab_lifecycle','request_id':request_id,'winner':winner,
                'recovered_after_seconds':5,'observer_stayed_connected':True,'saved_prefix':prefix,'native_log':str(native_log)}),flush=True)
        finally:
            release.touch(exist_ok=True);context.close()
            for proxy in proxies:proxy.close()
            process.terminate()
            try:process.wait(15)
            except subprocess.TimeoutExpired:process.kill();process.wait(10)
