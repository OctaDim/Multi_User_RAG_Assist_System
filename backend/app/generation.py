import asyncio
import argparse
from collections import deque
from datetime import timedelta
from contextlib import asynccontextmanager
import ctypes
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from sqlalchemy import DateTime, cast, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from psycopg.conninfo import make_conninfo

from app.configuration import load_settings
from app.models import Account, Conversation, CoordinatorLease, Document, GraphBinding, Message, Request, RequestSource, ServiceState, Setting

from app import answers, settings, sources
from app.auth import AccessError, lock_service, originating_session
from app.db import Database, database_url, migrate


logger = logging.getLogger(__name__)


def trace(kind, **fields):
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug('%s', json.dumps({'event': kind, **fields}))


class Coordinator:
    """One process owns the queue and physical contexts for every API process."""

    def __init__(self, database, epoch, runtime, embedder):
        self.database, self.epoch = database, epoch
        self.runtime, self.embedder = runtime, embedder
        self.prepared, self.active, self.closing = {}, {}, {}
        self.ready, self.runnable = deque(), deque()
        self.values = None
        self.revision, self.step_number = 0, 0

    @asynccontextmanager
    async def guard(self, request_id, *, finalizing=False):
        async with self.database.session() as connection, connection.begin():
            service = await lock_service(connection)
            if service['epoch'] != self.epoch or not service['healthy']:
                raise AccessError('lost_execution', 409)
            row = (await connection.execute(select(Request.execution_epoch, Request.owner_id, Request.conversation_id).where(Request.id == request_id))).mappings().first()
            if not row or row['execution_epoch'] != self.epoch:
                raise AccessError('lost_execution', 409)
            actor = (await connection.execute(select(Account.__table__).where(Account.id == row["owner_id"]).with_for_update(read=True))).mappings().first()
            if not finalizing:
                actor = await originating_session(connection, request_id)
            documents = (await connection.execute(select(Document.__table__).where(Document.id.in_(sources.scoped_document_ids(request_id))).order_by(Document.id).with_for_update(read=True))).mappings().all()
            if not finalizing:
                from app.events import origin
                await origin(connection, request_id)
            # Events also update dialog dates; take the write lock before locking its request.
            conversation = (await connection.execute(select(Conversation.__table__).where(Conversation.id == row["conversation_id"]).with_for_update())).mappings().first()
            request = (await connection.execute(select(Request.__table__).where(Request.id == request_id).with_for_update())).mappings().first()
            binding = (await connection.execute(select(GraphBinding.__table__).where(GraphBinding.request_id == request_id))).mappings().first()
            if request['state'] not in answers.UNFINISHED:
                raise AccessError('terminal_request', 409)
            if not finalizing:
                if actor['context_epoch'] != binding['account_epoch']:
                    raise AccessError('access_denied')
                if conversation['owner_id'] != actor['id'] or any(value['owner_id'] != actor['id'] for value in documents):
                    raise AccessError('not_found', 404)
                if (await connection.execute(select(RequestSource.request_id).join(Document, Document.id == RequestSource.document_id).where(RequestSource.request_id == request_id, Document.deleted).limit(1))).mappings().first():
                    raise AccessError('source_deleted', 409)
            # OCR changes close old saver writes, while the agreed current answer continues.
            yield connection, dict(request)

    async def refresh(self):
        async with self.database.session() as connection, connection.begin():
            service = await lock_service(connection)
            if service['epoch'] != self.epoch or not service['healthy']:
                raise AccessError('lost_execution', 409)
            current = await settings.current(connection)
            self.values = current['values']
            self.revision = current['revision']
            if current['applied_revision'] != current['revision']:
                await connection.execute(update(Setting.__table__).where(Setting.id == 1).values(applied_revision=current["revision"]))

    async def finish(self, request_id, state, reason):
        try:
            async with self.guard(request_id, finalizing=True) as (connection, request):
                await answers.transition(connection, request, state, reason)
        except AccessError as error:
            if error.code not in ('terminal_request', 'lost_execution'):
                raise

    def release(self, request_id):
        if request_id in self.closing or self.active.get(request_id) is None:
            return
        context = self.active[request_id]
        context.cancel()
        self.closing[request_id] = asyncio.create_task(asyncio.to_thread(context.close))
        if request_id in self.runnable:
            self.runnable.remove(request_id)

    async def reap(self):
        for request_id, task in list(self.closing.items()):
            if task.done():
                task.result()
                self.active.pop(request_id)
                self.closing.pop(request_id)
                trace('native_release', request=str(request_id), epoch=self.epoch, physical_active=len(self.active))

    async def cancel_invalid(self):
        for request_id in list(self.active):
            if request_id in self.closing:
                continue
            try:
                async with self.guard(request_id):
                    pass
            except AccessError as error:
                if error.code not in ('terminal_request', 'lost_execution'):
                    await self.finish(request_id, 'interrupted', error.code)
                self.release(request_id)

    async def prepare_next(self):
        from app.rag import run_graph

        async with self.database.session() as connection, connection.begin():
            row = (await connection.execute(select(Request.id).where(Request.state == "accepted", Request.execution_epoch == self.epoch).order_by(Request.created_at, Request.id).limit(1))).mappings().first()
        if not row:
            return
        request_id = row['id']
        try:
            async with self.guard(request_id) as (connection, _):
                updated = (await connection.execute(update(Request.__table__).where(Request.id == request_id, Request.state == "accepted").values(state="searching", version=Request.version + 1).returning(Request.__table__))).mappings().first()
                await answers.event(connection, updated, 'state', {'state': 'searching', 'version': updated['version']})
            state = await run_graph(self.database, request_id, self.epoch, self.embedder, self.runtime.tokenize)
            self.prepared[request_id] = state
            self.ready.append(request_id)
        except AccessError as error:
            await self.finish(request_id, 'interrupted', error.code)
        except Exception:
            await self.finish(request_id, 'failed', 'search_error')

    async def admit_ready(self):
        await self.refresh()
        await self.reap()
        while self.ready:
            request_id = self.ready[0]
            try:
                async with self.guard(request_id) as (connection, request):
                    current = await settings.current(connection)
                    self.values = current['values']
                    self.revision = current['revision']
                    if len(self.active) >= self.values['max_active']:
                        break
                    if current['applied_revision'] != current['revision']:
                        await connection.execute(update(Setting.__table__).where(Setting.id == 1).values(applied_revision=current["revision"]))
                    self.ready.popleft()
                    state = self.prepared.pop(request_id)
                    if request['state'] != 'queued':
                        continue
                    # The reservation exists before the allocation handoff; stop shares this lock.
                    self.active[request_id] = None
                    allocation = asyncio.create_task(asyncio.to_thread(self.runtime.allocate, request_id, state['tokens']))
                    updated = (await connection.execute(update(Request.__table__).where(Request.id == request_id).values(state="generating", version=Request.version + 1).returning(Request.__table__))).mappings().first()
                    await answers.event(connection, updated, 'state', {'state': 'generating', 'version': updated['version']})
                self.active[request_id] = await allocation
                self.runnable.append(request_id)
                trace('native_allocate', request=str(request_id), epoch=self.epoch, revision=self.revision,
                      context=int(getattr(self.active[request_id], 'context', 0) or 0),
                      prompt_tokens=len(state['tokens']), physical_active=len(self.active),
                      max_active=self.values['max_active'])
            except AccessError as error:
                if self.ready and self.ready[0] == request_id:
                    self.ready.popleft()
                    self.prepared.pop(request_id)
                if request_id in self.active:
                    self.active[request_id] = await allocation
                    self.release(request_id)
                await self.finish(request_id, 'interrupted', error.code)
            except Exception:
                if request_id in self.active and self.active[request_id] is None:
                    try:
                        self.active[request_id] = await allocation
                    except Exception:
                        self.active.pop(request_id)
                self.release(request_id)
                await self.finish(request_id, 'failed', 'generation_error')

    async def step(self):
        await self.cancel_invalid()
        await self.refresh()
        group = [self.runnable.popleft() for _ in range(min(self.values['step_width'], len(self.runnable)))]
        promoted = []
        for request_id in group:
            if request_id in self.closing:
                continue
            try:
                async with self.guard(request_id):
                    computation = asyncio.create_task(asyncio.to_thread(self.active[request_id].advance))
                result = await computation
                promoted.append({'request': str(request_id), 'phase': result['phase'],
                                 'token': result.get('token'), 'position': result.get('position')})
                async with self.guard(request_id) as (connection, request):
                    if result['text']:
                        request = (await connection.execute(update(Request.__table__).where(Request.id == request_id).values(answer_text=Request.answer_text + result["text"], version=Request.version + 1).returning(Request.__table__))).mappings().first()
                        flags = await sources.source_flags(connection, request_id)
                        await connection.execute(insert(Message.__table__).values(request_id=request_id, conversation_id=request["conversation_id"], role="assistant", text=request["answer_text"], excluded=bool(flags), source_flags=flags).on_conflict_do_update(index_elements=[Message.request_id, Message.role], set_={"text": request["answer_text"], "excluded": bool(flags), "source_flags": flags}))
                        await answers.event(connection, request, 'output', {'text': result['text'], 'version': request['version'],
                                                                           'citations': sources.cited_spans(request['answer_text'], request['passport']),
                                                                           'source_flags': flags, 'excluded': bool(flags)})
                    if result['done']:
                        completed = result['reason'] == 'eos'
                        await answers.transition(connection, request, 'completed' if completed else 'interrupted',
                                                 None if completed else result['reason'])
                        self.release(request_id)
                    else:
                        self.runnable.append(request_id)
            except AccessError as error:
                await self.finish(request_id, 'interrupted', error.code)
                self.release(request_id)
            except Exception:
                await self.finish(request_id, 'failed', 'generation_error')
                self.release(request_id)
        trace('native_step', epoch=self.epoch, step=self.step_number, revision=self.revision,
              step_width=self.values['step_width'], promoted=promoted)
        self.step_number += 1

    async def tick(self):
        await self.cancel_invalid()
        await self.reap()
        await self.prepare_next()
        await self.admit_ready()
        await self.step()

    async def run(self):
        async def watch():
            while True:
                await self.cancel_invalid()
                await asyncio.sleep(load_settings('policy')['generation']['cancellation_poll_seconds'])

        watcher = asyncio.create_task(watch())
        try:
            while True:
                if watcher.done():
                    watcher.result()
                await self.tick()
                await asyncio.sleep(load_settings('policy')['generation']['active_poll_seconds' if self.active or self.ready else 'idle_poll_seconds'])
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            await self.close()

    async def close(self):
        for request_id in list(self.active):
            self.release(request_id)
        if self.closing:
            await asyncio.gather(*self.closing.values())
            await self.reap()


