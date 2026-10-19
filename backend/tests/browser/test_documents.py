"""Real UI/SMTP-created owners and real document worker; no ready-source seeds."""
import os
import re
import signal
from pathlib import Path
import subprocess
import sys
import time

from playwright.sync_api import expect
import pytest

from .test_accounts import BACKEND, real_account_browser, register, login


@pytest.fixture
def real_document_browser(real_account_browser,tmp_path):
    log_path=tmp_path/'document-worker.log'
    with log_path.open('wb') as log:
        worker=subprocess.Popen([str(BACKEND/'.venv/bin/rag-documents')],cwd=BACKEND,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
        try:
            yield real_account_browser,worker,log_path
        finally:
            worker.terminate()
            try:worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill();worker.wait(timeout=10)


def ready(page,name,timeout=20):
    if not page.locator('#library').is_visible(): page.locator('[data-area=library]').click()
    deadline=time.monotonic()+timeout
    read_timeout_ms=int(page.locator('meta[name=request-timeout-ms]').get_attribute('content'))+15000
    while time.monotonic()<deadline:
        remaining_ms=max(1,int((deadline-time.monotonic())*1000))
        page.get_by_role('button',name='Обновить статусы документов').click(timeout=min(remaining_ms,read_timeout_ms))
        item=page.locator('#documents li').filter(has=page.get_by_text(name,exact=True))
        if item.count() and item.locator(':scope > p').first.inner_text()=='Готов' and item.get_by_role('button',name='Открыть документ',exact=True).count():return item
        page.wait_for_timeout(300)
    raise AssertionError('Owned UI document did not become ready: '+name)


def test_ui_smtp_original_text_correction_and_delete(real_document_browser,tmp_path):
    (browser,mailbox,frontend,_),worker,_=real_document_browser
    context=browser.new_context()
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'documents-browser@owned.test')
        login(page,'documents-browser@owned.test')
        page.locator('[data-area=library]').click()
        content=b'The annual budget is 100 euros.\n<script>window.documentInjected=true</script>'
        page.locator('#document-upload input').set_input_files({'name':'budget.txt','mimeType':'text/plain','buffer':content})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        expect(page.locator('#status')).to_have_text('Файлы приняты. Обработка выполняется в фоне.')
        item=ready(page,'budget.txt')
        item.get_by_role('button',name='Открыть документ').click()
        expect(page.locator('#document-correction textarea')).to_have_value(content.decode())
        assert page.evaluate('window.documentInjected') is None
        with page.expect_download() as download:
            page.get_by_role('button',name='Скачать оригинал').click()
        saved=tmp_path/'original.txt';download.value.save_as(saved)
        assert saved.read_bytes()==content
        page.locator('#document-correction textarea').fill(content.decode().replace('100','10'))
        page.get_by_role('button',name='Сохранить исправления').click()
        expect(page.locator('#status')).to_have_text('Исправления приняты. Новая ревизия появится после полной индексации.')
        expect(page.get_by_role('button',name='Сохранить исправления',exact=True)).to_be_disabled()
        expect(page.locator('#document-correction textarea')).to_have_value(content.decode().replace('100','10'))
        page.get_by_role('button',name='Закрыть',exact=True).click()
        item=ready(page,'budget.txt')
        item.get_by_role('button',name='Открыть документ').click()
        expect(page.locator('#document-correction textarea')).to_have_value(content.decode().replace('100','10'))
        page.get_by_role('button',name='Закрыть',exact=True).click()
        item.get_by_role('button',name='Удалить документ').click()
        expect(page.locator('#confirm-description')).to_contain_text('budget.txt')
        page.locator('#confirm-cancel').click()
        expect(item).to_be_visible()
        item.get_by_role('button',name='Удалить документ').click()
        page.locator('#confirm-accept').click()
        expect(page.locator('#documents')).not_to_contain_text('budget.txt')
        assert worker.poll() is None
        print('Real UI signup/SMTP verification/login; original upload; actual E5 worker; whole ready view; no HTML execution; unchanged download; new correction; deletion.')
    finally:context.close()


