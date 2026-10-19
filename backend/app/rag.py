import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert
from psycopg.pq import TransactionStatus

from app.models import Conversation, Document, GraphBinding, Message, Request, RequestSource

from app import settings, sources
from app.auth import AccessError, lock_service, principal, originating_session
from app.answers import UNFINISHED, event
from app.configuration import load_settings


class E5Embedder:
    """One local CPU session per coordinator; embeddings match source_chunks vector(384)."""

    def __init__(self, directory):
        directory = Path(directory)
        self.config = load_settings('runtime')['embedding']
        self.tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=self.config['max_length'])
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = self.config['intra_op_threads']
        self.session = ort.InferenceSession(str(directory / 'model_quantized.onnx'), options, providers=['CPUExecutionProvider'])

    def encode(self, texts, *, query=False):
        prefix = self.config['query_prefix'] if query else self.config['passage_prefix']
        encoded = self.tokenizer.encode_batch([prefix + text for text in texts])
        ids = np.asarray([value.ids for value in encoded], dtype=np.int64)
        mask = np.asarray([value.attention_mask for value in encoded], dtype=np.int64)
        inputs = {'input_ids': ids, 'attention_mask': mask, 'token_type_ids': np.zeros_like(ids)}
        outputs = self.session.run(None, {value.name: inputs[value.name] for value in self.session.get_inputs()})[0]
        pooled = (outputs * mask[..., None]).sum(1) / mask.sum(1)[..., None]
        pooled /= np.linalg.norm(pooled, axis=1, keepdims=True)
        return pooled.astype(np.float32).tolist()


class GuardedSaver(BaseCheckpointSaver):
    """The sole runtime saver boundary, bound to one admitted request and epochs."""

    def __init__(self, database, binding, *, token=None):
        super().__init__()
        self.database = database
        self.binding = binding
        self.token = token

    @asynccontextmanager
    async def guard(self, config=None, *, preparing=False):
        async with self.database.session() as connection, connection.begin():
            service = await lock_service(connection)
            if self.token:
                actor = await principal(connection, self.token)
                if actor['id'] != self.binding['owner_id']:
                    raise AccessError('not_found', 404)
            origin_actor = await originating_session(connection, self.binding['request_id'])
            if self.token and actor['id'] != origin_actor['id']:
                raise AccessError('not_found', 404)
            actor = origin_actor
            documents = (await connection.execute(select(Document.__table__).where(Document.id.in_(sources.scoped_document_ids(self.binding["request_id"]))).order_by(Document.id).with_for_update(read=True))).mappings().all()
            from app.events import origin
            await origin(connection, self.binding['request_id'])
            conversation = (await connection.execute(select(Conversation.__table__).where(Conversation.id == self.binding["conversation_id"]).with_for_update(read=True))).mappings().first()
            request = (await connection.execute(select(Request.__table__).where(Request.id == self.binding["request_id"]).with_for_update())).mappings().first()
            stored = (await connection.execute(select(GraphBinding.__table__).where(GraphBinding.request_id == self.binding["request_id"]).with_for_update(read=True))).mappings().first()
            if not request or not stored or not conversation or any(stored[key] != self.binding[key] for key in
                ('thread_id', 'owner_id', 'conversation_id', 'execution_epoch', 'context_epoch', 'account_epoch')):
                raise AccessError('stale_context', 409)
            if config and config.get('configurable', {}).get('thread_id') != stored['thread_id']:
                raise AccessError('invalid_graph_identity', 403)
            if (request['owner_id'] != actor['id'] or request['conversation_id'] != stored['conversation_id']
                or conversation['owner_id'] != actor['id']
                or any(document['owner_id'] != actor['id'] for document in documents)):
                raise AccessError('not_found', 404)
            if request['state'] not in UNFINISHED:
                raise AccessError('terminal_request', 409)
            if not service['healthy'] or service['epoch'] != stored['execution_epoch'] or request['execution_epoch'] != stored['execution_epoch']:
                raise AccessError('lost_execution', 409)
            if (actor['context_epoch'] != stored['account_epoch'] or request['context_epoch'] != stored['context_epoch']
                or (not preparing and conversation['context_epoch'] != stored['context_epoch'])):
                raise AccessError('stale_context', 409)
            if not preparing:
                invalid = (await connection.execute(select(RequestSource.request_id).outerjoin(sources.available_revisions, and_(sources.available_revisions.c.document_id == RequestSource.document_id, sources.available_revisions.c.revision_id == RequestSource.revision_id, sources.available_revisions.c.owner_id == actor["id"])).where(RequestSource.request_id == request["id"], sources.available_revisions.c.revision_id.is_(None)).limit(1))).mappings().first()
                if invalid:
                    raise AccessError('stale_source', 409)
            if preparing and (await connection.execute(select(RequestSource.request_id).join(Document, Document.id == RequestSource.document_id).where(RequestSource.request_id == request["id"], Document.deleted).limit(1))).mappings().first():
                raise AccessError('source_deleted',409)
            yield connection, dict(request)

    @asynccontextmanager
    async def saver(self, config):
        async with self.guard(config) as (session, _):
            connection = await session.connection()
            driver = (await connection.get_raw_connection()).driver_connection
            try:
                yield AsyncPostgresSaver(driver, serde=self.serde)
            except BaseException:
                # Driver IO bypasses SQLAlchemy's disconnect classification.
                if driver.closed or driver.broken or driver.info.transaction_status == TransactionStatus.UNKNOWN:
                    try:
                        await connection.invalidate()
                    except BaseException:
                        pass  # Preserve the original driver error or cancellation.
                raise

    async def aget_tuple(self, config):
        async with self.saver(config) as saver:
            return await saver.aget_tuple(config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        if config is None:
            raise AccessError('invalid_graph_identity')
        async with self.saver(config) as saver:
            values = [value async for value in saver.alist(config, filter=filter, before=before, limit=limit)]
        for value in values:
            # Each handoff rechecks access, including delayed iteration consumers.
            async with self.guard(config):
                yield value

    async def aput(self, config, checkpoint, metadata, new_versions):
        async with self.saver(config) as saver:
            return await saver.aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=''):
        async with self.saver(config) as saver:
            await saver.aput_writes(config, writes, task_id, task_path)

    def get_next_version(self, current, channel):
        return AsyncPostgresSaver.get_next_version(self, current, channel)


