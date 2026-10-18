"""Real UI/SMTP-created owners and real document worker; no ready-source seeds."""
import os
import re
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
    while time.monotonic()<deadline:
        page.get_by_role('button',name='Обновить статусы документов').click()
        item=page.locator('#documents li').filter(has=page.get_by_text(name,exact=True))
        if item.count() and 'Готов' in item.inner_text():return item
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
    (browser,mailbox,frontend,_),worker,_=real_document_browser
    contexts=[browser.new_context() for _ in range(2)]
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
        expect(user.locator('.skip-region')).to_have_count(2)
        with user.expect_download() as download:user.get_by_role('button',name='Скачать оригинал').click()
        saved=tmp_path/'mixed-original.pdf';download.value.save_as(saved)
        assert saved.read_bytes()==path.read_bytes()
        assert worker.poll() is None
        print('Real operator CLI/UI account; ordinary UI owner; policy saved in real admin form; explicit print-only PDF choice; actual PDFium/D-FINE/GGUF/E5 worker; spatial skip blocks and unchanged original.')
    finally:
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
