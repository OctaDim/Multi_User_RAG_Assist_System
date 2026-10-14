"""Real originals/publisher checks; fixture principals here are component-only."""
import pytest
from live_http import LiveClient as TestClient
from app.main import create_app


def test_actual_original_upload_is_not_a_ready_source(environment, monkeypatch, tmp_path):
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    text='Годовой бюджет составляет 100 евро.\n'
    content=text.encode()
    headers={'Authorization':'Bearer '+environment['user']['token']}
    with TestClient(create_app()) as client:
        response=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'budget.txt','size':len(content)}]})
        assert response.status_code == 201
        document=response.json()['documents'][0]
        assert document['state']=='receiving' and not document['ready']
        response=client.put('/api/documents/'+document['id']+'/original',headers=headers|{'Content-Type':'application/octet-stream'},content=content)
        assert response.status_code == 200
        assert response.json()['state']=='queued' and not response.json()['ready']
        assert client.get('/api/documents/'+document['id'],headers=headers).status_code==409


async def test_real_text_publisher_indexes_whole_original(environment, rag_pool, monkeypatch, tmp_path):
    import os
    import hashlib
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    from app import sources
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    content='The annual budget is 100 euros.\n'.encode()
    headers={'Authorization':'Bearer '+environment['user']['token']}
    with TestClient(create_app()) as client:
        response=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'budget.txt','size':len(content)}]})
        assert response.status_code==201
        document=response.json()['documents'][0]
        assert client.put('/api/documents/'+document['id']+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        assert await worker.process_one()
        read=client.get('/api/documents/'+document['id'],headers=headers)
        assert read.status_code==200
        assert read.json()['pages'][0]['text']==content.decode()
        assert client.get('/api/documents/'+document['id']+'/original',headers=headers).content==content
        assert read.json()['document']['original_sha256']==hashlib.sha256(content).hexdigest()
        async with rag_pool.connection() as connection:
            query=worker.embedder.encode(['The annual budget is 100 euros.'],query=True)[0]
            chunks=await sources.retrieve(connection,environment['user']['id'],[document['id']],query)
            assert len(chunks)==1 and chunks[0]['text']==content.decode()


async def test_worker_restart_ends_lost_job_without_requeue(environment, rag_pool, monkeypatch, tmp_path, connection):
    from uuid import uuid4
    from app.document_worker import DocumentWorker
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    with TestClient(create_app()) as client:
        content=b'An original whose worker was lost.'
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'lost.txt','size':len(content)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,None)
        lost=await worker.claim()
        revision=uuid4()
        await connection.execute("INSERT INTO source_revisions(id,document_id,status,upload_complete,page_count,mode) VALUES (%s,%s,'staging',true,1,'complete')",(revision,document))
        await worker.reconcile_lost()
        current=client.get('/api/documents',headers=headers).json()['documents'][0]
        assert current['state']=='failed' and current['error']=='document_worker_lost' and not current['ready']
        assert await worker.claim() is None
        assert (await (await connection.execute('SELECT status FROM source_revisions WHERE id=%s',(revision,))).fetchone())['status']=='failed'
        from app.auth import AccessError
        with pytest.raises(AccessError,match='document_job_ended'):
            async with worker.guard(lost):
                pass
        assert client.get('/api/documents/'+document+'/original',headers=headers).content==content


@pytest.mark.parametrize('mutation',['permission','account'])
async def test_revoked_permission_and_account_access_stop_queued_documents(environment, monkeypatch, tmp_path, connection, mutation):
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    admin={'Authorization':'Bearer '+environment['admin']['token']}
    content=b'An owned queued document.'
    with TestClient(create_app()) as client:
        response=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'one.txt','size':len(content)}]})
        document=response.json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        if mutation=='permission':
            policy_url='/api/documents/policies/'+str(environment['user']['id'])
            original=client.get(policy_url,headers=headers).json()
            policy={'limits':original['limits'],'permissions':original['permissions']|{'txt':False}}
            assert client.patch(policy_url,headers=admin,json=policy).status_code==200
            assert client.patch(policy_url,headers=admin,json={'limits':original['limits'],'permissions':original['permissions']}).status_code==200
        else:
            assert client.patch('/api/accounts/'+str(environment['user']['id']),headers=admin,json={'disabled':True}).status_code==200
        current=await (await connection.execute('SELECT state FROM document_files WHERE document_id=%s',(document,))).fetchone()
        assert current['state']=='failed'


