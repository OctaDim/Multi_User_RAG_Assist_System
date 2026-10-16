import asyncio
from contextlib import asynccontextmanager
import hashlib
from io import BytesIO
import os
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import ZipFile
from threading import Event

from sqlalchemy import func, insert, select, update

from app import documents, sources
from app.auth import AccessError, lock_service
from app.db import Database, database_url, migrate
from app.configuration import load_settings
from app.models import Account, Document, DocumentFile, DocumentPageText, SourceChunk, SourcePage, SourceRevision
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
        while chunk := source.read(load_settings('policy')['ingestion']['digest_block_bytes']):
            digest.update(chunk)
    return digest.hexdigest()


class DocumentWorker:
    def __init__(self, database, embedder):
        self.database, self.embedder = database, embedder
        self.ocr = None

    @asynccontextmanager
    async def guard(self, job):
        async with self.database.session() as session, session.begin():
            await lock_service(session)
            row = (await session.execute(select(Account.__table__).where(Account.id == job['owner_id'])
                   .with_for_update(read=True))).mappings().first()
            actor = dict(row) if row else None
            if not actor or not actor['verified'] or not actor['active'] or actor['disabled'] or actor['context_epoch'] != job['account_epoch']:
                raise AccessError('document_access_lost')
            config = await documents.policy(session, job['owner_id'])
            row = await documents.owned(session, actor, job['document_id'], write=True)
            if row['state'] != 'processing':
                raise AccessError('document_job_ended', 409)
            identity = (await session.execute(select(DocumentFile.job_id).where(
                DocumentFile.document_id == job['document_id']))).scalar_one()
            if identity != job['job_id']:
                raise AccessError('document_job_ended', 409)
            if job['correction_pages'] is None and (not config['permissions'][job['format']] or ((job['format']=='pdf' and job['mode']=='complete' or job.get('needs_handwriting')) and not config['permissions']['handwriting'])):
                raise AccessError('document_permission_revoked')
            if job['correction_pages'] is None and job.get('needs_handwriting') and config['handwriting_epoch'] != job['admitted_handwriting_epoch']:
                raise AccessError('document_permission_revoked')
            if job['correction_base'] and row['published_revision'] != job['correction_base']:
                raise AccessError('document_revision_changed',409)
            yield session, actor

    async def claim(self):
        async with self.database.session() as session, session.begin():
            await lock_service(session, exclusive=True)
            row = (await session.execute(
                select(DocumentFile.__table__, Document.owner_id, Account.context_epoch.label('account_epoch'))
                .join(Document, Document.id == DocumentFile.document_id).join(Account, Account.id == Document.owner_id)
                .where(DocumentFile.state == 'queued', ~Document.deleted)
                .order_by(DocumentFile.created_at, DocumentFile.document_id).limit(1)
            )).mappings().first()
            if not row:
                return None
            row = dict(row)
            row['job_id'] = uuid4()
            await session.execute(update(DocumentFile.__table__).where(DocumentFile.document_id == row['document_id'])
                                  .values(state='processing', job_id=row['job_id'], error=None))
            return row

    async def reconcile_lost(self):
        # Only the newly acquired singleton worker may fence its predecessor's jobs.
        async with self.database.session() as session, session.begin():
            await lock_service(session, exclusive=True)
            await session.execute(update(SourceRevision.__table__).where(
                SourceRevision.document_id == DocumentFile.document_id, SourceRevision.status == 'staging',
                DocumentFile.state == 'processing').values(status='failed'))
            await session.execute(update(DocumentFile.__table__).where(DocumentFile.state == 'processing')
                                  .values(state='failed', error='document_worker_lost', job_id=None))

    async def failed(self, job, reason, page=None, revision_id=None):
        async with self.database.session() as session, session.begin():
            await lock_service(session)
            await session.execute(update(DocumentFile.__table__).where(
                DocumentFile.document_id == job['document_id'], DocumentFile.job_id == job['job_id'],
                DocumentFile.state == 'processing').values(state='failed', error=reason, failure_page=page))
            if revision_id:
                await session.execute(update(SourceRevision.__table__).where(
                    SourceRevision.id == revision_id, SourceRevision.status == 'staging').values(status='failed'))

    async def stage_page(self, job, revision_id, page, text, regions):
        async with self.guard(job) as (session, _):
            await session.execute(insert(SourcePage).values(revision_id=revision_id, page=page, status='processing'))
            await session.execute(insert(DocumentPageText).values(revision_id=revision_id, page=page, text=text, regions=regions))
        # Exact recognized/manual spans; skip markers never become searchable evidence.
        spans = regions if regions else [{'start':0,'end':len(text),'kind':'printed'}]
        for region in spans:
            start = region['start']
            while start < region['end']:
                end = min(start+load_settings('policy')['ingestion']['chunk_characters'],region['end'])
                paragraph = text.find('\n\n',start+1,end)
                if paragraph > start:
                    end = paragraph+2
                part = text[start:end]
                prefix = load_settings('runtime')['embedding']['passage_prefix']
                encoded = self.embedder.tokenizer.encode(prefix+part)
                if encoded.overflowing:
                    retained = max(end for _,end in encoded.offsets)-len(prefix)
                    part = part[:max(0, retained)]
                if not part:
                    raise AccessError('document_tokenization_failed',422)
                vector = [0.0]*384 if region['kind']=='skip' else (await asyncio.to_thread(self.embedder.encode, [part]))[0]
                async with self.guard(job) as (session, _):
                    await session.execute(insert(SourceChunk).values(
                        id=uuid4(), revision_id=revision_id, page=page, text=part, span_start=start,
                        span_end=start+len(part), kind=region['kind'],
                        coordinates={key:value for key,value in region.items() if key not in ('text','start','end','kind')},
                        embedding=vector))
                start += len(part)
        async with self.guard(job) as (session, _):
            await session.execute(update(SourcePage.__table__).where(SourcePage.revision_id == revision_id, SourcePage.page == page)
                                  .values(status='ready'))

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
                await asyncio.sleep(load_settings('policy')['ingestion']['cancellation_poll_seconds'])
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
            async with self.guard(job) as (session, _):
                await session.execute(insert(SourceRevision).values(
                    id=revision_id, document_id=job['document_id'], status='staging', upload_complete=True,
                    page_count=page_count, mode=job['mode'], skip_confirmed=job['mode']=='skip_handwriting'))
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
            async with self.guard(job) as (session, actor):
                if job['mode']=='skip_handwriting':
                    limitations = [{'kind':'handwriting_ocr_disabled','message':'Обработан только печатный текст; рукописные участки пропущены.'}]
                    await session.execute(update(SourceRevision.__table__).where(SourceRevision.id == revision_id).values(limitations=limitations))
                await session.execute(update(SourceRevision.__table__).where(SourceRevision.id == revision_id).values(status='published'))
                await session.execute(update(Document.__table__).where(Document.id == job['document_id']).values(ready=True))
                await sources.switch_source(session, actor, job['document_id'], revision_id=revision_id)
                await session.execute(update(DocumentFile.__table__).where(DocumentFile.document_id == job['document_id'])
                                      .values(state='ready', job_id=None))
        except Exception as error:
            reason = error.code if isinstance(error, AccessError) else 'invalid_utf8' if isinstance(error, UnicodeDecodeError) else 'document_processing_failed'
            await self.failed(job, reason, current_page, revision_id)
        return True

    def close(self):
        if self.ocr is not None:
            self.ocr.close()


async def run():
    dsn = database_url()
    await migrate(dsn)
    database = Database(dsn)
    try:
        async with database.connection() as keeper:
            claimed = (await keeper.execute(select(func.pg_try_advisory_lock(
                func.hashtextextended('rag:document-worker', 0))))).scalar_one()
            await keeper.commit()
            if not claimed:
                raise RuntimeError('Another document worker owns processing')
            worker = DocumentWorker(database, None)
            try:
                await worker.reconcile_lost()
                worker.embedder = E5Embedder(os.environ['RAG_E5_DIR'])
                while True:
                    await keeper.execute(select(1))
                    await keeper.commit()
                    if not await worker.process_one():
                        await asyncio.sleep(load_settings('policy')['ingestion']['queue_poll_seconds'])
            finally:
                try:
                    worker.close()
                finally:
                    await keeper.execute(select(func.pg_advisory_unlock(func.hashtextextended('rag:document-worker', 0))))
                    await keeper.commit()
    finally:
        await database.dispose()


def main():
    asyncio.run(run())


if __name__=='__main__':
    main()
