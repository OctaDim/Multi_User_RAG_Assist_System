"""A fragment failure must not publish a page or a retrievable source."""
from io import BytesIO

from PIL import Image, ImageDraw

from app.auth import AccessError
from app.document_worker import DocumentWorker
from app.main import create_app
from app.ocr import DocumentOCR
from live_http import LiveClient


async def test_fragment_error_prevents_database_page_and_source_publication(
        environment,rag_pool,connection,monkeypatch,tmp_path):
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path))
    image=Image.new('RGB',(1000,3000),'white')
    draw=ImageDraw.Draw(image)
    draw.rectangle((50,100,200,130),fill='black')
    draw.rectangle((50,2800,200,2830),fill='black')
    output=BytesIO();image.save(output,format='PDF',resolution=72)
    content=output.getvalue()
    ocr=DocumentOCR.__new__(DocumentOCR)
    ocr.detect_handwriting=lambda image:[]
    calls=[]
    def recognize(image,cancelled):
        calls.append(image.size)
        if len(calls)>1:
            raise AccessError('ocr_truncated',422)
        return [{'kind':'printed','text':'Unpublished first fragment','bbox':[50,100,200,130]}]
    ocr.recognize=recognize
    headers={'Authorization':'Bearer '+environment['user']['token']}
    with LiveClient(create_app()) as client:
        response=client.post('/api/documents/uploads',headers=headers,json={
            'files':[{'name':'long.pdf','size':len(content)}]})
        assert response.status_code==201,response.text
        document=response.json()['documents'][0]['id']
        assert client.put('/api/documents/'+document+'/original',headers=headers,content=content).status_code==200
        worker=DocumentWorker(rag_pool,None)
        worker.ocr=ocr
        assert await worker.process_one()
        assert len(calls)==2
        current=(await (await connection.execute(
            'SELECT d.ready,d.published_revision,f.state,f.error,f.failure_page '
            'FROM documents d JOIN document_files f ON f.document_id=d.id WHERE d.id=%s',
            (document,))).fetchone())
        assert current=={'ready':False,'published_revision':None,'state':'failed',
                         'error':'ocr_truncated','failure_page':1}
        for table in ('document_page_texts','source_chunks'):
            count=await (await connection.execute(
                f'SELECT count(*) AS n FROM {table} p JOIN source_revisions r ON r.id=p.revision_id '
                'WHERE r.document_id=%s',(document,))).fetchone()
            assert count['n']==0
        assert client.get('/api/documents/'+document,headers=headers).status_code==409
        assert client.get('/api/documents/'+document+'/original',headers=headers).content==content