def test_lower_quota_keeps_admitted_upload_and_denies_new_one(environment, monkeypatch, tmp_path):
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    admin={'Authorization':'Bearer '+environment['admin']['token']}
    content=b'The annual budget is 100 euros.'
    with TestClient(create_app()) as client:
        body={'files':[{'name':'budget.txt','size':len(content)}]}
        document=client.post('/api/documents/uploads',headers=headers,json=body).json()['documents'][0]['id']
        policy_url='/api/documents/policies/'+str(environment['user']['id'])
        original=client.get(policy_url,headers=headers).json()
        value={'limits':original['limits']|{'file_bytes':8},'permissions':original['permissions']}
        assert client.patch(policy_url,headers=admin,json=value).status_code==200
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        assert client.post('/api/documents/uploads',headers=headers,json=body).status_code==413


def test_forbidden_handwriting_requires_explicit_choice_and_no_auto_resume(environment, monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    admin={'Authorization':'Bearer '+environment['admin']['token']}
    pdf=Path('harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/mixed-real-title-fixture-v1.pdf').read_bytes()
    with TestClient(create_app()) as client:
        policy_url='/api/documents/policies/'+str(environment['user']['id'])
        original=client.get(policy_url,headers=headers).json()
        assert client.patch(policy_url,headers=admin,json={'limits':original['limits'],'permissions':original['permissions']|{'handwriting':False}}).status_code==200
        body={'files':[{'name':'mixed.pdf','size':len(pdf)}]}
        document=client.post('/api/documents/uploads',headers=headers,json=body).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=pdf).json()['state']=='awaiting_choice'
        assert client.get('/api/documents/'+document,headers=headers).status_code==409
        assert client.patch(policy_url,headers=admin,json={'limits':original['limits'],'permissions':original['permissions']}).status_code==200
        assert client.get('/api/documents',headers=headers).json()['documents'][0]['state']=='awaiting_choice'
        response=client.post('/api/documents/'+document+'/mode',headers=headers,json={'choice':'skip_handwriting'})
        assert response.status_code==200 and response.json()['mode']=='skip_handwriting'


async def test_database_failure_after_atomic_file_link_keeps_original_accounted(environment, monkeypatch, tmp_path, connection):
    import hashlib
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    await connection.execute("""CREATE FUNCTION reject_queue() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.state='queued' THEN RAISE EXCEPTION 'owned queue publication fault'; END IF; RETURN NEW; END $$;
        CREATE TRIGGER owned_queue_failure BEFORE UPDATE ON document_files FOR EACH ROW EXECUTE FUNCTION reject_queue();""")
    content=b'A complete owned original.'
    headers={'Authorization':'Bearer '+environment['user']['token']}
    with TestClient(create_app()) as client:
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'fault.txt','size':len(content)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==500
        row=await (await connection.execute('SELECT state,original_sha256 FROM document_files WHERE document_id=%s',(document,))).fetchone()
        assert row['state']=='failed' and row['original_sha256']==hashlib.sha256(content).hexdigest()
        assert client.get('/api/documents/'+document+'/original',headers=headers).content==content
        assert client.get('/api/documents/'+document,headers=headers).status_code==409


async def test_real_correction_switches_whole_index_and_preserves_original(environment, rag_pool, monkeypatch, tmp_path):
    import os
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    from app import sources
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    content=b'The annual budget is 100 euros.'
    with TestClient(create_app()) as client:
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'budget.txt','size':len(content)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        assert await worker.process_one()
        before=client.get('/api/documents/'+document,headers=headers).json()
        body={'base_revision':before['document']['published_revision'],'pages':[{'page':1,'text':'The annual budget is 10 euros.'}]}
        assert client.post('/api/documents/'+document+'/corrections',headers=headers,json=body).status_code==200
        assert await worker.process_one()
        after=client.get('/api/documents/'+document,headers=headers).json()
        assert after['pages'][0]['text']=='The annual budget is 10 euros.'
        assert after['document']['published_revision']!=before['document']['published_revision']
        assert client.get('/api/documents/'+document+'/original',headers=headers).content==content
        async with rag_pool.connection() as connection:
            vector=worker.embedder.encode(['The annual budget is 10 euros.'],query=True)[0]
            chunks=await sources.retrieve(connection,environment['user']['id'],[document],vector)
            assert len(chunks)==1 and '10 euros' in chunks[0]['text'] and '100 euros' not in chunks[0]['text']
        assert client.post('/api/documents/'+document+'/corrections',headers=headers,json=body).status_code==409


