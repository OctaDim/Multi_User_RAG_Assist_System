"""U7 mutation integration: actual issuer, browser, OCR publisher and Qwen."""
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont
import psycopg
from psycopg.rows import dict_row
from playwright.sync_api import expect
import pytest

from .test_accounts import BACKEND, real_account_browser, register, login, navigate, open_sources
from .test_documents import real_document_browser, ready


@pytest.fixture
def paused_native_browser(real_document_browser,environment,tmp_path,request):
    marker,release=tmp_path/'native-pause',tmp_path/'native-release'
    mode=request.param
    hook=tmp_path/'native-worker.py'
    hook.write_text(f'''import logging,time
from pathlib import Path
from app.llama_runtime import LlamaContext
logging.basicConfig(level=logging.DEBUG)
original=LlamaContext.advance
marker=Path({str(marker)!r});release=Path({str(release)!r})
def advance(self):
    if not marker.exists() and ({mode!r}=='before' or (len(self.output_tokens)>=3 and not self._decoder.getstate()[0])):
        marker.write_text('inside real native context')
        while not release.exists():time.sleep(.01)
    return original(self)
LlamaContext.advance=advance
from app.generation import main
main()
''')
    launcher=tmp_path/'native-supervisor.py'
    launcher.write_text(f'''from app import generation
original=generation.subprocess.Popen
def spawn(args,**kwargs):
    if '--worker' in args:args=[args[0],{str(hook)!r},*args[3:]]
    return original(args,**kwargs)
generation.subprocess.Popen=spawn
generation.main()
''')
    log_path=tmp_path/'generation.log'
    with log_path.open('xb') as log:
        process=subprocess.Popen([sys.executable,str(launcher)],cwd=BACKEND,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
        try:
            until=time.monotonic()+30
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                while True:
                    row=connection.execute('SELECT epoch,healthy_until>clock_timestamp() FROM coordinator_lease WHERE id=1').fetchone()
                    if row[0]>1 and row[1]:break
                    assert process.poll() is None and time.monotonic()<until,log_path.read_text()
                    time.sleep(.05)
            yield real_document_browser,marker,release,log_path,mode
        finally:
            release.touch(exist_ok=True)
            process.terminate()
            try:process.wait(15)
            except subprocess.TimeoutExpired:process.kill();process.wait(10)
            records=[json.loads(line) for line in log_path.read_text().splitlines() if line.startswith('{"event": "native_spawn"')]
            assert all(not Path(f"/proc/{row['pid']}").exists() for row in records)


def scanned_budget():
    image=Image.new('RGB',(1400,350),'white')
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',42)
    ImageDraw.Draw(image).text((60,130),'The annual budget is 100 euros.',font=font,fill='black')
    output=BytesIO();image.save(output,format='PDF',resolution=150)
    return output.getvalue()


@pytest.mark.parametrize('paused_native_browser,mutation',[
    ('before','delete'),('after','delete'),('after','correction')],indirect=['paused_native_browser'])
def test_real_ocr_mutation_preserves_original_and_excludes_future_context(paused_native_browser,environment,mutation):
    ((browser,mailbox,frontend,api_url),_,_),marker,release,log_path,mode=paused_native_browser
    context=browser.new_context()
    try:
        page=context.new_page();email='u7-real-'+mutation+'-'+str(marker.parent.name)+'@owned.test'
        register(page,mailbox,frontend,email)
        page.on('console',lambda message:print('U7 browser console:',message.text,flush=True))
        page.on('requestfailed',lambda request:print('U7 failed HTTP:',request.method,request.url,request.failure,flush=True))
        try:login(page,email)
        except Exception:
            print('U7 login status:',page.locator('#status').inner_text(),flush=True)
            raise
        navigate(page,'library')
        page.locator('#document-upload input').set_input_files({'name':'scanned-budget.pdf','mimeType':'application/pdf','buffer':scanned_budget()})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        item=ready(page,'scanned-budget.pdf',timeout=300)
        item.get_by_role('button',name='Открыть документ',exact=True).click()
        original=page.locator('#document-correction textarea').input_value()
        assert '100' in original,'Actual OCR must read the source before this proof'
        navigate(page,'chat')
        open_sources(page)
        page.get_by_role('checkbox',name='scanned-budget.pdf',exact=True).check()
        navigate(page,'evidence')
        page.locator('#question').fill('What is the annual budget? Cite the source.')
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#early-fragments blockquote')).to_contain_text('100',timeout=120000)
        until=time.monotonic()+120
        while not marker.exists() and time.monotonic()<until:page.wait_for_timeout(50)
        assert marker.exists(),'Real native context did not reach the controlled computation boundary'
        if mode=='after':
            expect(page.locator('#history .answer-text')).not_to_have_text('',timeout=120000)
        if mutation=='delete':
            navigate(page,'library')
            item.get_by_role('button',name='Удалить документ',exact=True).click()
            page.locator('#confirm-accept').click()
            navigate(page,'chat')
            expect(page.locator('#history')).to_contain_text('Источник удалён',timeout=15000)
            expect(page.locator('#history')).to_contain_text('Прерван',timeout=15000)
        else:
            navigate(page,'library')
            item.get_by_role('button',name='Открыть документ',exact=True).click()
            page.locator('#document-correction textarea').fill(original.replace('100','10'))
            page.get_by_role('button',name='Сохранить исправления',exact=True).click()
            expect(page.locator('#document-correction .operation-status')).to_contain_text('Исправления приняты')
            navigate(page,'library')
            ready(page,'scanned-budget.pdf',timeout=300)
            navigate(page,'chat')
            expect(page.locator('#history')).to_contain_text('OCR исправлен',timeout=15000)
        release.touch()
        if mutation=='correction':
            expect(page.locator('#history')).to_contain_text('Завершён',timeout=180000)
        navigate(page,'evidence')
        expect(page.locator('#early-fragments')).to_contain_text('100')
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            row=connection.execute('''SELECT r.* FROM requests r JOIN accounts a ON a.id=r.owner_id
                WHERE a.email=%s ORDER BY r.created_at LIMIT 1''',(email,)).fetchone()
            assert row['state']==('completed' if mutation=='correction' else 'interrupted')
            messages=connection.execute("SELECT * FROM messages WHERE request_id=%s AND role='assistant'",(row['id'],)).fetchall()
            if messages:
                assert messages[0]['excluded'] and list(messages[0]['source_flags'].values())==['corrected' if mutation=='correction' else 'deleted']
            else:assert mutation=='delete' and mode=='before'
            if mode=='before':assert not messages and not row['answer_text']
            else:assert messages and row['answer_text']
            old_request,old_state=row['id'],row['state']
        if mutation=='delete':
            navigate(page,'library')
            page.locator('#document-upload input').set_input_files({'name':'current-budget.txt','mimeType':'text/plain','buffer':b'The annual budget is 10 euros.'})
            page.get_by_role('button',name='Загрузить документы',exact=True).click();ready(page,'current-budget.txt')
            navigate(page,'chat')
            open_sources(page)
            page.get_by_role('checkbox',name='current-budget.txt',exact=True).check()
        navigate(page,'chat')
        page.locator('#question').fill('What is the annual budget now? Cite the source.')
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#history article')).to_have_count(2)
        expect(page.locator('#history article').last).to_contain_text('Завершён',timeout=180000)
        with psycopg.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
            row=connection.execute('''SELECT r.* FROM requests r JOIN accounts a ON a.id=r.owner_id
                WHERE a.email=%s ORDER BY r.created_at DESC LIMIT 1''',(email,)).fetchone()
            assert str(old_request) not in row['passport']['history_requests']
            assert all('100' not in value['text'] for value in row['passport']['passed'])
            binding=connection.execute('SELECT * FROM graph_bindings WHERE request_id=%s',(row['id'],)).fetchone()
        async def checkpoint():
            from psycopg import AsyncConnection
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            async with await AsyncConnection.connect(environment['dsn'],autocommit=True,row_factory=dict_row) as connection:
                value=await AsyncPostgresSaver(connection).aget_tuple({'configurable':{'thread_id':binding['thread_id']}})
                assert value and str(old_request) not in repr(value.checkpoint)
                assert '100' not in value.checkpoint['channel_values']['prompt']
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(asyncio.run,checkpoint()).result(15)
        native=[json.loads(line[line.index('{'):]) for line in log_path.read_text().splitlines()
            if '"event": "native_allocate"' in line or '"event": "native_release"' in line]
        for identifier in (old_request,row['id']):
            assert sum(record['event']=='native_allocate' and record['request']==str(identifier) for record in native)==1
        assert sum(record['event']=='native_release' and record['request']==str(old_request) for record in native)==1
        print({'proof':'real_u7_ocr_invalidation','email':email,'mutation':mutation,'first_state':old_state,'next_state':row['state'],
            'native_trace':str(log_path),'actual_smtp_and_upload':True},flush=True)
    finally:
        release.touch(exist_ok=True);context.close()
