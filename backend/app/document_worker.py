import asyncio
from contextlib import asynccontextmanager
import hashlib
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import ZipFile
from threading import Event

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app import documents, sources
from app.auth import AccessError, lock_service
from app.db import database_url
from app.rag import E5Embedder


WORD = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def extract_text(path, format):
    if format in ('txt', 'md'):
        return path.read_bytes().decode('utf-8-sig')
    return '\n'.join(part['text'] for part in docx_parts(path) if 'text' in part)


def docx_parts(path):
    with ZipFile(path) as archive:
        names=archive.namelist()
        if 'word/document.xml' not in names:
            raise AccessError('invalid_docx',422)
        texts=['word/document.xml']+[name for name in sorted(names) if name.startswith(('word/header','word/footer','word/footnotes','word/endnotes','word/comments')) and name.endswith('.xml')]
        result=[]
        for name in texts:
            paragraphs=[]
            with archive.open(name) as source:
                for _,node in ElementTree.iterparse(source,events=('end',)):
                    if node.tag==WORD+'p':
                        paragraphs.append(''.join(child.text or '' if child.tag==WORD+'t' else '\t' if child.tag==WORD+'tab' else '\n' if child.tag==WORD+'br' else '' for child in node.iter()))
                        node.clear()
            result.append({'name':name,'text':'\n'.join(paragraphs)})
        # Never extract ZIP paths to disk or follow external relationship URLs.
        result += [{'name':name,'image':archive.read(name)} for name in sorted(names) if name.startswith('word/media/') and not name.endswith('/')]
        return result


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024*1024):
            digest.update(chunk)
    return digest.hexdigest()