async def test_revocation_after_detection_cannot_start_recognition(environment, rag_pool, monkeypatch, tmp_path):
    import os
    from pathlib import Path
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    from app.ocr import DocumentOCR
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    admin={'Authorization':'Bearer '+environment['admin']['token']}
    pdf=(Path(__file__).resolve().parents[2]/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/mixed-real-title-fixture-v1.pdf').read_bytes()
    calls=[]
    original_detector=DocumentOCR.detect_handwriting
    with TestClient(create_app()) as client:
        policy_url='/api/documents/policies/'+str(environment['user']['id'])
        value=client.get(policy_url,headers=headers).json()
        def detect_then_revoke(ocr,image):
            regions=original_detector(ocr,image)
            response=client.patch(policy_url,headers=admin,json={'limits':value['limits'],'permissions':value['permissions']|{'handwriting':False}})
            assert response.status_code==200
            return regions
        def forbidden_recognition(*args):
            calls.append('recognition_started_after_revocation')
            raise AssertionError('Negative probe blocks forbidden recognition; no successful OCR is mocked')
        monkeypatch.setattr(DocumentOCR,'detect_handwriting',detect_then_revoke)
        monkeypatch.setattr(DocumentOCR,'recognize',forbidden_recognition)
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'mixed.pdf','size':len(pdf)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=pdf).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        try:
            assert await worker.process_one()
            assert calls==[]
            row=next(row for row in client.get('/api/documents',headers=headers).json()['documents'] if row['id']==document)
            assert row['state']=='awaiting_choice' and not row['ready']
        finally:
            worker.close()


async def test_real_pdf_skip_publisher_and_manual_correction(environment, rag_pool, monkeypatch, tmp_path):
    import os
    from pathlib import Path
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    from app import sources
    from app.ocr import SKIP_TEXT
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    admin={'Authorization':'Bearer '+environment['admin']['token']}
    pdf=(Path(__file__).resolve().parents[2]/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/mixed-real-title-fixture-v1.pdf').read_bytes()
    with TestClient(create_app()) as client:
        policy_url='/api/documents/policies/'+str(environment['user']['id'])
        value=client.get(policy_url,headers=headers).json()
        assert client.patch(policy_url,headers=admin,json={'limits':value['limits'],'permissions':value['permissions']|{'handwriting':False}}).status_code==200
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'mixed.pdf','size':len(pdf)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=pdf).json()['state']=='awaiting_choice'
        assert client.post('/api/documents/'+document+'/mode',headers=headers,json={'choice':'skip_handwriting'}).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        try:
            assert await worker.process_one()
            response=client.get('/api/documents/'+document,headers=headers)
            assert response.status_code==200
            before=response.json()
            text=before['pages'][0]['text']
            assert text.count(SKIP_TEXT)==2 and 'Dreams' not in text and 'Hughes' not in text
            assert 'Гадавы бюджэт складае 100 еўра.' in text and 'The annual budget is 100 euros.' in text
            assert client.get('/api/documents/'+document+'/original',headers=headers).content==pdf
            async with rag_pool.connection() as connection:
                query=worker.embedder.encode(['The annual budget is 100 euros.'],query=True)[0]
                found=await sources.retrieve(connection,environment['user']['id'],[document],query)
                assert found and all(row['kind']=='printed' and SKIP_TEXT not in row['text'] for row in found)
            body={'base_revision':before['document']['published_revision'],'pages':[{'page':1,'text':text.replace('100','10')}]}
            assert client.post('/api/documents/'+document+'/corrections',headers=headers,json=body).status_code==200
            assert await worker.process_one()
            after=client.get('/api/documents/'+document,headers=headers).json()
            assert after['pages'][0]['text'].count(SKIP_TEXT)==2 and '10 euros' in after['pages'][0]['text']
            async with rag_pool.connection() as connection:
                query=worker.embedder.encode(['The annual budget is 10 euros.'],query=True)[0]
                found=await sources.retrieve(connection,environment['user']['id'],[document],query)
                assert found and any('10 euros' in row['text'] for row in found)
                assert all(SKIP_TEXT not in row['text'] for row in found)
            assert client.get('/api/documents/'+document+'/original',headers=headers).content==pdf
            print('Real PDFium/D-FINE/native full-context GGUF/E5/pgvector whole publisher and manual text correction; fixture issuer is component-only.')
        finally:
            worker.close()


