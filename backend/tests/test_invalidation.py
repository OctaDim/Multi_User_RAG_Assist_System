"""U7 transport races on real HTTP/DB; fixture principals are component contracts."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx
import pytest


@contextmanager
def held_apis(environment, tmp_path, *, backpressure_path=None, originals=None, serialization_delay=None):
    """Outer test ASGI pause after preparation; production H11 still performs writes."""
    held, release = tmp_path/'held', tmp_path/'release'
    launcher = tmp_path/'held-api.py'
    launcher.write_text(f'''import asyncio,socket,time
from pathlib import Path
from app import main
original=main.app
pressure_path={backpressure_path!r}
if pressure_path is not None:
    class Probe(main.GuardedH11Protocol):
        def connection_made(self,transport):
            super().connection_made(transport)
            transport.get_extra_info('socket').setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,16384)
            transport.set_write_buffer_limits(high=1,low=0)
        def pause_writing(self):
            super().pause_writing()
            Path({str(tmp_path/'real-pause')!r}).write_text('actual asyncio transport backpressure')
        def handle_events(self):
            previous=self.cycle
            super().handle_events()
            if self.cycle is not None and self.cycle is not previous:
                cycle=self.cycle
                drain=cycle.flow.drain
                async def observed_drain():
                    if cycle.scope['path']==pressure_path:
                        Path({str(tmp_path/'target-drain')!r}).write_text('actual network wait before private write')
                    await drain()
                cycle.flow.drain=observed_drain
    main.GuardedH11Protocol=Probe
serialization_delay={serialization_delay!r}
if serialization_delay is not None:
    from app import handoff
    original_bytes=handoff.json_bytes
    def slow_encoding(value):
        result=original_bytes(value)
        if isinstance(value,dict) and isinstance(value.get('account'),dict) and str(value['account']['id'])=={str(environment['user']['id'])!r}:
            time.sleep(serialization_delay)
        return result
    handoff.json_bytes=slow_encoding
class HoldBody:
    async def __call__(self,scope,receive,send):
        async def handoff(message):
            kind=dict(scope.get('headers',[])).get(b'x-owned-kind')
            if (message['type']=='http.response.body' and message.get('body')
                and (b'x-owned-pause',b'u7-proof') in scope.get('headers',[])
                and (kind is None or b'"kind": "'+kind+b'"' in message['body'])):
                Path({str(held)!r}).write_text('prepared')
                while not Path({str(release)!r}).exists():await asyncio.sleep(.01)
            await send(message)
        await original(scope,receive,handoff)
main.app=HoldBody()
main.main()
''')
    ports=[unused_port(),unused_port()]
    processes, logs=[],[]
    clients=[]
    try:
        env=dict(os.environ,RAG_DATABASE_URL=environment['dsn'],RAG_ORIGINALS_DIR=str(originals or tmp_path/'originals'))
        for index,port in enumerate(ports):
            log=(tmp_path/f'held-api-{index}.log').open('xb');logs.append(log)
            command=[sys.executable,str(launcher),'--port',str(port)] if index==0 else [str(Path('backend/.venv/bin/rag-api').absolute()),'--port',str(port)]
            process=subprocess.Popen(command,cwd='backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            processes.append(process);wait_ready(port,process)
            clients.append(httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=10))
        yield ports,clients,held,release
    finally:
        release.touch(exist_ok=True)
        for client in clients:client.close()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:process.wait(10)
                except subprocess.TimeoutExpired:process.kill();process.wait(10)
        for log in logs:log.close()


def wait_marker(marker):
    until=time.monotonic()+10
    while not marker.exists() and time.monotonic()<until:time.sleep(.01)
    assert marker.exists(),'Private response never reached prepared-body pause'


def paused_get(port,path,token,extra=''):
    peer=socket.create_connection(('127.0.0.1',port),timeout=5)
    peer.sendall((f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nX-Owned-Pause: u7-proof\r\n{extra}Connection: close\r\n\r\n').encode())
    return peer


def receive_all(peer):
    data=b''
    try:
        while chunk:=peer.recv(65536):data+=chunk
    finally:peer.close()
    return data


@pytest.mark.parametrize('route',['/api/accounts','/api/settings'])
def test_role_downgrade_closes_prepared_admin_response(environment,tmp_path,route):
    with held_apis(environment,tmp_path) as (ports,clients,held,release):
        peer=paused_get(ports[0],route,environment['super_admin']['token'])
        wait_marker(held)
        mutation=clients[1].patch('/api/accounts/'+str(environment['super_admin']['id']),
            json={'role':'user'},headers={'Authorization':'Bearer '+environment['super_admin']['token']})
        assert mutation.status_code==200
        release.touch()
        data=receive_all(peer)
        assert b'"max_active"' not in data and str(environment['admin']['id']).encode() not in data


@pytest.mark.parametrize('format',['original','png','json'])
def test_deleted_document_closes_prepared_original_png_and_json(environment,tmp_path,format):
    from io import BytesIO
    from PIL import Image,ImageDraw
    with held_apis(environment,tmp_path) as (ports,clients,held,release):
        headers={'Authorization':'Bearer '+environment['user']['token']}
        image=Image.new('RGB',(320,160),'white');ImageDraw.Draw(image).text((20,20),'PRIVATE ORIGINAL 100',fill='black')
        pdf=BytesIO();image.save(pdf,format='PDF');content=pdf.getvalue()
        admitted=clients[1].post('/api/documents/uploads',headers=headers,json={'files':[{'name':'private.pdf','size':len(content)}]})
        identifier=admitted.json()['documents'][0]['id']
        assert clients[1].put(f'/api/documents/{identifier}/original',headers=headers,content=content).status_code==200
        route=f'/api/documents/{identifier}/'+('pages/1/original' if format=='png' else 'original')
        if format=='json':route='/api/documents'
        peer=paused_get(ports[0],route,environment['user']['token']);wait_marker(held)
        assert clients[1].delete(f'/api/documents/{identifier}',headers=headers).status_code==200
        release.touch();data=receive_all(peer)
        if format=='json':assert identifier.encode() not in data,'Deleted source remained in prepared library JSON'
        else:assert (b'\x89PNG' if format=='png' else b'%PDF') not in data,'Deleted original escaped after source fence'


def test_account_view_is_freshly_serialized_at_handoff(environment,tmp_path):
    with held_apis(environment,tmp_path) as (ports,clients,held,release):
        peer=paused_get(ports[0],'/api/accounts/me',environment['user']['token']);wait_marker(held)
        response=clients[1].patch('/api/accounts/'+str(environment['user']['id']),json={'role':'admin'},
            headers={'Authorization':'Bearer '+environment['super_admin']['token']})
        assert response.status_code==200
        release.touch();data=receive_all(peer)
        assert b'"role":"admin"' in data and b'"role":"user"' not in data


def test_generic_asgi_without_private_handoff_fails_closed(environment,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    with TestClient(create_app()) as client:
        response=client.get('/api/accounts/me',headers={'Authorization':'Bearer '+environment['user']['token']})
        assert response.status_code==503 and response.json()=={'error':'protected_transport_unavailable'}
        assert client.post('/api/accounts/login',json={'email':'a@b.test','password':'Owned long password'}).status_code==503


async def test_deduplicated_completed_ack_contains_citations(session, environment,connection,rag_pool):
    from uuid import uuid4
    from app import answers
    from test_rag_context import run,complete
    key=uuid4()
    async def send():
        return await answers.admit(session,environment['user']['token'],environment['conversation'],key,
            'What is the annual budget?',[environment['document']],environment['tab'],environment['proof'])
    request=await send();await run(rag_pool,request)
    await connection.execute('UPDATE requests SET answer_text=%s WHERE id=%s',('100 euros [source:1]',request['id']))
    await complete(session,request,'100 euros [source:1]')
    snapshot=await answers.snapshot(session,environment['user']['token'],environment['conversation'])
    assert (await send())['citations']==snapshot['requests'][0]['citations']
    assert (await send())['citations'][0]['quote']=='The annual budget is 100 euros.'


async def test_correction_marks_request_snapshot_and_notifies_all_tabs(session, environment,connection,rag_pool):
    from app import answers,sources,events
    from conftest import seed_revision
    from test_source_contract import send
    from test_rag_context import run,complete
    request=await send(session,environment);await run(rag_pool,request)
    await connection.execute('UPDATE requests SET answer_text=%s WHERE id=%s',('100 euros [source:1]',request['id']))
    await complete(session,request,'100 euros [source:1]')
    before=await answers.snapshot(session,environment['user']['token'],environment['conversation'])
    revision,_=await seed_revision(connection,environment['document'],text='The budget is 10 euros.',attach=False)
    await sources.change_source(session,environment['user']['token'],environment['document'],revision_id=revision)
    after=await answers.snapshot(session,environment['user']['token'],environment['conversation'])
    projected=after['requests'][0]
    assert projected['source_flags']=={str(environment['document']):'corrected'} and projected['excluded']
    assert projected['version']>before['requests'][0]['version']
    assert projected['citations'][0]['quote']=='The annual budget is 100 euros.'
    event=await events.read(session,environment['user']['token'],environment['tab'],environment['proof'],1,before['watermark'])
    assert event['kind']=='source_status' and event['payload']['source_flags']==projected['source_flags']


@pytest.mark.parametrize('invalidation',['delete','connection','proof'])
@pytest.mark.parametrize('kind',['fragments','output'])
async def test_prepared_sse_and_replay_rechecks_source_and_tab(session, environment,connection,rag_pool,tmp_path,invalidation,kind):
    import asyncio
    from app import answers,sources,auth
    from test_source_contract import send
    from test_rag_context import run
    request=await send(session,environment);await run(rag_pool,request)
    if kind=='output':
        async with session.begin():
            await (await session.connection()).exec_driver_sql("UPDATE requests SET state='generating',answer_text='UNDISPATCHED PRIVATE TOKEN',version=version+1 WHERE id=%s",(request['id'],))
            await (await session.connection()).exec_driver_sql("INSERT INTO messages(request_id,conversation_id,role,text) VALUES (%s,%s,'assistant','UNDISPATCHED PRIVATE TOKEN')",(request['id'],environment['conversation']))
            updated=(await (await session.connection()).exec_driver_sql('SELECT * FROM requests WHERE id=%s',(request['id'],))).mappings().first()
            await answers.event(session,updated,'output',{'text':'UNDISPATCHED PRIVATE TOKEN','version':updated['version']})
    with held_apis(environment,tmp_path) as (ports,clients,held,release):
        peer=paused_get(ports[0],f"/api/tabs/{environment['tab']}/events",environment['user']['token'],
            f"X-Tab-Proof: {environment['proof']}\r\nLast-Event-ID: 0\r\nX-Owned-Kind: {kind}\r\n")
        await asyncio.to_thread(wait_marker,held)
        if invalidation=='delete':
            await sources.change_source(session,environment['user']['token'],environment['document'],deleted=True)
        else:
            async with session.begin():
                await auth.lock_service(session)
                column='connection_epoch=connection_epoch+1' if invalidation=='connection' else "proof_hash='no-longer-the-proof'"
                await (await session.connection()).exec_driver_sql('UPDATE tabs SET '+column+' WHERE id=%s',(environment['tab'],))
        release.touch()
        def bounded_receive():
            data=b'';peer.settimeout(.6)
            try:
                while chunk:=peer.recv(65536):data+=chunk
            except socket.timeout:pass
            finally:peer.close()
            return data
        data=await asyncio.to_thread(bounded_receive)
        forbidden=b'UNDISPATCHED PRIVATE TOKEN' if kind=='output' else b'The annual budget is 100 euros.'
        assert forbidden not in data,'Previously read private event escaped its source/tab fence'


async def test_prepared_snapshot_retains_old_quote_with_current_correction_flags(session, environment,connection,rag_pool,tmp_path):
    import asyncio
    from app import sources
    from test_source_contract import send
    from test_rag_context import run,complete
    from conftest import seed_revision
    request=await send(session,environment);await run(rag_pool,request)
    await connection.execute('UPDATE requests SET answer_text=%s WHERE id=%s',('100 euros [source:1]',request['id']))
    await complete(session,request,'100 euros [source:1]')
    with held_apis(environment,tmp_path) as (ports,clients,held,release):
        peer=paused_get(ports[0],f"/api/conversations/{environment['conversation']}",environment['user']['token'])
        await asyncio.to_thread(wait_marker,held)
        revision,_=await seed_revision(connection,environment['document'],text='Budget 10 euros.',attach=False)
        await sources.change_source(session,environment['user']['token'],environment['document'],revision_id=revision)
        release.touch();data=await asyncio.to_thread(receive_all,peer)
        assert b'The annual budget is 100 euros.' in data and b'"corrected"' in data and b'"excluded":true' in data


async def test_irreducible_native_question_budget_refuses_before_admission(session, environment,connection):
    from uuid import uuid4
    from app import answers
    from app.auth import AccessError
    with pytest.raises(AccessError,match='context_too_large'):
        await answers.admit(session,environment['user']['token'],environment['conversation'],uuid4(),
            'Ж budget 100 ' * 4096,[environment['document']],environment['tab'],environment['proof'])
    assert (await (await connection.execute('SELECT count(*) AS n FROM messages')).fetchone())['n']==0
    assert (await (await connection.execute('SELECT count(*) AS n FROM requests')).fetchone())['n']==0


async def test_correction_between_preparation_and_pending_checkpoint_keeps_current_generation(session, environment,connection,rag_pool,monkeypatch):
    import asyncio
    from app import sources
    from app.rag import GuardedSaver
    from app.generation import Coordinator
    from conftest import seed_revision
    from test_source_contract import send
    from test_scheduler import TokenRuntime
    from test_rag_context import ContractEmbedder
    request=await send(session,environment)
    prepared,release=asyncio.Event(),asyncio.Event()
    original=GuardedSaver.aput_writes
    async def held_write(self,config,writes,task_id,task_path=''):
        if any(channel=='prompt' for channel,_ in writes):
            prepared.set();await release.wait()
        return await original(self,config,writes,task_id,task_path)
    monkeypatch.setattr(GuardedSaver,'aput_writes',held_write)
    coordinator=Coordinator(rag_pool,1,TokenRuntime(),ContractEmbedder())
    task=asyncio.create_task(coordinator.prepare_next())
    try:
        await asyncio.wait_for(prepared.wait(),10)
        revision,_=await seed_revision(connection,environment['document'],text='Corrected budget 10',attach=False)
        await sources.change_source(session,environment['user']['token'],environment['document'],revision_id=revision)
        release.set();await task
        row=await (await connection.execute('SELECT * FROM requests WHERE id=%s',(request['id'],))).fetchone()
        assert row['state']=='queued','OCR correction introduced cancellation before native allocation'
        await coordinator.admit_ready();await coordinator.step()
        row=await (await connection.execute('SELECT * FROM requests WHERE id=%s',(request['id'],))).fetchone()
        assert row['state']=='generating' and row['answer_text']
        message=await (await connection.execute("SELECT * FROM messages WHERE request_id=%s AND role='assistant'",(request['id'],))).fetchone()
        assert message['excluded'] and message['source_flags']=={str(environment['document']):'corrected'}
    finally:
        release.set();await asyncio.gather(task,return_exceptions=True);await coordinator.close()


async def test_correction_of_prior_history_after_admission_keeps_current_question(session, environment,connection,rag_pool):
    from app import sources
    from app.generation import Coordinator
    from conftest import seed_revision
    from test_source_contract import send
    from test_rag_context import run,complete,ContractEmbedder
    from test_scheduler import TokenRuntime
    previous=await send(session,environment);await run(rag_pool,previous);await complete(session,previous,'OLD HISTORY 100')
    current=await send(session,environment)
    revision,_=await seed_revision(connection,environment['document'],text='Corrected budget 10',attach=False)
    await sources.change_source(session,environment['user']['token'],environment['document'],revision_id=revision)
    coordinator=Coordinator(rag_pool,1,TokenRuntime(),ContractEmbedder())
    try:
        await coordinator.prepare_next()
        row=await (await connection.execute('SELECT * FROM requests WHERE id=%s',(current['id'],))).fetchone()
        assert row['state']=='queued','Correction of prior history cancelled the already accepted question'
        assert 'OLD HISTORY 100' not in coordinator.prepared[current['id']]['prompt']
    finally:await coordinator.close()


async def test_fresh_handoff_snapshot_watermark_is_the_actual_replay_cursor(session, environment,connection,tmp_path):
    import asyncio,re
    from uuid import uuid4
    from app import answers,events
    from test_source_contract import send
    await send(session,environment)
    with held_apis(environment,tmp_path) as (ports,clients,held,release):
        peer=paused_get(ports[0],f"/api/tabs/{environment['tab']}/events",environment['user']['token'],
            f"X-Tab-Proof: {environment['proof']}\r\nX-Owned-Kind: snapshot\r\n")
        await asyncio.to_thread(wait_marker,held)
        prefix=await asyncio.to_thread(peer.recv,65536)
        heartbeat=json.loads(re.search(rb'data: (.+)\n\n',prefix).group(1))['payload']
        await events.ack(session,environment['user']['token'],environment['tab'],environment['proof'],
            heartbeat['connection_epoch'],heartbeat['challenge'])
        room=await answers.create_conversation(session,environment['user']['token'])
        await answers.admit(session,environment['user']['token'],room['id'],uuid4(),'NEW COMMITTED QUESTION',
            [environment['document']],environment['tab'],environment['proof'])
        release.touch()
        def receive():
            data=prefix;peer.settimeout(.8)
            try:
                while chunk:=peer.recv(65536):data+=chunk
            except socket.timeout:pass
            finally:peer.close()
            return data
        data=await asyncio.to_thread(receive)
        values=[json.loads(match) for match in re.findall(rb'data: (.+)\n\n',data)]
        snapshot=next(value for value in values if value['kind']=='snapshot')
        assert b'NEW COMMITTED QUESTION' in data
        position=values.index(snapshot)
        assert all(value['id']>snapshot['id'] for value in values[position+1:] if 'id' in value),values


async def test_minted_login_token_is_fenced_before_private_body(environment,connection,tmp_path):
    import asyncio
    from app.accounts import hash_password
    password='An actual long owned password'
    encoded=await asyncio.to_thread(hash_password,password)
    await connection.execute('UPDATE accounts SET email=%s,password_hash=%s WHERE id=%s',('login-race@owned.test',encoded,environment['user']['id']))
    with held_apis(environment,tmp_path) as (ports,clients,held,release):
        body=json.dumps({'email':'login-race@owned.test','password':password}).encode()
        peer=socket.create_connection(('127.0.0.1',ports[0]),timeout=5)
        peer.sendall((f'POST /api/accounts/login HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nX-Owned-Pause: u7-proof\r\nConnection: close\r\n\r\n').encode()+body)
        await asyncio.to_thread(wait_marker,held)
        response=clients[1].patch('/api/accounts/'+str(environment['user']['id']),headers={
            'Authorization':'Bearer '+environment['super_admin']['token']},json={'disabled':True})
        assert response.status_code==200
        release.touch();data=await asyncio.to_thread(receive_all,peer)
        assert b'"token":' not in data,'Newly minted credential escaped a committed account fence'


@pytest.mark.parametrize('mutation',['logout','expiry','soft_delete'])
async def test_current_session_fences_prepared_json_but_logout_ack_stays_minimal(environment,connection,tmp_path,mutation):
    import asyncio
    with held_apis(environment,tmp_path) as (ports,clients,held,release):
        peer=paused_get(ports[0],'/api/accounts/me',environment['user']['token']);await asyncio.to_thread(wait_marker,held)
        headers={'Authorization':'Bearer '+environment['user']['token']}
        if mutation=='logout':
            response=clients[1].post('/api/accounts/logout',headers=headers)
            assert response.status_code==200 and response.json()=={'logged_out':True}
        elif mutation=='expiry':
            await connection.execute("UPDATE sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",(environment['user']['session_id'],))
        else:
            assert clients[1].patch('/api/accounts/'+str(environment['user']['id']),json={'active':False},headers={
                'Authorization':'Bearer '+environment['super_admin']['token']}).status_code==200
        release.touch();data=await asyncio.to_thread(receive_all,peer)
        assert str(environment['user']['id']).encode() not in data
        assert clients[1].post('/api/accounts/logout',headers=headers).json()=={'logged_out':True}


async def test_natural_session_expiry_during_serialization_closes_unhanded_body(environment,connection,tmp_path):
    import asyncio
    with held_apis(environment,tmp_path,serialization_delay=2) as (ports,clients,_,_):
        await connection.execute("UPDATE sessions SET expires_at=clock_timestamp()+interval '1 second' WHERE id=%s",(environment['user']['session_id'],))
        peer=socket.create_connection(('127.0.0.1',ports[0]),timeout=5)
        peer.sendall((f"GET /api/accounts/me HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {environment['user']['token']}\r\nConnection: close\r\n\r\n").encode())
        data=await asyncio.to_thread(receive_all,peer)
        assert str(environment['user']['id']).encode() not in data,'Session expired during encoding but the private body was still handed off'


@pytest.mark.parametrize('mutation',['timeout','delete'])
async def test_real_database_complete_races_invalidation_with_one_terminal_outcome(session, environment,connection,rag_pool,mutation):
    import asyncio
    from app import sources,events
    from app.generation import Coordinator
    from test_source_contract import send
    from test_rag_context import run
    request=await send(session,environment);await run(rag_pool,request)
    await connection.execute("UPDATE requests SET state='generating',answer_text='COMMITTED PREFIX' WHERE id=%s",(request['id'],))
    await connection.execute("INSERT INTO messages(request_id,conversation_id,role,text) VALUES (%s,%s,'assistant','COMMITTED PREFIX')",(request['id'],environment['conversation']))
    if mutation=='timeout':
        await connection.execute("UPDATE tabs SET connected=false,confirmed=false,deadline=clock_timestamp()-interval '1 second' WHERE id=%s",(environment['tab'],))
    start=asyncio.Event()
    async def finish():
        await start.wait()
        await Coordinator(rag_pool,1,None,None).finish(request['id'],'completed',None)
    async def invalidate():
        async with rag_pool.session() as other:
            await start.wait()
            if mutation=='timeout':await events.expire_due(other)
            else:await sources.change_source(other,environment['user']['token'],environment['document'],deleted=True)
    tasks=[asyncio.create_task(finish()),asyncio.create_task(invalidate())]
    start.set();await asyncio.gather(*tasks)
    row=await (await connection.execute('SELECT * FROM requests WHERE id=%s',(request['id'],))).fetchone()
    assert row['state'] in ('completed','interrupted')
    terminal=await (await connection.execute("SELECT * FROM events WHERE request_id=%s AND kind='terminal'",(request['id'],))).fetchall()
    assert len(terminal)==1 and terminal[0]['payload']['state']==row['state']
    assert row['answer_text']=='COMMITTED PREFIX'
    message=await (await connection.execute("SELECT * FROM messages WHERE request_id=%s AND role='assistant'",(request['id'],))).fetchone()
    assert message['text']=='COMMITTED PREFIX'
    if mutation=='delete':assert message['excluded'] and list(message['source_flags'].values())==['deleted']


async def test_real_database_output_races_account_revoke_without_late_publication(session, environment,connection,rag_pool):
    import asyncio,threading
    from app import accounts
    from app.generation import Coordinator
    from test_source_contract import send
    from test_scheduler import TokenRuntime
    from test_rag_context import ContractEmbedder
    request=await send(session,environment)
    runtime=TokenRuntime();coordinator=Coordinator(rag_pool,1,runtime,ContractEmbedder())
    computed,release=threading.Event(),threading.Event()
    try:
        await coordinator.prepare_next();await coordinator.admit_ready();await coordinator.step()
        row=await (await connection.execute('SELECT * FROM requests WHERE id=%s',(request['id'],))).fetchone()
        prefix=row['answer_text'];assert prefix
        runtime.advance_hook=lambda context:(computed.set(),release.wait(10))
        task=asyncio.create_task(coordinator.step())
        assert await asyncio.to_thread(computed.wait,5)
        async with rag_pool.session() as independent:
            await accounts.mutate(independent,environment['super_admin']['token'],environment['user']['id'],{'disabled':True})
        watermark=(await (await connection.execute('SELECT max(id) AS id FROM events WHERE request_id=%s',(request['id'],))).fetchone())['id']
        release.set();await task
        row=await (await connection.execute('SELECT * FROM requests WHERE id=%s',(request['id'],))).fetchone()
        assert row['state']=='interrupted' and row['answer_text']==prefix
        assert not await (await connection.execute("SELECT 1 FROM events WHERE request_id=%s AND id>%s AND kind='output'",(request['id'],watermark))).fetchone()
        assert (await (await connection.execute("SELECT count(*) AS n FROM events WHERE request_id=%s AND kind='terminal'",(request['id'],))).fetchone())['n']==1
    finally:release.set();await coordinator.close()


async def test_stop_old_request_races_new_admission_and_old_pending_writes_cannot_change_new_context(session, environment,connection,rag_pool):
    import asyncio
    from uuid import uuid4
    from app import answers
    from app.auth import AccessError
    from test_source_contract import send
    from test_rag_context import run,saver_for
    old=await send(session,environment);await run(rag_pool,old)
    saver=await saver_for(rag_pool,connection,old)
    config={'configurable':{'thread_id':saver.binding['thread_id']}}
    checkpoint=await saver.aget_tuple(config)
    await answers.stop(session,environment['user']['token'],old['id'])
    start=asyncio.Event()
    async def stop_again():
        async with rag_pool.session() as independent:
            await start.wait();return await answers.stop(independent,environment['user']['token'],old['id'])
    async def new_question():
        async with rag_pool.session() as independent:
            await start.wait();return await answers.admit(independent,environment['user']['token'],environment['conversation'],
                uuid4(),'NEW CURRENT QUESTION',[environment['document']],environment['tab'],environment['proof'])
    tasks=[asyncio.create_task(stop_again()),asyncio.create_task(new_question())]
    start.set();repeated,new=await asyncio.gather(*tasks)
    assert repeated['id']==old['id'] and new['id']!=old['id'] and new['state']=='accepted'
    await run(rag_pool,new)
    for operation in (saver.aput_writes(checkpoint.config,[('prompt','LATE OLD SECRET')],'late-old'),
        saver.aput(checkpoint.config,checkpoint.checkpoint,{'source':'update','step':99,'parents':{}},{})):
        with pytest.raises(AccessError,match='terminal_request'):await operation
    current=await saver_for(rag_pool,connection,new)
    state=await current.aget_tuple({'configurable':{'thread_id':current.binding['thread_id']}})
    assert 'NEW CURRENT QUESTION' in state.checkpoint['channel_values']['prompt']
    assert 'LATE OLD SECRET' not in repr(state.checkpoint)
    assert (await (await connection.execute('SELECT state FROM requests WHERE id=%s',(new['id'],))).fetchone())['state']=='queued'


@pytest.mark.parametrize('target',['json','file','png','snapshot','replay'])
def test_real_socket_backpressure_revocation_holds_no_database_locks(environment,tmp_path,target):
    from io import BytesIO
    from PIL import Image
    headers={'Authorization':'Bearer '+environment['user']['token']}
    # The first response fills the actual kernel/asyncio send buffer. A pipelined
    # second private response is prepared while its transport cannot yet write.
    # No flow.pause_writing call or synthetic drain gate is used by this test.
    route='/api/accounts/me'
    if target in ('snapshot','replay'):route=f"/api/tabs/{environment['tab']}/events"
    # Uploads are genuine HTTP files, even in this fixture-principal component proof.
    preparation=tmp_path/'setup';preparation.mkdir()
    with held_apis(environment,preparation,originals=tmp_path/'originals') as (_,setup,_,_):
        large=b'BUFFER PRESSURE '+os.urandom(3*1024*1024-len(b'BUFFER PRESSURE ')-1)
        batch=setup[1].post('/api/documents/uploads',headers=headers,json={'files':[{'name':'pressure.txt','size':len(large)}]}).json()
        pressure=batch['documents'][0]['id']
        assert setup[1].put(f'/api/documents/{pressure}/original',headers=headers,content=large).status_code==200
        pdf=BytesIO();Image.new('RGB',(64,64),'white').save(pdf,format='PDF');small=pdf.getvalue()
        batch=setup[1].post('/api/documents/uploads',headers=headers,json={'files':[{'name':'target.pdf','size':len(small)}]}).json()
        document=batch['documents'][0]['id']
        assert setup[1].put(f'/api/documents/{document}/original',headers=headers,content=small).status_code==200
        if target in ('snapshot','replay'):
            from uuid import uuid4
            admitted=setup[1].post(f"/api/conversations/{environment['conversation']}/answers",headers=headers|{'X-Tab-Proof':environment['proof']},
                json={'operation_key':str(uuid4()),'question':'UNHANDED PRIVATE QUESTION',
                    'document_ids':[str(environment['document'])],'tab_id':str(environment['tab'])})
            assert admitted.status_code==200
    if target in ('file','png'):route=f'/api/documents/{document}/'+('original' if target=='file' else 'pages/1/original')
    with held_apis(environment,tmp_path,backpressure_path=route) as (ports,clients,_,_):
        if target=='png':
            assert clients[0].get(route,headers=headers).status_code==200
            (tmp_path/'target-drain').unlink(missing_ok=True)
            (tmp_path/'real-pause').unlink(missing_ok=True)
        peer=socket.socket();peer.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,65536);peer.settimeout(10)
        peer.connect(('127.0.0.1',ports[0]))
        extra=f"X-Tab-Proof: {environment['proof']}\r\n" if target in ('snapshot','replay') else ''
        if target=='replay':extra+='Last-Event-ID: 0\r\n'
        peer.sendall((f"GET /api/documents/{pressure}/original HTTP/1.1\r\nHost: localhost\r\nAuthorization: {headers['Authorization']}\r\n\r\n"
            f"GET {route} HTTP/1.1\r\nHost: localhost\r\nAuthorization: {headers['Authorization']}\r\n{extra}Connection: close\r\n\r\n").encode())
        received=b'';until=time.monotonic()+20
        try:
            while not (tmp_path/'target-drain').exists() and time.monotonic()<until:
                received+=peer.recv(2048)
                time.sleep(.008 if target=='png' else .003)
            assert (tmp_path/'real-pause').exists() and (tmp_path/'target-drain').exists(),'Actual private-response network drainage was not observed'
            response=clients[1].patch('/api/accounts/'+str(environment['user']['id']),headers={
                'Authorization':'Bearer '+environment['super_admin']['token']},json={'disabled':True},timeout=3)
            assert response.status_code==200,'Network backpressure held a DB invalidation lock'
            received+=receive_all(peer)
            forbidden={
                'file':b'%PDF', 'png':b'\x89PNG',
                'snapshot':b'UNHANDED PRIVATE QUESTION', 'replay':b'UNHANDED PRIVATE QUESTION',
                'json':str(environment['user']['id']).encode(),
            }[target]
            assert forbidden not in received,'Unhanded private response escaped after actual network drainage'
        finally:peer.close()
from urllib.request import Request, urlopen


def unused_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


def wait_ready(port, process):
    deadline = time.monotonic()+15
    while time.monotonic() < deadline:
        assert process.poll() is None, 'Owned API exited'
        try:
            with urlopen(f'http://127.0.0.1:{port}/openapi.json', timeout=.3):
                return
        except OSError:
            time.sleep(.05)
    raise AssertionError('Owned API did not become ready')


def test_account_revoke_closes_prepared_body_before_real_handoff(environment, tmp_path):
    held, release = tmp_path/'prepared-body', tmp_path/'release-body'
    launcher = tmp_path/'held-api.py'
    launcher.write_text(f'''import asyncio,sys
from pathlib import Path
from app import main
original=main.app
class HoldBody:
    async def __call__(self,scope,receive,send):
        async def handoff(message):
            if (scope.get('path')=='/api/accounts/me' and message['type']=='http.response.body'
                and (b'x-owned-pause',b'u7-proof') in scope.get('headers',[])):
                Path({str(held)!r}).write_text('prepared')
                while not Path({str(release)!r}).exists():await asyncio.sleep(.01)
            await send(message)
        await original(scope,receive,handoff)
main.app=HoldBody()
main.main()
''')
    ports = [unused_port(), unused_port()]
    processes, logs = [], []
    peer = None
    try:
        env = dict(os.environ, RAG_DATABASE_URL=environment['dsn'])
        for index, port in enumerate(ports):
            log = (tmp_path/f'api-{index}.log').open('wb'); logs.append(log)
            command = [sys.executable, str(launcher), '--port', str(port)] if index==0 else [str(Path('backend/.venv/bin/rag-api').absolute()), '--port', str(port)]
            process = subprocess.Popen(command, cwd='backend', env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            wait_ready(port, process)
        peer = socket.create_connection(('127.0.0.1', ports[0]), timeout=5)
        peer.sendall((f"GET /api/accounts/me HTTP/1.1\r\nHost: 127.0.0.1:{ports[0]}\r\n"
                      f"Authorization: Bearer {environment['user']['token']}\r\nX-Owned-Pause: u7-proof\r\nConnection: close\r\n\r\n").encode())
        deadline = time.monotonic()+10
        while not held.exists() and time.monotonic()<deadline:
            time.sleep(.01)
        assert held.exists(), 'Private response never reached the prepared-body pause'
        mutation = Request(f"http://127.0.0.1:{ports[1]}/api/accounts/{environment['user']['id']}",
            data=json.dumps({'disabled':True}).encode(), method='PATCH',
            headers={'Content-Type':'application/json','Authorization':f"Bearer {environment['super_admin']['token']}"})
        with urlopen(mutation, timeout=3) as response:
            assert response.status==200
        release.write_text('released after committed revocation')
        received = b''
        while data := peer.recv(65536):
            received += data
        assert str(environment['user']['id']).encode() not in received, 'Prepared private body escaped after access revocation'
    finally:
        release.touch(exist_ok=True)
        if peer is not None:peer.close()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:process.wait(10)
                except subprocess.TimeoutExpired:process.kill();process.wait(10)
        for log in logs:log.close()