def test_ui_permission_choice_actual_native_pdf_and_unchanged_original(real_document_browser,tmp_path):
    (browser,mailbox,frontend,api_url),worker,_=real_document_browser
    contexts=[browser.new_context() for _ in range(2)]
    held=[]
    try:
        operator,user=[context.new_page() for context in contexts]
        invitation=subprocess.run([sys.executable,'-m','app.accounts','--email','doc-operator@owned.test'],cwd=BACKEND,env=os.environ.copy(),check=True,capture_output=True,text=True).stdout.strip()
        register(operator,mailbox,frontend,'doc-operator@owned.test',invitation);login(operator,'doc-operator@owned.test')
        register(user,mailbox,frontend,'pdf-browser@owned.test');login(user,'pdf-browser@owned.test')
        user.locator('[data-area=library]').click()
        operator.reload()
        operator.locator('#nav-administration').click()
        card=operator.locator('article').filter(has=operator.locator('form[data-account="pdf-browser@owned.test"]'))
        card.locator('summary').click()
        policy=card.locator('form[data-policy]')
        expect(policy.locator('[name=handwriting]')).to_be_checked()
        policy.locator('[name=handwriting]').uncheck()
        policy.get_by_role('button',name='Сохранить ограничения документов').click()
        expect(operator.locator('#status')).to_have_text('Ограничения документов сохранены.')
        path=BACKEND.parent/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/mixed-real-title-fixture-v1.pdf'
        user.locator('#document-upload input').set_input_files(str(path))
        user.get_by_role('button',name='Загрузить документы',exact=True).click()
        expect(user.locator('#status')).to_have_text('Файлы приняты. Обработка выполняется в фоне.')
        expect(user.locator('#documents')).to_contain_text('OCR рукописей не разрешён')
        user.get_by_role('button',name='Загрузить только печатный текст').click()
        item=ready(user,path.name,timeout=120)
        item.get_by_role('button',name='Открыть документ').click()
        expect(user.locator('#document-correction textarea')).to_have_value(re.compile(r'The annual budget is 100 euros\.',re.S))
        text=user.locator('#document-correction textarea').input_value()
        assert 'Dreams' not in text and 'Hughes' not in text and text.count('Рукописный текст пропущен.')==2
        expect(user.locator('.original-page img')).to_be_visible()
        user.wait_for_function('document.querySelector(".original-page img")?.complete && document.querySelector(".original-page img").naturalWidth > 0',timeout=120000)
        expect(user.locator('.skip-region')).to_have_count(2)
        for width in (1440,768,375):
            user.set_viewport_size({'width':width,'height':1000})
            assert user.evaluate('document.documentElement.scrollWidth <= innerWidth')
            user.screenshot(path=str(tmp_path/f'pdf-editor-{width}.png'),full_page=True)
        user.set_viewport_size({'width':1440,'height':1000})
        with user.expect_download() as download:user.get_by_role('button',name='Скачать оригинал').click()
        saved=tmp_path/'mixed-original.pdf';download.value.save_as(saved)
        assert saved.read_bytes()==path.read_bytes()
        policy.locator('[name=handwriting]').check()
        policy.get_by_role('button',name='Сохранить ограничения документов').click()
        expect(operator.locator('#status')).to_have_text('Ограничения документов сохранены.')
        user.locator('#close-editor').click()
        user.locator('#document-upload input').set_input_files({'name':'neighbor-edit.txt','mimeType':'text/plain','buffer':b'Neighbor original'})
        user.get_by_role('button',name='Загрузить документы',exact=True).click();ready(user,'neighbor-edit.txt')
        item.get_by_role('button',name='Открыть документ').click()
        def hold_mode(route): held.append((route,route.fetch()))
        user.route(api_url+'/api/documents/*/mode',hold_mode)
        os.kill(worker.pid,signal.SIGSTOP)
        mode=user.get_by_role('button',name='Обработать PDF полностью',exact=True)
        mode_handle=mode.element_handle();mode.click();expect(mode).to_be_disabled()
        user.locator('#close-editor').click()
        neighbor=user.locator('#documents li').filter(has=user.get_by_text('neighbor-edit.txt',exact=True))
        neighbor.get_by_role('button',name='Открыть документ',exact=True).click()
        user.locator('#document-correction textarea').fill('Unsaved neighbor after delayed PDF mode')
        route,response=held.pop();assert response.status==200;route.fulfill(response=response)
        user.wait_for_function('(button)=>!button.disabled',arg=mode_handle)
        expect(user.locator('#document-editor')).to_be_visible()
        expect(user.locator('#document-view h3')).to_have_text('neighbor-edit.txt')
        expect(user.locator('#document-correction textarea')).to_have_value('Unsaved neighbor after delayed PDF mode')
        assert worker.poll() is None
        print('Real operator CLI/UI account; ordinary UI owner; policy saved in real admin form; explicit print-only PDF choice; actual PDFium/D-FINE/GGUF/E5 worker; spatial skip blocks and unchanged original.')
    finally:
        os.kill(worker.pid,signal.SIGCONT)
        for route,_ in held:
            try:route.abort()
            except Exception:pass
        for context in contexts:context.close()