async def test_long_unicode_original_has_no_silent_embedding_tail_loss(environment, rag_pool, monkeypatch, tmp_path):
    import os
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    text='文'*1200+'\nКонец документа.'
    content=text.encode()
    with TestClient(create_app()) as client:
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'unicode.txt','size':len(content)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        assert await worker.process_one()
        async with rag_pool.connection() as connection:
            chunks=await (await connection.execute('SELECT text,span_start,span_end FROM source_chunks c JOIN documents d ON d.published_revision=c.revision_id WHERE d.id=%s ORDER BY span_start',(document,))).fetchall()
        assert ''.join(row['text'] for row in chunks)==text
        assert len(chunks)>1 and chunks[-1]['span_end']==len(text)
        for chunk in chunks:
            assert not worker.embedder.tokenizer.encode('passage: '+chunk['text']).overflowing


async def test_real_publisher_preserves_complete_short_paragraphs_and_exact_spans(environment,rag_pool,monkeypatch,tmp_path):
    import os
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn']);monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    paragraphs=['The permitted annual budget is 100 euros. '*12,
                'The exception applies only to non-political crimes. '*9,
                'Everyone has the right to a nationality. '*8]
    text='\n\n'.join(paragraphs);content=text.encode()
    with TestClient(create_app()) as client:
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'paragraphs.txt','size':len(content)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        try:
            assert await worker.process_one()
            async with rag_pool.connection() as connection:
                chunks=await (await connection.execute('SELECT text,span_start,span_end FROM source_chunks c JOIN documents d ON d.published_revision=c.revision_id WHERE d.id=%s ORDER BY span_start',(document,))).fetchall()
            assert ''.join(row['text'] for row in chunks)==text
            for paragraph in paragraphs:
                assert any(paragraph in row['text'] for row in chunks),chunks
            assert all(text[row['span_start']:row['span_end']]==row['text'] for row in chunks)
            assert client.get('/api/documents/'+document+'/original',headers=headers).content==content
        finally:worker.close()


async def test_short_unrelated_paragraphs_have_separate_searchable_spans(environment,rag_pool,monkeypatch,tmp_path):
    import os
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn']);monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    paragraphs=['The library budget is 100 euros.',
                'The exception applies only to non-political crimes.',
                'Everyone has the right to a nationality.']
    text='\n\n'.join(paragraphs);content=text.encode()
    headers={'Authorization':'Bearer '+environment['user']['token']}
    with TestClient(create_app()) as client:
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'separate-paragraphs.txt','size':len(content)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        try:
            assert await worker.process_one()
            async with rag_pool.connection() as connection:
                chunks=await (await connection.execute('SELECT text,span_start,span_end FROM source_chunks c JOIN documents d ON d.published_revision=c.revision_id WHERE d.id=%s ORDER BY span_start',(document,))).fetchall()
            assert len(chunks)==len(paragraphs)
            assert ''.join(row['text'] for row in chunks)==text
            assert all(row['text'].strip()==paragraph for row,paragraph in zip(chunks,paragraphs))
            assert all(text[row['span_start']:row['span_end']]==row['text'] for row in chunks)
            assert client.get('/api/documents/'+document+'/original',headers=headers).content==content
        finally:worker.close()