def fragment_payload(fragment):
    return {key: str(fragment[key]) if key in ('id', 'document_id', 'revision_id') else fragment[key]
            for key in ('id', 'document_id', 'revision_id', 'page', 'text', 'span_start', 'span_end', 'coordinates', 'kind', 'mode', 'limitations', 'similarity', 'name')}


def pack_context(question, history, fragments, tokenize, *, n_ctx=None, response_reserve=None, chat=False):
    config = load_settings('runtime')
    n_ctx = config['generation']['n_ctx'] if n_ctx is None else n_ctx
    response_reserve = config['rag']['response_reserve'] if response_reserve is None else response_reserve
    prompts = load_settings('prompts')['chat' if chat else 'rag']
    kept_history, kept_fragments = list(history), list(fragments)

    def prompt():
        prior = ''
        for value in kept_history:
            answer = re.sub(r'\[source:([1-9][0-9]?)\]', r'[past-source:\1]', value['answer'])
            prior += f"<turn>\nUser: {value['question']}\nAssistant: {answer}\n</turn>\n"
        excerpts = ''.join(f"<source id=\"{number}\" trace_id=\"{value['id']}\" citation=\"[source:{number}]\" page=\"{value['page']}\" start=\"{value['span_start']}\" end=\"{value['span_end']}\">\n{value['text']}\n</source>\n" for number,value in enumerate(kept_fragments,1))
        markers = ', '.join(f'[source:{number}]' for number in range(1, len(kept_fragments)+1))
        return prompts['template'].format(system=prompts['system'], prior=prior, excerpts=excerpts,
                                          question=question, markers=markers)

    while True:
        text = prompt()
        tokens = list(tokenize(text))
        if len(tokens) + response_reserve <= n_ctx:
            return {'prompt': text, 'tokens': tokens, 'response_tokens': n_ctx-len(tokens),
                    'history': kept_history, 'fragments': kept_fragments}
        if kept_history:
            kept_history.pop(0)
        elif kept_fragments:
            kept_fragments.pop()
        else:
            raise AccessError('context_too_large', 422)


