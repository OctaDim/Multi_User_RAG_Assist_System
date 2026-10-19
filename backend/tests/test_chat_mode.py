"""Document-free answers use the same admission, guards and native queue."""
from uuid import uuid4

import pytest

from app import answers
from app.auth import AccessError
from app.rag import run_graph
from test_rag_context import complete, contract_tokenize


class NoRetrieval:
    def encode(self, *args, **kwargs):
        raise AssertionError('Document-free chat must not run retrieval')


async def submit(session, environment, *, key=None, scope=(), question='Remember my favorite color: azure.'):
    return await answers.admit(session, environment['user']['token'], environment['conversation'],
                               key or uuid4(), question, list(scope), environment['tab'], environment['proof'])


async def test_empty_library_admits_chat_and_replay_keeps_its_mode(session, environment, connection, rag_pool):
    await connection.execute('UPDATE documents SET ready=false')
    key=uuid4()
    request=await submit(session, environment, key=key)
    assert request['scope']==[] and request['passport']['scope_mode']=='chat'
    await connection.execute('UPDATE documents SET ready=true')
    replay=await submit(session, environment, key=key)
    assert replay['id']==request['id'] and replay['scope']==[]
    state=await run_graph(rag_pool,request['id'],request['execution_epoch'],NoRetrieval(),contract_tokenize)
    assert state['passport']['scope_mode']=='chat'
    assert state['passport']['passed']==state['passport']['available']==[]
    assert 'Use only the permitted source excerpts' not in state['prompt']
    assert 'azure' in state['prompt'] and 'general knowledge' in state['prompt']


async def test_explicit_unavailable_selection_does_not_become_chat(session, environment, connection):
    await connection.execute('UPDATE documents SET ready=false')
    with pytest.raises(AccessError,match='no_ready_sources'):
        await submit(session,environment,scope=[environment['document']])


async def test_chat_history_is_kept_and_does_not_become_rag_evidence(session, environment, connection, rag_pool):
    await connection.execute('UPDATE documents SET ready=false')
    first=await submit(session,environment)
    await run_graph(rag_pool,first['id'],first['execution_epoch'],NoRetrieval(),contract_tokenize)
    await complete(session,first,'Your favorite color is azure.')
    second=await submit(session,environment,question='What is my favorite color?')
    state=await run_graph(rag_pool,second['id'],second['execution_epoch'],NoRetrieval(),contract_tokenize)
    assert [row['request_id'] for row in state['history']]==[str(first['id'])]
    assert 'Your favorite color is azure.' in state['prompt']
    await complete(session,second,'Azure.')
    await connection.execute('UPDATE documents SET ready=true')
    third=await submit(session,environment,question='What is the annual budget?')
    from test_rag_context import ContractEmbedder
    state=await run_graph(rag_pool,third['id'],third['execution_epoch'],ContractEmbedder(),contract_tokenize)
    assert state['passport']['scope_mode']=='all'
    assert state['history']==[] and 'favorite color' not in state['prompt']


async def test_first_send_conversation_creation_is_idempotent_and_owner_checked(session, environment):
    identifier=uuid4()
    first=await answers.create_conversation(session,environment['user']['token'],identifier)
    repeated=await answers.create_conversation(session,environment['user']['token'],identifier)
    assert first['id']==repeated['id']==identifier
    with pytest.raises(AccessError,match='not_found'):
        await answers.create_conversation(session,environment['admin']['token'],identifier)