async def test_docx_headers_footnotes_and_body_are_all_published(environment,rag_pool,monkeypatch,tmp_path):
    import os
    from io import BytesIO
    from zipfile import ZipFile
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn']);monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    package=BytesIO()
    with ZipFile(package,'w') as archive:
        for name,text in [('document.xml','Main owned fact.'),('header1.xml','Header owned fact.'),('footnotes.xml','Footnote owned fact.')]:
            archive.writestr('word/'+name,f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:document>')
    content=package.getvalue();headers={'Authorization':'Bearer '+environment['user']['token']}
    with TestClient(create_app()) as client:
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'owned.docx','size':len(content)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        assert await worker.process_one()
        result=client.get('/api/documents/'+document,headers=headers).json()
        text='\n'.join(page['text'] for page in result['pages'])
        assert 'Main owned fact.' in text and 'Header owned fact.' in text and 'Footnote owned fact.' in text
        assert client.get('/api/documents/'+document+'/original',headers=headers).content==content


@pytest.mark.parametrize('revoke_after_ocr',[False,True])
async def test_real_docx_embedded_handwriting_is_processed_before_publication(environment,rag_pool,monkeypatch,tmp_path,revoke_after_ocr):
    import os
    from io import BytesIO
    from zipfile import ZipFile
    from pathlib import Path
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn']);monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    package=BytesIO()
    with ZipFile(package,'w') as archive:
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Owned body with embedded handwriting.</w:t></w:r></w:p></w:document>')
        image_name='mixed-real-title-fixture-v1.png' if revoke_after_ocr else 'real-handwritten-title-author-input-v1.png'
        archive.writestr('word/media/title.png',(Path(__file__).resolve().parents[2]/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof'/image_name).read_bytes())
    content=package.getvalue();headers={'Authorization':'Bearer '+environment['user']['token']}
    with TestClient(create_app()) as client:
        document=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':'image.docx','size':len(content)}]}).json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        if revoke_after_ocr:
            stage_page=worker.stage_page
            async def revoke_before_image_publication(job,revision,page,text,regions):
                if page==2:
                    assert any(region['kind']=='handwritten' for region in regions)
                    policy_url='/api/documents/policies/'+str(environment['user']['id'])
                    policy=client.get(policy_url,headers=headers).json()
                    admin={'Authorization':'Bearer '+environment['admin']['token']}
                    assert client.patch(policy_url,headers=admin,json={'limits':policy['limits'],'permissions':policy['permissions']|{'handwriting':False}}).status_code==200
                    assert client.patch(policy_url,headers=admin,json={'limits':policy['limits'],'permissions':policy['permissions']}).status_code==200
                await stage_page(job,revision,page,text,regions)
            monkeypatch.setattr(worker,'stage_page',revoke_before_image_publication)
        try:
            assert await worker.process_one()
            response=client.get('/api/documents/'+document,headers=headers)
            if revoke_after_ocr:
                assert response.status_code==409
                current=client.get('/api/documents',headers=headers).json()['documents'][0]
                assert current['state']=='failed' and current['error']=='document_permission_revoked' and not current['ready']
                assert client.get('/api/documents/'+document+'/original',headers=headers).content==content
                return
            assert response.status_code==200
            text='\n'.join(page['text'] for page in response.json()['pages'])
            assert 'Owned body' in text and 'Dreams' in text and 'Langston Hughes' in text
            assert client.get('/api/documents/'+document+'/original',headers=headers).content==content
        finally:worker.close()


async def test_bad_file_does_not_publish_partial_text_or_cancel_good_batch_file(environment,rag_pool,monkeypatch,tmp_path):
    import os
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn']);monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    headers={'Authorization':'Bearer '+environment['user']['token']}
    files=[('invalid.txt',b'Valid prefix then invalid UTF8: \xff'),('good.md',b'# Owned valid document\nThe annual budget is 100 euros.')]
    with TestClient(create_app()) as client:
        batch=client.post('/api/documents/uploads',headers=headers,json={'files':[{'name':name,'size':len(data)} for name,data in files]}).json()['documents']
        for document,(_,data) in zip(batch,files):assert client.put('/api/documents/'+document['id']+'/original',headers=headers,content=data).status_code==200
        worker=DocumentWorker(rag_pool,E5Embedder(os.environ['RAG_E5_DIR']))
        assert await worker.process_one() and await worker.process_one()
        assert client.get('/api/documents/'+batch[0]['id'],headers=headers).status_code==409
        assert client.get('/api/documents/'+batch[1]['id'],headers=headers).json()['pages'][0]['text']==files[1][1].decode()
        async with rag_pool.connection() as connection:
            row=await (await connection.execute('SELECT ready,published_revision FROM documents WHERE id=%s',(batch[0]['id'],))).fetchone()
        assert not row['ready'] and row['published_revision'] is None