def test_editor_refresh_close_guard_and_failed_save_preserve_text(real_document_browser):
    (browser,mailbox,frontend,api_url),worker,_=real_document_browser
    context=browser.new_context(viewport={'width':1440,'height':1000})
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'editor-guard@owned.test')
        login(page,'editor-guard@owned.test')
        page.locator('[data-area=library]').click()
        page.locator('#document-upload input').set_input_files({'name':'guard.txt','mimeType':'text/plain','buffer':b'Original source'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        item=ready(page,'guard.txt')
        item.get_by_role('button',name='Открыть документ').click()
        text=page.locator('#document-correction textarea')
        text.fill('Unsaved working text')
        page.get_by_role('button',name='Проверить обработку',exact=True).click()
        expect(text).to_have_value('Unsaved working text')
        page.get_by_role('button',name='Закрыть',exact=True).click()
        expect(page.locator('#confirm-title')).to_have_text('Несохранённые исправления')
        page.locator('#confirm-cancel').click()
        expect(text).to_have_value('Unsaved working text')
        page.route(api_url+'/api/documents/*/corrections',lambda route:route.fulfill(status=409,json={'error':'document_revision_changed'}))
        page.get_by_role('button',name='Сохранить исправления',exact=True).click()
        expect(page.locator('#document-correction .operation-status')).to_contain_text('Ревизия уже изменилась')
        expect(text).to_have_value('Unsaved working text')
        expect(page.get_by_role('button',name='Сохранить исправления',exact=True)).to_be_enabled()
        page.get_by_role('button',name='Закрыть',exact=True).click()
        page.locator('#confirm-accept').click()
        expect(page.locator('#document-editor')).not_to_be_visible()
        page.locator('#document-upload input').set_input_files({'name':'second.txt','mimeType':'text/plain','buffer':b'Second source'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        other=ready(page,'second.txt')
        first=page.locator('#documents li').filter(has=page.get_by_text('guard.txt',exact=True))
        first_id=first.get_attribute('data-document')
        held=[]
        def hold_read(route): held.append((route,route.fetch()))
        page.route(api_url+'/api/documents/'+first_id,hold_read)
        first.get_by_role('button',name='Открыть документ').click()
        other.get_by_role('button',name='Открыть документ').click()
        expect(page.locator('#document-correction textarea')).to_have_value('Second source')
        route,response=held.pop();route.fulfill(response=response)
        expect(page.locator('#document-correction textarea')).to_have_value('Second source')
        expect(page.locator('#document-view h3')).to_have_text('second.txt')
        assert worker.poll() is None
    finally:context.close()


def test_late_document_open_cannot_interrupt_chat(real_document_browser):
    (browser,mailbox,frontend,api_url),_,_=real_document_browser
    context=browser.new_context()
    held=[]
    try:
        page=context.new_page();register(page,mailbox,frontend,'late-editor@owned.test');login(page,'late-editor@owned.test')
        page.locator('[data-area=library]').click()
        page.locator('#document-upload input').set_input_files({'name':'late.txt','mimeType':'text/plain','buffer':b'Late source'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        item=ready(page,'late.txt');identifier=item.get_attribute('data-document')
        def hold(route): held.append((route,route.fetch()))
        page.route(api_url+'/api/documents/'+identifier,hold)
        button=item.get_by_role('button',name='Открыть документ',exact=True)
        button.click()
        page.locator('[data-area=chat]').click()
        page.locator('#question').fill('Keep writing while the old document read finishes')
        route,response=held.pop();route.fulfill(response=response)
        expect(item.get_by_role('button',name='Открыть документ',exact=True,include_hidden=True)).to_be_enabled()
        expect(page.locator('#document-editor')).to_be_hidden()
        expect(page.locator('#question')).to_have_value('Keep writing while the old document read finishes')
        expect(page.locator('#chat')).to_be_visible()
    finally:
        for route,_ in held:
            try:route.abort()
            except Exception:pass
        context.close()


def test_open_during_correction_becomes_editable_after_publication(real_document_browser):
    import signal
    (browser,mailbox,frontend,_),worker,_=real_document_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'queued-editor@owned.test');login(page,'queued-editor@owned.test')
        page.locator('[data-area=library]').click()
        page.locator('#document-upload input').set_input_files({'name':'queued.txt','mimeType':'text/plain','buffer':b'Original queued source'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        item=ready(page,'queued.txt');item.get_by_role('button',name='Открыть документ',exact=True).click()
        os.kill(worker.pid,signal.SIGSTOP)
        text=page.locator('#document-correction textarea');text.fill('New published source')
        page.get_by_role('button',name='Сохранить исправления',exact=True).click()
        expect(page.locator('#document-correction .operation-status')).to_contain_text('Исправления приняты')
        page.locator('#close-editor').click()
        page.locator('#refresh-documents').click()
        expect(item).to_contain_text('Ожидает обработки')
        item.get_by_role('button',name='Открыть документ',exact=True).click()
        expect(text).not_to_be_editable()
        expect(page.get_by_role('button',name='Сохранить исправления',exact=True)).to_be_disabled()
        os.kill(worker.pid,signal.SIGCONT)
        deadline=time.monotonic()+30
        while True:
            page.get_by_role('button',name='Проверить обработку',exact=True).click()
            if text.input_value()=='New published source':break
            assert time.monotonic()<deadline
            page.wait_for_timeout(100)
        expect(text).to_be_editable()
        expect(page.get_by_role('button',name='Сохранить исправления',exact=True)).to_be_enabled()
    finally:
        os.kill(worker.pid,signal.SIGCONT)
        context.close()


def test_external_delete_preserves_unsaved_editor_text(real_document_browser):
    (browser,mailbox,frontend,_),_,_=real_document_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'external-delete@owned.test');login(page,'external-delete@owned.test')
        page.locator('[data-area=library]').click()
        page.locator('#document-upload input').set_input_files({'name':'external.txt','mimeType':'text/plain','buffer':b'Original source'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        item=ready(page,'external.txt');item.get_by_role('button',name='Открыть документ',exact=True).click()
        text=page.locator('#document-correction textarea');text.fill('Unsaved text that must survive deletion elsewhere')
        other=context.new_page();other.goto(frontend);login(other,'external-delete@owned.test')
        other.locator('[data-area=library]').click()
        other.locator('#documents li').get_by_role('button',name='Удалить документ',exact=True).click()
        other.locator('#confirm-accept').click();expect(other.locator('#documents li')).to_have_count(0)
        page.get_by_role('button',name='Проверить обработку',exact=True).click()
        expect(text).to_have_value('Unsaved text that must survive deletion elsewhere')
        expect(page.locator('#document-correction .operation-status')).to_contain_text('удалён')
        expect(page.get_by_role('button',name='Сохранить исправления',exact=True)).to_be_disabled()
        page.locator('#close-editor').click();expect(page.locator('#confirm-action')).to_be_visible()
        page.locator('#confirm-cancel').click();expect(text).to_have_value('Unsaved text that must survive deletion elsewhere')
    finally:context.close()


def test_admitted_upload_timeout_recovers_inventory_and_blocks_duplicate_retry(real_document_browser):
    (browser,mailbox,frontend,api_url),_,_=real_document_browser
    context=browser.new_context()
    held=[];admissions=[]
    try:
        page=context.new_page();register(page,mailbox,frontend,'upload-timeout@owned.test');login(page,'upload-timeout@owned.test')
        def short_timeout(route):
            response=route.fetch()
            body=re.sub(r'(<meta name="request-timeout-ms" content=")[0-9]+',r'\g<1>1000',response.text())
            route.fulfill(response=response,body=body)
        page.route(frontend+'/',short_timeout);page.reload()
        expect(page.locator('html')).to_have_attribute('data-ready','true')
        page.locator('[data-area=library]').click()
        def delay_admission(route):
            admissions.append(route.request)
            response=route.fetch();held.append((route,response))
        page.route(api_url+'/api/documents/uploads',delay_admission)
        file={'name':'timeout.txt','mimeType':'text/plain','buffer':b'Accepted once'}
        page.locator('#document-upload input').set_input_files(file)
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        expect(page.locator('#document-upload .operation-status')).to_contain_text('Время ожидания истекло')
        expect(page.locator('#documents li')).to_have_count(1)
        expect(page.locator('#documents li')).to_contain_text('timeout.txt')
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        expect(page.locator('#document-upload .operation-status')).to_contain_text('Предыдущая загрузка могла быть принята')
        assert len(admissions)==1
        page.locator('#refresh-documents').click();expect(page.locator('#documents li')).to_have_count(1)
        page.locator('#documents li').get_by_role('button',name='Удалить документ',exact=True).click()
        page.locator('#confirm-accept').click();expect(page.locator('#documents li')).to_have_count(0)
        route,response=held.pop()
        try:route.fulfill(response=response)
        except Exception:pass  # The browser may already have cancelled the timed-out transport.
        page.unroute(api_url+'/api/documents/uploads',delay_admission)
        page.locator('#document-upload input').set_input_files(file)
        page.get_by_role('button',name='Загрузить документы',exact=True).click();ready(page,'timeout.txt')
        expect(page.locator('#documents li')).to_have_count(1)
    finally:
        for route,_ in held:
            try:route.abort()
            except Exception:pass
        context.close()


def test_refresh_timeout_preserves_editor_and_allows_manual_retry(real_document_browser):
    (browser,mailbox,frontend,api_url),_,_=real_document_browser
    context=browser.new_context();held=[]
    try:
        page=context.new_page();register(page,mailbox,frontend,'refresh-timeout@owned.test');login(page,'refresh-timeout@owned.test')
        def short_timeout(route):
            response=route.fetch()
            body=re.sub(r'(<meta name="request-timeout-ms" content=")[0-9]+',r'\g<1>1000',response.text())
            route.fulfill(response=response,body=body)
        page.route(frontend+'/',short_timeout);page.reload()
        expect(page.locator('html')).to_have_attribute('data-ready','true')
        page.locator('[data-area=library]').click()
        page.locator('#document-upload input').set_input_files({'name':'read-timeout.txt','mimeType':'text/plain','buffer':b'Original source'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        ready(page,'read-timeout.txt').get_by_role('button',name='Открыть документ',exact=True).click()
        text=page.locator('#document-correction textarea');text.fill('Keep unsaved edits through a timed-out status read')
        def delay_read(route):held.append(route)
        page.route(api_url+'/api/documents',delay_read)
        page.get_by_role('button',name='Проверить обработку',exact=True).click()
        expect(page.locator('#document-view .operation-status')).to_contain_text('Время ожидания истекло')
        expect(page.get_by_role('button',name='Проверить обработку',exact=True)).to_be_enabled()
        expect(text).to_have_value('Keep unsaved edits through a timed-out status read')
        for route in held:route.abort()
        held.clear();page.unroute(api_url+'/api/documents',delay_read)
        page.get_by_role('button',name='Проверить обработку',exact=True).click()
        expect(page.locator('#library-status')).to_have_text('Документов: 1')
        expect(text).to_have_value('Keep unsaved edits through a timed-out status read')
    finally:
        for route in held:
            try:route.abort()
            except Exception:pass
        context.close()


def test_failed_publication_keeps_accepted_correction_and_allows_explicit_retry(real_document_browser):
    from app.documents import original_path
    (browser,mailbox,frontend,_),worker,_=real_document_browser
    context=browser.new_context()
    stored=None;original=b'Original durable source'
    try:
        page=context.new_page();register(page,mailbox,frontend,'failed-publication@owned.test');login(page,'failed-publication@owned.test')
        page.locator('[data-area=library]').click()
        page.locator('#document-upload input').set_input_files({'name':'publication.txt','mimeType':'text/plain','buffer':original})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        item=ready(page,'publication.txt');stored=original_path(item.get_attribute('data-document'))
        item.get_by_role('button',name='Открыть документ',exact=True).click()
        text=page.locator('#document-correction textarea');text.fill('Accepted working text survives a failed publisher')
        os.kill(worker.pid,signal.SIGSTOP)
        stored.write_bytes(b'Controlled temporary integrity failure in this owned fixture')
        page.get_by_role('button',name='Сохранить исправления',exact=True).click()
        expect(page.locator('#document-correction .operation-status')).to_contain_text('Исправления приняты')
        os.kill(worker.pid,signal.SIGCONT)
        deadline=time.monotonic()+30
        while True:
            page.get_by_role('button',name='Проверить обработку',exact=True).click()
            if 'Индексация исправлений не завершена' in page.locator('#document-correction .operation-status').inner_text():break
            assert time.monotonic()<deadline
            page.wait_for_timeout(100)
        expect(text).to_have_value('Accepted working text survives a failed publisher')
        expect(text).to_be_editable()
        save=page.get_by_role('button',name='Сохранить исправления',exact=True);expect(save).to_be_enabled()
        stored.write_bytes(original)
        save.click();expect(page.locator('#document-correction .operation-status')).to_contain_text('Исправления приняты')
        deadline=time.monotonic()+30
        while page.locator('#document-correction').evaluate('(form)=>form.inert'):
            page.get_by_role('button',name='Проверить обработку',exact=True).click()
            assert time.monotonic()<deadline
            page.wait_for_timeout(100)
        expect(text).to_have_value('Accepted working text survives a failed publisher')
        expect(save).to_be_enabled()
        with page.expect_download() as download:page.get_by_role('button',name='Скачать оригинал',exact=True).click()
        assert download.value.failure() is None
        assert Path(download.value.path()).read_bytes()==original
    finally:
        if stored is not None:stored.write_bytes(original)
        os.kill(worker.pid,signal.SIGCONT)
        context.close()