class DocumentWorker:
    def __init__(self, pool, embedder):
        self.pool, self.embedder = pool, embedder
        self.ocr = None

    @asynccontextmanager
    async def guard(self, job):
        async with self.pool.connection() as connection, connection.transaction():
            await lock_service(connection)
            actor = await (await connection.execute('SELECT * FROM accounts WHERE id=%s FOR SHARE', (job['owner_id'],))).fetchone()
            if not actor or not actor['verified'] or not actor['active'] or actor['disabled'] or actor['context_epoch'] != job['account_epoch']:
                raise AccessError('document_access_lost')
            config = await documents.policy(connection, job['owner_id'])
            row = await documents.owned(connection, actor, job['document_id'], write=True)
            if row['state'] != 'processing':
                raise AccessError('document_job_ended', 409)
            identity = await (await connection.execute('SELECT job_id FROM document_files WHERE document_id=%s', (job['document_id'],))).fetchone()
            if identity['job_id'] != job['job_id']:
                raise AccessError('document_job_ended', 409)
            if job['correction_pages'] is None and (not config['permissions'][job['format']] or ((job['format']=='pdf' and job['mode']=='complete' or job.get('needs_handwriting')) and not config['permissions']['handwriting'])):
                raise AccessError('document_permission_revoked')
            if job['correction_pages'] is None and job.get('needs_handwriting') and config['handwriting_epoch'] != job['admitted_handwriting_epoch']:
                raise AccessError('document_permission_revoked')
            if job['correction_base'] and row['published_revision'] != job['correction_base']:
                raise AccessError('document_revision_changed',409)
            yield connection, actor

    async def claim(self):
        async with self.pool.connection() as connection, connection.transaction():
            await lock_service(connection, exclusive=True)
            row = await (await connection.execute(
                '''SELECT f.*,d.owner_id,a.context_epoch AS account_epoch FROM document_files f
                   JOIN documents d ON d.id=f.document_id JOIN accounts a ON a.id=d.owner_id
                   WHERE f.state='queued' AND NOT d.deleted ORDER BY f.created_at,f.document_id LIMIT 1''',
            )).fetchone()
            if not row:
                return None
            row['job_id'] = uuid4()
            await connection.execute("UPDATE document_files SET state='processing',job_id=%s,error=NULL WHERE document_id=%s", (row['job_id'], row['document_id']))
            return row

    async def reconcile_lost(self):
        # Only the newly acquired singleton worker may fence its predecessor's jobs.
        async with self.pool.connection() as connection, connection.transaction():
            await lock_service(connection, exclusive=True)
            await connection.execute(
                """UPDATE source_revisions r SET status='failed' FROM document_files f
                   WHERE r.document_id=f.document_id AND r.status='staging' AND f.state='processing'""",
            )
            await connection.execute(
                "UPDATE document_files SET state='failed',error='document_worker_lost',job_id=NULL WHERE state='processing'",
            )

    async def failed(self, job, reason, page=None, revision_id=None):
        async with self.pool.connection() as connection, connection.transaction():
            await lock_service(connection)
            await connection.execute("UPDATE document_files SET state='failed',error=%s,failure_page=%s WHERE document_id=%s AND job_id=%s AND state='processing'",
                                     (reason, page, job['document_id'], job['job_id']))
            if revision_id:
                await connection.execute("UPDATE source_revisions SET status='failed' WHERE id=%s AND status='staging'", (revision_id,))

    async def stage_page(self, job, revision_id, page, text, regions):
        async with self.guard(job) as (connection, _):
            await connection.execute("INSERT INTO source_pages VALUES (%s,%s,'processing')", (revision_id, page))
            await connection.execute('INSERT INTO document_page_texts VALUES (%s,%s,%s,%s)', (revision_id, page, text, Jsonb(regions)))
        # Exact recognized/manual spans; skip markers never become searchable evidence.
        spans = regions if regions else [{'start':0,'end':len(text),'kind':'printed'}]
        for region in spans:
            start = region['start']
            while start < region['end']:
                part = text[start:min(start+800,region['end'])]
                encoded = self.embedder.tokenizer.encode('passage: '+part)
                if encoded.overflowing:
                    part = part[:max(end for _,end in encoded.offsets)-len('passage: ')]
                if not part:
                    raise AccessError('document_tokenization_failed',422)
                vector = [0.0]*384 if region['kind']=='skip' else (await asyncio.to_thread(self.embedder.encode, [part]))[0]
                async with self.guard(job) as (connection, _):
                    await connection.execute(
                        '''INSERT INTO source_chunks(id,revision_id,page,text,span_start,span_end,kind,coordinates,embedding)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)''',
                        (uuid4(), revision_id, page, part, start, start+len(part), region['kind'],
                         Jsonb({key:value for key,value in region.items() if key not in ('text','start','end','kind')}),
                         '['+','.join(map(str, vector))+']'),
                    )
                start += len(part)
        async with self.guard(job) as (connection, _):
            await connection.execute("UPDATE source_pages SET status='ready' WHERE revision_id=%s AND page=%s", (revision_id, page))

    async def recognize_page(self,job,prepared):
        cancelled = Event()
        async def watch():
            while True:
                try:
                    async with self.guard(job):
                        pass
                except AccessError:
                    cancelled.set()
                    return
                await asyncio.sleep(.1)
        future = asyncio.create_task(asyncio.to_thread(self.ocr.finish_page,prepared,cancelled))
        watcher = asyncio.create_task(watch())
        try:
            return await asyncio.shield(future)
        finally:
            cancelled.set()
            watcher.cancel()
            # Cancellation cannot free a context while its actual C call still owns it.
            await asyncio.gather(future,watcher,return_exceptions=True)

    async def process_one(self):
        job = await self.claim()
        if not job:
            return False
        current_page, revision_id = None, None
        try:
            async with self.guard(job):
                pass
            path = documents.original_path(job['document_id'])
            if await asyncio.to_thread(file_digest, path) != job['original_sha256']:
                raise AccessError('original_integrity_failure', 409)
            if job['correction_pages'] is not None:
                page_count = len(job['correction_pages'])
            elif job['format']=='docx':
                parts=await asyncio.to_thread(docx_parts,path)
                page_count=len(parts)
            elif job['format'] == 'pdf':
                from app.ocr import DocumentOCR
                if self.ocr is None:
                    self.ocr = await asyncio.to_thread(DocumentOCR)
                page_count = await asyncio.to_thread(self.ocr.page_count, path)
                if page_count > job['admitted_limits']['pdf_pages']:
                    raise AccessError('pdf_page_limit', 413)
            else:
                page_count = 1
            revision_id = uuid4()
            async with self.guard(job) as (connection, _):
                await connection.execute("INSERT INTO source_revisions(id,document_id,status,upload_complete,page_count,mode,skip_confirmed) VALUES (%s,%s,'staging',true,%s,%s,%s)",
                                         (revision_id, job['document_id'], page_count, job['mode'], job['mode']=='skip_handwriting'))
            for page in range(1, page_count+1):
                current_page = page
                async with self.guard(job):
                    pass
                if job['correction_pages'] is not None:
                    result = job['correction_pages'][page-1]
                    text, regions = result['text'], result['regions']
                elif job['format']=='pdf':
                    prepared = await asyncio.to_thread(self.ocr.prepare_page, path, page, job['mode'])
                    async with self.guard(job):
                        pass
                    result = await self.recognize_page(job,prepared)
                    text, regions = result['text'], result['regions']
                elif job['format']=='docx':
                    part=parts[page-1]
                    if 'text' in part:
                        text=part['text'];regions=[{'kind':'printed','start':0,'end':len(text),'source_part':part['name']}]
                    else:
                        from PIL import Image
                        from app.ocr import DocumentOCR
                        if self.ocr is None:
                            self.ocr=await asyncio.to_thread(DocumentOCR)
                        image=await asyncio.to_thread(lambda:Image.open(BytesIO(part['image'])).convert('RGB'))
                        prepared=await asyncio.to_thread(self.ocr.prepare_image,image,'complete')
                        job['needs_handwriting']=job.get('needs_handwriting',False) or bool(prepared['handwriting'])
                        async with self.guard(job):
                            pass
                        result=await self.recognize_page(job,prepared)
                        text,regions=result['text'],result['regions']
                        for region in regions:
                            region['source_part']=part['name']
                else:
                    text, regions = await asyncio.to_thread(extract_text, path, job['format']), []
                await self.stage_page(job, revision_id, page, text, regions)
            async with self.guard(job) as (connection, actor):
                if job['mode']=='skip_handwriting':
                    limitations = [{'kind':'handwriting_ocr_disabled','message':'Обработан только печатный текст; рукописные участки пропущены.'}]
                    await connection.execute('UPDATE source_revisions SET limitations=%s WHERE id=%s', (Jsonb(limitations),revision_id))
                await connection.execute("UPDATE source_revisions SET status='published' WHERE id=%s", (revision_id,))
                await connection.execute('UPDATE documents SET ready=true WHERE id=%s', (job['document_id'],))
                await sources.switch_source(connection, actor, job['document_id'], revision_id=revision_id)
                await connection.execute("UPDATE document_files SET state='ready',job_id=NULL WHERE document_id=%s", (job['document_id'],))
        except Exception as error:
            reason = error.code if isinstance(error, AccessError) else 'invalid_utf8' if isinstance(error, UnicodeDecodeError) else 'document_processing_failed'
            await self.failed(job, reason, current_page, revision_id)
        return True

    def close(self):
        if self.ocr is not None:
            self.ocr.close()


async def run():
    async with await AsyncConnection.connect(database_url(), autocommit=True) as keeper:
        claimed = await (await keeper.execute("SELECT pg_try_advisory_lock(hashtextextended('rag:document-worker',0))")).fetchone()
        if not claimed[0]:
            raise RuntimeError('Another document worker owns processing')
        async with AsyncConnectionPool(database_url(), open=False, kwargs={'autocommit': True, 'row_factory': dict_row, 'prepare_threshold': 0}) as pool:
            await pool.wait()
            worker = DocumentWorker(pool, None)
            await worker.reconcile_lost()
            worker.embedder = E5Embedder(os.environ['RAG_E5_DIR'])
            try:
                while True:
                    await keeper.execute('SELECT 1')
                    if not await worker.process_one():
                        await asyncio.sleep(.25)
            finally:
                worker.close()


def main():
    asyncio.run(run())


if __name__=='__main__':
    main()