def process_start(pid):
    try:
        # /proc command names can contain spaces and closing parentheses.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except FileNotFoundError:
        return None


class Supervisor:
    """A DB epoch fences writes; an inherited host lock separately fences native memory."""

    def __init__(self, dsn):
        self.dsn = dsn
        self.child = None
        self.fence = self.epoch = None
        self.stopping = asyncio.Event()

    def acquire_fence(self, runtime_id):
        directory = Path(tempfile.gettempdir()) / f'rag-generation-{os.getuid()}'
        directory.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(directory / f'{runtime_id}.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = os.read(descriptor, 4096)
            if previous:
                record = json.loads(previous)
                if record.get('pid') and process_start(record['pid']) == record['start']:
                    raise RuntimeError('Predecessor reap is unconfirmed; replacement blocked')
        except BaseException:
            os.close(descriptor)
            raise
        self.fence = descriptor

    def record_child(self):
        record = {'pid': self.child.pid, 'start': process_start(self.child.pid)} if self.child else {}
        os.lseek(self.fence, 0, os.SEEK_SET)
        os.ftruncate(self.fence, 0)
        os.write(self.fence, json.dumps(record).encode())
        os.fsync(self.fence)

    async def reap_child(self):
        if self.child:
            if self.child.poll() is None:
                self.child.terminate()
            try:
                await asyncio.to_thread(self.child.wait, load_settings('policy')['generation']['reap_timeout_seconds'])
            except subprocess.TimeoutExpired:
                self.child.kill()
                await asyncio.to_thread(self.child.wait, load_settings('policy')['generation']['reap_timeout_seconds'])
            self.child = None
            self.record_child()

    async def run(self):
        dsn = make_conninfo(self.dsn, connect_timeout=load_settings('policy')['generation']['connect_timeout_seconds'])
        await migrate(dsn)
        database = Database(dsn)
        try:
            async with database.connection() as connection:
                await self.own(connection)
        finally:
            await database.dispose()

    async def own(self, connection):
        ready_read = start_write = None
        heartbeat = None
        try:
            locked = (await connection.execute(select(func.pg_try_advisory_lock(func.hashtextextended("rag:generation", 0)).label("locked")))).mappings().first()
            await connection.commit()
            if not locked['locked']:
                raise RuntimeError('Generation supervisor already owns this service')
            async with connection.begin():
                service = await lock_service(connection, exclusive=True)
                service.update((await connection.execute(select(ServiceState.runtime_id, ServiceState.physical_host).where(ServiceState.id == 1))).mappings().first())
                machine = Path('/etc/machine-id').read_text().strip()
                host = f'{machine}:{os.getuid()}:{os.readlink("/proc/self/ns/mnt")}'
                if not machine or service['physical_host'] not in (None, host):
                    raise RuntimeError('Automatic generation failover to another host is disabled')
                self.acquire_fence(service['runtime_id'])
                self.epoch = service['epoch'] + 1
                await connection.execute(update(ServiceState.__table__).where(ServiceState.id == 1).values(epoch=self.epoch, physical_host=host))
                await connection.execute(update(CoordinatorLease.__table__).where(CoordinatorLease.id == 1).values(epoch=self.epoch, healthy_until=cast(literal("-infinity"), DateTime(timezone=True))))
                # The predecessor is already reaped; nothing resumes its checkpoints or queue.
                lost = (await connection.execute(select(Request.__table__).where(Request.state.in_(answers.UNFINISHED)).order_by(Request.id).with_for_update())).mappings().all()
                for request in lost:
                    await answers.transition(connection, request, 'interrupted', 'execution_lost')
            keeper = ((await connection.execute(select(func.pg_backend_pid().label("pid")))).mappings().first())['pid']
            await connection.commit()
            ready_read, ready_write = os.pipe()
            start_read, start_write = os.pipe()
            try:
                self.child = subprocess.Popen(
                    [sys.executable, '-m', 'app.generation', '--worker', '--epoch', str(self.epoch),
                     '--parent', str(os.getpid()), '--lock-fd', str(self.fence),
                     '--ready-fd', str(ready_write), '--start-fd', str(start_read)],
                    pass_fds=(self.fence, ready_write, start_read),
                )
                self.record_child()
                print(json.dumps({'event': 'native_spawn', 'pid': self.child.pid, 'keeper_pid': keeper, 'epoch': self.epoch}), flush=True)
                os.write(start_write, b'1')
            finally:
                os.close(ready_write)
                os.close(start_read)
            os.close(start_write)
            start_write = None
            os.set_blocking(ready_read, False)
            ready = False
            loop = asyncio.get_running_loop()
            lease_seconds = load_settings('policy')['generation']['lease_seconds']
            ownership_deadline = loop.time() + lease_seconds

            async def renew(ready):
                async with connection.begin():
                    if ready:
                        await connection.execute(
                            update(CoordinatorLease.__table__).where(
                                CoordinatorLease.id == 1, CoordinatorLease.epoch == self.epoch,
                            ).values(healthy_until=func.clock_timestamp() + timedelta(seconds=lease_seconds))
                        )
                    else:
                        await connection.execute(select(literal(1)))

            while not self.stopping.is_set():
                if self.child.poll() is not None:
                    raise RuntimeError('Native coordinator exited; service requires recovery')
                if not ready:
                    try:
                        ready = os.read(ready_read, 1) == b'1'
                    except BlockingIOError:
                        pass
                renewal_started = loop.time()
                heartbeat = asyncio.create_task(renew(ready))
                # A delayed query is bounded by the confirmed lease, not a
                # shorter unrelated watchdog. Start time conservatively bounds
                # the earliest possible server renewal, including WAL waits.
                done, _ = await asyncio.wait({heartbeat}, timeout=max(0,ownership_deadline-renewal_started))
                if not done:
                    raise RuntimeError('Coordinator ownership connection stalled')
                heartbeat.result()
                ownership_deadline = renewal_started + lease_seconds
                await asyncio.sleep(load_settings('policy')['generation']['renewal_poll_seconds'])
        finally:
            # Reap first, even when DB cleanup or a cancelled query cannot complete.
            await self.reap_child()
            if heartbeat and not heartbeat.done():
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            try:
                if not connection.invalidated:
                    await connection.rollback()
                    async with connection.begin():
                        if self.epoch is not None:
                            await connection.execute(
                                update(CoordinatorLease.__table__).where(
                                    CoordinatorLease.id == 1, CoordinatorLease.epoch == self.epoch,
                                ).values(healthy_until=cast(literal('-infinity'), DateTime(timezone=True)))
                            )
                        await connection.execute(select(func.pg_advisory_unlock(func.hashtextextended('rag:generation', 0))))
            except Exception:
                await connection.invalidate()
            if ready_read is not None:
                os.close(ready_read)
            if start_write is not None:
                os.close(start_write)
            if self.fence is not None:
                os.close(self.fence)
                self.fence = None


async def worker(args):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != args.parent:
        raise RuntimeError('Native worker lost its supervisor')
    os.fstat(args.lock_fd)
    if os.read(args.start_fd, 1) != b'1':
        raise RuntimeError('Supervisor did not authorize native loading')
    os.close(args.start_fd)
    from app.llama_runtime import LlamaRuntime
    from app.rag import E5Embedder

    dsn = database_url()
    await migrate(dsn)
    database = Database(dsn)
    try:
        async with database.session() as connection, connection.begin():
            config = await settings.current(connection)
        runtime = LlamaRuntime(os.environ['RAG_MODEL_PATH'], config['values'])
        try:
            embedder = E5Embedder(os.environ['RAG_E5_DIR'])
            os.write(args.ready_fd, b'1')
            os.close(args.ready_fd)
            while True:
                async with database.session() as connection, connection.begin():
                    service = await lock_service(connection)
                if service['epoch'] != args.epoch:
                    raise RuntimeError('Native worker lost its execution epoch')
                if service['healthy']:
                    break
                await asyncio.sleep(load_settings('policy')['generation']['ready_poll_seconds'])
            await Coordinator(database, args.epoch, runtime, embedder).run()
        finally:
            runtime.close()
    finally:
        await database.dispose()


def main():
    parser = argparse.ArgumentParser(description='Own one shared generation coordinator on this host')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    for name in ('epoch', 'parent', 'lock-fd', 'ready-fd', 'start-fd'):
        parser.add_argument('--' + name, type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    async def start():
        if args.worker:
            if any(getattr(args, key) is None for key in ('epoch', 'parent', 'lock_fd', 'ready_fd', 'start_fd')):
                raise RuntimeError('Native worker requires its supervising process')
            await worker(args)
        else:
            supervisor = Supervisor(database_url())
            loop = asyncio.get_running_loop()
            for event in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(event, supervisor.stopping.set)
            await supervisor.run()

    asyncio.run(start())


if __name__ == '__main__':
    main()
