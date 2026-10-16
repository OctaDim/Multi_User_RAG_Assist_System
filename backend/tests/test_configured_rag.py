"""Changed runtime profiles affect actual packing, retrieval and native boundaries."""
import hashlib
import os
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import insert

from app import sources
from app.auth import AccessError
from app.models import Document
from app.rag import E5Embedder, pack_context
from conftest import seed_revision


def select_runtime(tmp_path, monkeypatch, overrides):
    selected = tmp_path / 'service.toml'
    selected.write_text('')
    (tmp_path / 'runtime.local.toml').write_text(overrides)
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(selected))


def test_packing_uses_configured_context_and_response_reserve(tmp_path, monkeypatch):
    select_runtime(tmp_path, monkeypatch, '[generation]\nn_ctx=512\n[rag]\nresponse_reserve=480\n')
    packed = pack_context('Budget?', [], [], lambda text: [1] * 20)
    assert packed['response_tokens'] == 492
    with pytest.raises(AccessError, match='context_too_large'):
        pack_context('Budget?', [], [], lambda text: [1] * 33)


def test_default_prompt_bytes_are_unchanged(tmp_path, monkeypatch):
    select_runtime(tmp_path, monkeypatch, '')
    packed = pack_context('Budget?', [{'question': 'Old?', 'answer': 'Old fact [source:1].'}],
                          [{'id': 'chunk', 'page': 2, 'span_start': 3, 'span_end': 10, 'text': 'Budget.'}],
                          lambda text: [1])
    assert hashlib.sha256(packed['prompt'].encode()).hexdigest() == '51e45ab3c4ea5b22c5cd41ae4b3ca5c67f1a9df945373ec81945c7b4bcdc201b'


async def test_retrieval_obeys_configured_limit_and_similarity(session, connection, environment, tmp_path, monkeypatch):
    select_runtime(tmp_path, monkeypatch, '[rag]\nretrieval_limit=1\nmin_similarity=0.9\n')
    vector = [0.8, 0.6] + [0.0] * 382
    below, relevant = uuid4(), uuid4()
    async with session.begin():
        await session.execute(insert(Document), [{'id': identity, 'owner_id': environment['user']['id'], 'ready': True}
                                                 for identity in (below, relevant)])
    await seed_revision(connection, below, text='Below the configured threshold', embedding=vector)
    await seed_revision(connection, relevant, text='Another equally relevant source')
    scope = [environment['document'], below, relevant]
    async with session.begin():
        # A below-threshold match must be filtered even when the caller widens the result limit.
        rows = await sources.retrieve(session, environment['user']['id'], scope,
                                      [1.0] + [0.0] * 383, limit=10)
        assert {row['text'] for row in rows} == {'The annual budget is 100 euros.', 'Another equally relevant source'}
        rows = await sources.retrieve(session, environment['user']['id'], scope,
                                      [1.0] + [0.0] * 383)
        assert len(rows) == 1


def test_real_embedder_uses_configured_truncation_threads_and_prefixes(tmp_path, monkeypatch):
    select_runtime(tmp_path, monkeypatch,
        '[embedding]\nmax_length=32\nintra_op_threads=2\nquery_prefix="question: "\npassage_prefix="question: "\n')
    embedder = E5Embedder(os.environ['RAG_E5_DIR'])
    text = 'Library annual budget is 100 euros. ' * 50
    encoded = embedder.tokenizer.encode(text)
    assert len(encoded.ids) == 32
    assert embedder.session.get_session_options().intra_op_num_threads == 2
    query = embedder.encode([text], query=True)[0]
    passage = embedder.encode([text])[0]
    assert len(query) == len(passage) == 384
    assert np.isclose(np.linalg.norm(query), 1.0)
    # Equal configured prefixes must make the two execution paths identical.
    assert np.allclose(query, passage)


def test_real_native_prefill_respects_configured_batch(tmp_path, monkeypatch):
    from app.llama_runtime import LlamaRuntime
    from app.settings import defaults
    select_runtime(tmp_path, monkeypatch,
                   '[generation]\nn_ctx=512\n[native]\nprefill_batch=8\ntoken_capacity_padding=1\npiece_capacity=1\n')
    runtime = LlamaRuntime(os.environ['RAG_MODEL_PATH'], defaults())
    try:
        assert runtime.n_ctx == 512
        tokens = runtime.tokenize('Write a clear sentence about the annual library budget. ' * 4)
        assert len(tokens) > 8
        context = runtime.allocate('configured-native-prefill', tokens)
        try:
            assert context.n_ctx == 512
            result = context.advance()
            assert result['phase'] == 'prefill'
            assert context.position == 8
        finally:
            context.close()
    finally:
        runtime.close()


def test_admission_budget_uses_the_selected_generation_context(tmp_path, monkeypatch):
    from app.answers import question_budget
    select_runtime(tmp_path, monkeypatch, '[generation]\nn_ctx=512\n')
    question = 'What is the annual library budget? ' * 250
    with pytest.raises(AccessError, match='context_too_large'):
        question_budget(question)
    # An explicitly selected generation context takes priority over the fallback.
    question_budget(question, {'n_ctx': 4096})