async def prepare(saver, embedder, tokenize, *, min_similarity=None):
    async with saver.guard(preparing=True) as (connection, request):
        question = ((await connection.execute(select(Message.text).where(Message.request_id == request["id"], Message.role == "user"))).mappings().first())['text']
        generation = (await settings.current(connection))['values']
        chat = request['passport'].get('scope_mode') == 'chat'
    embedding = None if chat else (await asyncio.to_thread(embedder.encode, [question], query=True))[0]
    async with saver.guard(preparing=True) as (connection, request):
        available = await sources.available(connection, request['owner_id'], request['scope'])
        if not available and not chat:
            raise AccessError('no_ready_sources', 409)
        found = [] if chat else await sources.retrieve(connection, request['owner_id'], request['scope'], embedding, min_similarity=min_similarity)
        previous = await sources.history(connection, request)
        packed = pack_context(question, previous, found, tokenize, n_ctx=generation['n_ctx'], chat=chat)
        dependencies = {(str(value['document_id']), str(value['revision_id'])) for value in found}
        history_dependencies = {(item['document_id'], item['revision_id'])
                                for value in packed['history'] for item in value['dependencies']}
        dependencies.update(history_dependencies)
        passport = {
            'scope_mode': request['passport'].get('scope_mode', 'selected'),
            'selected_document_ids': request['passport'].get('selected_document_ids', list(map(str, request['scope']))),
            'selected': list(map(str, request['scope'])),
            'available': [{key: str(row[key]) if key in ('document_id', 'revision_id') else row[key]
                           for key in ('document_id', 'revision_id', 'mode', 'limitations', 'name')} for row in available],
            'excluded': [str(value) for value in request['scope'] if value not in {row['document_id'] for row in available}],
            'found': [fragment_payload(value) for value in found],
            'passed': [fragment_payload(value) for value in packed['fragments']],
            'insufficient_evidence': not chat and not bool(packed['fragments']),
            'history_requests': [str(value['request_id']) for value in packed['history']],
            'history_dependencies': [{'document_id': doc, 'revision_id': rev} for doc, rev in sorted(history_dependencies)],
        }
        current = {(str(row['document_id']), str(row['revision_id'])) for row in await sources.available(connection, request['owner_id'], request['scope'])}
        if not dependencies.issubset(current):
            raise AccessError('stale_source', 409)
        for document_id, revision_id in sorted(dependencies):
            await connection.execute(insert(RequestSource.__table__).values(request_id=request["id"], document_id=document_id, revision_id=revision_id).on_conflict_do_nothing())
        request = (await connection.execute(update(Request.__table__).where(Request.id == request["id"]).values(state="queued", passport=passport, version=Request.version + 1).returning(Request.__table__))).mappings().first()
        await event(connection, request, 'fragments', {'passport': passport, 'version': request['version']})
    return {**packed, 'history': [{**row, 'request_id': str(row['request_id'])} for row in packed['history']],
            'fragments': passport['passed'], 'passport': passport,
            'dependencies': [{'document_id': doc, 'revision_id': rev} for doc, rev in sorted(dependencies)]}


class RAGState(TypedDict, total=False):
    request_id: str
    prompt: str
    tokens: list[int]
    response_tokens: int
    history: list[dict]
    fragments: list[dict]
    passport: dict
    dependencies: list[dict]
    answer: str


async def run_graph(database, request_id, execution_epoch, embedder, tokenize, *, token=None, generate=None, min_similarity=None):
    async with database.session() as connection, connection.begin():
        binding = (await connection.execute(select(GraphBinding.__table__).where(GraphBinding.request_id == request_id))).mappings().first()
    if not binding or binding['execution_epoch'] != execution_epoch:
        raise AccessError('lost_execution', 409)
    saver = GuardedSaver(database, binding, token=token)
    async with saver.guard(preparing=True) as (connection, _):
        if not (await connection.execute(update(GraphBinding.__table__).where(GraphBinding.request_id == request_id, ~GraphBinding.started).values(started=True).returning(GraphBinding.request_id))).mappings().first():
            raise AccessError('graph_already_started', 409)
    prepared = await prepare(saver, embedder, tokenize, min_similarity=min_similarity)

    async def retrieve_node(state):
        return prepared

    graph = StateGraph(RAGState)
    graph.add_node('prepare', retrieve_node)
    graph.add_edge(START, 'prepare')
    if generate is not None:
        async def generate_node(state):
            async with saver.guard():
                pass
            return {'answer': await generate(state)}
        graph.add_node('generate', generate_node)
        graph.add_edge('prepare', 'generate')
        graph.add_edge('generate', END)
    else:
        graph.add_edge('prepare', END)
    compiled = graph.compile(checkpointer=saver)
    try:
        return await compiled.ainvoke({'request_id': str(request_id)}, {'configurable': {'thread_id': binding['thread_id']}})
    except AccessError as error:
        if generate is not None or error.code not in ('stale_context', 'stale_source'):
            raise
        # Preparation already committed its immutable inputs. OCR closes saver
        # writes but must not cancel this one current native generation. Nothing
        # is retried or resumed, and no stale state is written to persistence.
        from app.generation import Coordinator
        async with Coordinator(database, execution_epoch, None, None).guard(request_id) as (connection, _):
            flags = await sources.source_flags(connection, request_id)
            if any(flag != 'corrected' for flag in flags.values()):
                raise
        return {'request_id':str(request_id), **prepared}
