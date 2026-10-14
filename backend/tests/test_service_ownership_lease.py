"""Real PostgreSQL heartbeat delay; component proof, not issued-owner acceptance."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic

import pytest


@pytest.mark.parametrize('delay',[.8,5.5],ids=['within-confirmed-lease','past-confirmed-lease'])
async def test_real_query_delay_keeps_owner_until_confirmed_lease_bound(environment,connection,tmp_path,delay):
    log=tmp_path/'actual-supervisor.log'
    native_pid=None
    with log.open('xb') as out:
        process=subprocess.Popen([sys.executable,'-m','app.generation'],cwd='backend',
            env=dict(os.environ,RAG_DATABASE_URL=environment['dsn']),stdout=out,stderr=subprocess.STDOUT)
        try:
            until=monotonic()+30
            while True:
                assert process.poll() is None,log.read_text()
                lease=await (await connection.execute('SELECT epoch,healthy_until>clock_timestamp() AS healthy FROM coordinator_lease')).fetchone()
                if lease['epoch']>1 and lease['healthy']:break
                assert monotonic()<until
                await asyncio.sleep(.05)
            owner=next(json.loads(line) for line in log.read_text().splitlines() if line.startswith('{"event": "native_spawn"'))
            native_pid=owner['pid']
            async with connection.transaction():
                before=await (await connection.execute('SELECT epoch,extract(epoch FROM healthy_until-clock_timestamp()) AS remaining FROM coordinator_lease WHERE id=1 FOR UPDATE')).fetchone()
                assert before['remaining']>4
                until=monotonic()+2
                while True:
                    await connection.execute('SELECT pg_stat_clear_snapshot()')
                    pending=await (await connection.execute('SELECT pid,state,wait_event_type,wait_event,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE pid=%s',(owner['keeper_pid'],))).fetchone()
                    if pending and pending['wait_event_type']=='Lock':break
                    assert monotonic()<until,{'pending':pending,'log':log.read_text()}
                    await asyncio.sleep(.01)
                advisory=await (await connection.execute("SELECT count(*) AS n FROM pg_locks WHERE pid=%s AND locktype='advisory' AND granted",(owner['keeper_pid'],))).fetchone()
                assert advisory['n']>0
                started=monotonic()
                await asyncio.sleep(delay)
                after=await (await connection.execute('SELECT epoch,healthy_until>clock_timestamp() AS healthy FROM coordinator_lease')).fetchone()
                proof={'scope':'real PostgreSQL delay and native physical lifetime; seeded component environment',
                    'delay_seconds':delay,'actual_elapsed_seconds':monotonic()-started,'owner':owner,
                    'initial_lease':before,'observed_pending_query':pending,'granted_advisory_locks':advisory['n'],
                    'after_lease':after,'native_child_alive':Path(f'/proc/{native_pid}').exists(),
                    'supervisor_poll':process.poll()}
                (tmp_path/'actual-ownership-delay.json').write_text(json.dumps(proof,default=str,indent=2)+'\n')
                print(json.dumps(proof,default=str),flush=True)
                assert after['epoch']==before['epoch']
                if delay<4:
                    assert after['healthy'] and Path(f'/proc/{native_pid}').exists(),log.read_text()
                else:
                    assert not after['healthy'] and not Path(f'/proc/{native_pid}').exists(),log.read_text()
            if delay<4:
                until=monotonic()+5
                while True:
                    renewed=await (await connection.execute('SELECT epoch,extract(epoch FROM healthy_until-clock_timestamp()) AS remaining FROM coordinator_lease')).fetchone()
                    if renewed['remaining']>4.5:break
                    assert monotonic()<until and process.poll() is None,log.read_text()
                    await asyncio.sleep(.02)
                assert renewed['epoch']==before['epoch'] and Path(f'/proc/{native_pid}').exists()
                # Actual ownership loss still reaps the same child, without retry.
                assert (await (await connection.execute('SELECT pg_terminate_backend(%s) AS terminated',(owner['keeper_pid'],))).fetchone())['terminated']
            assert await asyncio.to_thread(process.wait,15)!=0
            assert not Path(f'/proc/{native_pid}').exists()
            assert sum(line.startswith('{"event": "native_spawn"') for line in log.read_text().splitlines())==1
        finally:
            if process.poll() is None:
                process.terminate()
                await asyncio.to_thread(process.wait,20)
            if native_pid is not None:assert not Path(f'/proc/{native_pid}').exists()
