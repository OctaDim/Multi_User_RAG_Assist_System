"""U6 proofs through actual signup/SMTP/browser/API; no seeded ready sources."""
import os
import json
import signal
import sys
import subprocess
import time

import psycopg
from playwright.sync_api import expect
import pytest

from .test_accounts import BACKEND, real_account_browser, register, login
from .test_documents import real_document_browser, ready


@pytest.fixture
def real_answer_browser(real_document_browser, environment, tmp_path):
    path = tmp_path/'generation.log'
    with psycopg.connect(environment['dsn'],autocommit=True) as connection:
        previous_epoch = connection.execute('SELECT epoch FROM service_state WHERE id=1').fetchone()[0]
    with path.open('wb') as log:
        process = subprocess.Popen([str(BACKEND/'.venv/bin/rag-generation')],cwd=BACKEND,env=os.environ.copy(),
                                   stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+30
            with psycopg.connect(environment['dsn'],autocommit=True) as connection:
                while True:
                    live = connection.execute('SELECT epoch,healthy_until>clock_timestamp() FROM coordinator_lease WHERE id=1').fetchone()
                    if live and live[0]>previous_epoch and live[1]:break
                    if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Owned generation did not become ready')
                    time.sleep(.1)
            yield real_document_browser, process, path
        finally:
            process.terminate()
            try:process.wait(15)
            except subprocess.TimeoutExpired:process.kill();process.wait(10)


def test_real_ui_keeps_independent_conversation_tab_drafts_and_refuses_no_sources(real_account_browser):
    browser, mailbox, frontend, _ = real_account_browser
    context = browser.new_context()
    try:
        first = context.new_page()
        register(first, mailbox, frontend, 'lifecycle-drafts@owned.test')
        login(first, 'lifecycle-drafts@owned.test')
        first.get_by_role('button', name='Открыть беседу', exact=True).click()
        first_id = first.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        first.locator('#question').fill('First tab A')
        first.get_by_role('button', name='Новая беседа', exact=True).click()
        expect(first.locator('#conversations li')).to_have_count(2)
        second_id = first.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        first.locator('#question').fill('First tab B')
        first.locator(f'#conversations button[data-conversation="{first_id}"]').click()
        expect(first.locator('#question')).to_have_value('First tab A')

        second = context.new_page()
        second.goto(frontend)
        login(second, 'lifecycle-drafts@owned.test')
        second.locator(f'#conversations button[data-conversation="{first_id}"]').click()
        second.locator('#question').fill('Second tab A')
        first.reload()
        expect(first.locator('#question')).to_have_value('First tab A')
        expect(second.locator('#question')).to_have_value('Second tab A')
        first.locator(f'#conversations button[data-conversation="{second_id}"]').click()
        expect(first.locator('#question')).to_have_value('First tab B')
        first.locator(f'#conversations button[data-conversation="{first_id}"]').click()
        first.get_by_role('button', name='Отправить вопрос', exact=True).click()
        expect(first.locator('#status')).to_contain_text('Нет готовых источников')
        expect(first.locator('#question')).to_have_value('First tab A')
        expect(first.locator('#history')).to_have_text('В этой беседе пока нет сообщений.')
        expect(second.locator('#question')).to_have_value('Second tab A')
        first.get_by_role('button', name='Выйти', exact=True).click()
        login(first, 'lifecycle-drafts@owned.test')
        expect(first.locator('#question')).to_have_value('')
    finally:
        context.close()


def test_real_fragments_precede_answer_without_waiting_for_history_read(real_answer_browser):
    ((browser,mailbox,frontend,_),worker,_),generation,_ = real_answer_browser
    context=browser.new_context()
    held=[]
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'lifecycle-answer@owned.test')
        login(page,'lifecycle-answer@owned.test')
        content=b'The annual budget is 100 euros.\n'
        page.locator('#document-upload input').set_input_files({'name':'answer-budget.txt','mimeType':'text/plain','buffer':content})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        ready(page,'answer-budget.txt')
        page.get_by_role('checkbox',name='answer-budget.txt',exact=True).check()
        page.evaluate("""() => {
          window.fragmentPrefix = undefined;
          window.fragmentObserver = new MutationObserver(() => {
            const fragment=document.querySelector('#early-fragments blockquote');
            if (fragment?.getClientRects().length && window.fragmentPrefix === undefined)
              window.fragmentPrefix=document.querySelector('#history .answer-text')?.textContent || '';
          });
          window.fragmentObserver.observe(document.body,{childList:true,subtree:true,characterData:true});
        }""")
        def hold_history(route):
            if route.request.method=='GET':held.append(route)
            else:route.continue_()
        page.route('**/api/conversations/*',hold_history)
        page.locator('#question').fill('What is the annual budget?')
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#early-fragments blockquote')).to_contain_text('100 euros')
        assert page.evaluate('window.fragmentPrefix') == ''
        expect(page.locator('#history .answer-text')).to_contain_text('100',timeout=30000)
        page.locator('#history .answer-passport summary').click()
        expect(page.locator('#history .answer-passport')).to_contain_text('answer-budget.txt')
        expect(page.locator('#history .answer-passport')).to_contain_text('Страница 1')
        expect(page.locator('#history .answer-text a').first).to_be_visible()
        page.locator('#history .answer-text a').first.click()
        expect(page.locator('#history .cited-quote')).to_have_text(content.decode().strip())
        expect(page.locator('#history')).to_contain_text('Завершён',timeout=30000)
        page.evaluate("""() => {
          window.answerNoopMutations = 0;
          window.answerObserver = new MutationObserver(records => window.answerNoopMutations += records.length);
          window.answerObserver.observe(document.querySelector('#history .answer-text'),
            {childList:true,subtree:true,characterData:true,attributes:true});
        }""")
        with page.expect_response(lambda response: response.request.method=='POST' and response.url.endswith('/heartbeat'),timeout=10000) as heartbeat:
            pass
        heartbeat.value.body()
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        assert page.evaluate('window.answerNoopMutations') == 0
        assert worker.poll() is None and generation.poll() is None
    except Exception:
        print('Actual UI status:',page.locator('#status').inner_text())
        print('Actual UI connection:',page.locator('#answer-connection').inner_text())
        print('Actual UI history:',page.locator('#history').inner_text())
        print('Actual UI early fragments:',page.locator('#early-fragments').inner_text())
        raise
    finally:
        for route in held:
            try:route.abort()
            except Exception:pass
        context.close()


def test_delayed_real_ack_preserves_new_draft_and_does_not_block_other_conversation(real_answer_browser):
    ((browser,mailbox,frontend,_),_,_),generation,generation_log = real_answer_browser
    context=browser.new_context()
    held=[]
    native_pid=None
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'lifecycle-ack@owned.test')
        login(page,'lifecycle-ack@owned.test')
        page.locator('#document-upload input').set_input_files({'name':'ack-budget.txt','mimeType':'text/plain',
                                                              'buffer':b'The annual budget is 100 euros.\n'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        ready(page,'ack-budget.txt')
        page.get_by_role('checkbox',name='ack-budget.txt',exact=True).check()
        native_pid=next(json.loads(line)['pid'] for line in generation_log.read_text().splitlines()
                        if line.startswith('{"event": "native_spawn"'))
        os.kill(native_pid,signal.SIGSTOP)
        first_id=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        first_question='What is the annual budget?'
        def delay_first_ack(route):
            if not held:
                response=route.fetch()
                assert response.status==200
                held.append((route,response))
            else:route.continue_()
        page.route('**/api/conversations/*/answers',delay_first_ack)
        page.locator('#question').fill(first_question)
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#history h3')).to_have_text(first_question)
        page.locator('#question').fill('A new unsent draft after acceptance')
        page.get_by_role('button',name='Новая беседа',exact=True).click()
        expect(page.locator('#conversations li')).to_have_count(2)
        second_id=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        assert second_id!=first_id
        page.locator('#question').fill('The annual budget is 100 euros. Explain that budget.')
        expect(page.get_by_role('button',name='Отправить вопрос',exact=True)).to_be_enabled()
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#history h3')).to_contain_text('Explain that budget')
        neighbor=context.new_page()
        neighbor.goto(frontend)
        login(neighbor,'lifecycle-ack@owned.test')
        neighbor.locator(f'#conversations button[data-conversation="{first_id}"]').click()
        neighbor.get_by_role('checkbox',name='ack-budget.txt',exact=True).check()
        neighbor.locator('#question').fill('Neighbor draft while A is busy')
        expect(neighbor.get_by_role('button',name='Отправить вопрос',exact=True)).to_be_disabled()
        # Exercise the same handler reached by a competing form event before a tab sees busy.
        neighbor.locator('#question-form').evaluate('form => form.requestSubmit()')
        expect(neighbor.locator('#status')).to_contain_text('В этой беседе уже выполняется запрос')
        expect(neighbor.locator('#question')).to_have_value('Neighbor draft while A is busy')
        page.locator(f'#conversations button[data-conversation="{first_id}"]').click()
        expect(page.locator('#question')).to_have_value('A new unsent draft after acceptance')
        page.get_by_role('button',name='Остановить ответ',exact=True).click()
        expect(page.locator('#history')).to_contain_text('Прерван')
        expect(page.locator('#history')).to_contain_text('Прерван: Остановлен пользователем')
        expect(page.locator('#history').get_by_text('Ответ модели',exact=True)).to_be_hidden()
        route,response=held.pop()
        route.fulfill(response=response)
        expect(page.locator('#question')).to_have_value('A new unsent draft after acceptance')
        os.kill(native_pid,signal.SIGCONT)
        native_pid=None
        page.locator(f'#conversations button[data-conversation="{second_id}"]').click()
        expect(page.locator('#history .answer-text')).to_contain_text('100',timeout=30000)
        expect(page.locator('#history h3')).not_to_have_text(first_question)
        assert generation.poll() is None
    except Exception:
        print('Delayed ACK actual status:',page.locator('#status').inner_text())
        print('Delayed ACK actual history:',page.locator('#history').inner_text())
        with psycopg.connect(os.environ['RAG_DATABASE_URL'],autocommit=True) as connection:
            rows=connection.execute("SELECT r.id,r.state,r.reason,b.started FROM requests r JOIN accounts a ON a.id=r.owner_id JOIN graph_bindings b ON b.request_id=r.id WHERE a.email='lifecycle-ack@owned.test' ORDER BY r.created_at,r.id").fetchall()
            print('Actual admitted request states:',rows)
        raise
    finally:
        if native_pid is not None:
            try:os.kill(native_pid,signal.SIGCONT)
            except ProcessLookupError:pass
        for route,_ in held:
            try:route.abort()
            except Exception:pass
        context.close()


def test_actual_app_close_restore_duplicate_and_opener_discard_closed_drafts(real_account_browser,tmp_path):
    browser,mailbox,frontend,_=real_account_browser
    extension=BACKEND/'tests/fixtures/answer_lifecycle/restore_extension'
    context=browser.browser_type.launch_persistent_context(tmp_path/'profile',headless=False,
        ignore_default_args=['--disable-extensions'],
        args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}'])
    try:
        worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
        original=context.new_page()
        register(original,mailbox,frontend,'lifecycle-lifetime@owned.test')
        login(original,'lifecycle-lifetime@owned.test')
        original.goto(frontend+'?lifetime=original')
        expect(original.locator('html')).to_have_attribute('data-ready','true')
        expect(original.locator('#answer-connection')).to_have_text('Соединение установлено.')
        original.locator('#question').fill('Closed original draft')
        original_tab=original.evaluate("JSON.parse(sessionStorage.getItem('rag:tab')).id")
        neighbor=context.new_page()
        neighbor.goto(frontend+'?lifetime=neighbor')
        login(neighbor,'lifecycle-lifetime@owned.test')
        neighbor.locator('#question').fill('Neighbor draft remains')
        url=original.url
        original.close()
        with context.expect_page() as restored_page:
            worker.evaluate("""async url => {
              for (let attempt=0; attempt<50; attempt++) {
                const sessions=await chrome.sessions.getRecentlyClosed();
                const entry=sessions.find(value => value.tab?.url === url);
                if (entry) return await chrome.sessions.restore(entry.tab.sessionId);
                await new Promise(resolve => setTimeout(resolve,100));
              }
              throw new Error('Closed real app tab was not recorded');
            }""",url)
        restored=restored_page.value
        expect(restored.locator('html')).to_have_attribute('data-ready','true')
        expect(restored.locator('#workspace')).to_be_visible()
        expect(restored.locator('#question')).to_have_value('')
        expect(restored.locator('#answer-connection')).to_have_text('Соединение установлено.')
        assert restored.evaluate("JSON.parse(sessionStorage.getItem('rag:tab')).id")!=original_tab
        expect(neighbor.locator('#question')).to_have_value('Neighbor draft remains')
        restored.locator('#question').fill('Restored tab new draft')
        restored_tab=restored.evaluate("JSON.parse(sessionStorage.getItem('rag:tab')).id")
        with context.expect_page() as duplicate_page:
            worker.evaluate("""async url => {
              const tabs=await chrome.tabs.query({});
              return await chrome.tabs.duplicate(tabs.find(value => value.url===url).id);
            }""",restored.url)
        duplicate=duplicate_page.value
        expect(duplicate.locator('html')).to_have_attribute('data-ready','true')
        expect(duplicate.locator('#question')).to_have_value('')
        expect(duplicate.locator('#answer-connection')).to_have_text('Соединение установлено.')
        assert duplicate.evaluate("JSON.parse(sessionStorage.getItem('rag:tab')).id")!=restored_tab
        with context.expect_page() as opened_page:
            restored.evaluate('url => window.open(url)',frontend+'?lifetime=opener')
        opened=opened_page.value
        expect(opened.locator('html')).to_have_attribute('data-ready','true')
        expect(opened.locator('#question')).to_have_value('')
        expect(opened.locator('#answer-connection')).to_have_text('Соединение установлено.')
        assert opened.evaluate("JSON.parse(sessionStorage.getItem('rag:tab')).id")!=restored_tab
        expect(restored.locator('#question')).to_have_value('Restored tab new draft')
        expect(neighbor.locator('#question')).to_have_value('Neighbor draft remains')
        print('Real UI/SMTP account, actual Chrome close/restore/duplicate/opener; server-issued independent tab proofs; no closed draft recovery.')
    finally:
        context.close()


def test_actual_browser_restart_does_not_restore_closed_conversation_drafts(real_account_browser,tmp_path):
    browser,mailbox,frontend,_=real_account_browser
    profile=tmp_path/'restart-profile'
    context=browser.browser_type.launch_persistent_context(profile,headless=False,args=['--restore-last-session'])
    first_id=second_id=None
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'lifecycle-restart@owned.test')
        login(page,'lifecycle-restart@owned.test')
        page.goto(frontend+'?lifetime=restart')
        expect(page.locator('html')).to_have_attribute('data-ready','true')
        first_id=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        page.locator('#question').fill('Closed browser first conversation')
        page.get_by_role('button',name='Новая беседа',exact=True).click()
        expect(page.locator('#conversations li')).to_have_count(2)
        second_id=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        page.locator('#question').fill('Closed browser second conversation')
    finally:
        context.close()
    restored=browser.browser_type.launch_persistent_context(profile,headless=False,args=['--restore-last-session'])
    try:
        page=next(page for page in restored.pages if 'lifetime=restart' in page.url)
        expect(page.locator('html')).to_have_attribute('data-ready','true')
        assert page.evaluate("!Object.keys(sessionStorage).some(key=>key.startsWith('rag:draft:'))")
        if page.locator('#authentication').is_visible():login(page,'lifecycle-restart@owned.test')
        for identifier in (first_id,second_id):
            page.locator(f'#conversations button[data-conversation="{identifier}"]').click()
            expect(page.locator('#question')).to_have_value('')
        print('Actual persistent Chromium restart restored the real app URL; neither closed conversation draft returned.')
    finally:
        restored.close()


def test_ready_source_never_auto_submits_html_stays_text_and_owner_change_clears_drafts(real_document_browser):
    (browser,mailbox,frontend,_),worker,_=real_document_browser
    context=browser.new_context(viewport={'width':375,'height':812})
    paused=False
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'lifecycle-ready@owned.test')
        login(page,'lifecycle-ready@owned.test')
        os.kill(worker.pid,signal.SIGSTOP);paused=True
        name='<img src=x onerror=window.nameInjected=true>.txt'
        text='<script>window.textInjected=true</script>\nThe annual budget is 100 euros.'
        page.locator('#document-upload input').set_input_files({'name':name,'mimeType':'text/plain','buffer':text.encode()})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        expect(page.locator('#status')).to_have_text('Файлы приняты. Обработка выполняется в фоне.')
        page.locator('#question-sources input').check()
        page.locator('#question').fill('Wait for my selected document')
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#status')).to_contain_text('Нет готовых источников')
        os.kill(worker.pid,signal.SIGCONT);paused=False
        item=ready(page,name)
        expect(page.locator('#question')).to_have_value('Wait for my selected document')
        expect(page.locator('#history')).to_have_text('В этой беседе пока нет сообщений.')
        item.get_by_role('button',name='Открыть документ',exact=True).click()
        expect(page.locator('#document-correction textarea')).to_have_value(text)
        assert page.evaluate('window.nameInjected') is None and page.evaluate('window.textInjected') is None
        page.locator('#question').focus()
        page.keyboard.press('Tab')
        assert page.get_by_role('button',name='Отправить вопрос',exact=True).evaluate('node => node === document.activeElement')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_role('button',name='Выйти',exact=True).click()
        register(page,mailbox,frontend,'lifecycle-other-owner@owned.test')
        login(page,'lifecycle-other-owner@owned.test')
        expect(page.locator('#question')).to_have_value('')
        expect(page.locator('#documents li')).to_have_count(0)
        assert page.evaluate("!Object.values(sessionStorage).some(value=>value.includes('Wait for my selected document'))")
        print('Real ready publication caused no auto-submit; filename/source HTML stayed inert; keyboard/mobile checked; new owner has no previous draft/document.')
    finally:
        if paused:
            try:os.kill(worker.pid,signal.SIGCONT)
            except ProcessLookupError:pass
        context.close()


def test_actual_print_only_pdf_limitations_reach_answer_passport(real_answer_browser):
    ((browser,mailbox,frontend,_),worker,_),generation,_=real_answer_browser
    contexts=[browser.new_context() for _ in range(2)]
    try:
        operator,user=[context.new_page() for context in contexts]
        invitation=subprocess.run([sys.executable,'-m','app.accounts','--email','lifecycle-pdf-operator@owned.test'],
            cwd=BACKEND,env=os.environ.copy(),check=True,capture_output=True,text=True).stdout.strip()
        register(operator,mailbox,frontend,'lifecycle-pdf-operator@owned.test',invitation)
        login(operator,'lifecycle-pdf-operator@owned.test')
        register(user,mailbox,frontend,'lifecycle-pdf@owned.test')
        login(user,'lifecycle-pdf@owned.test')
        operator.reload()
        card=operator.locator('article').filter(has=operator.locator('form[data-account="lifecycle-pdf@owned.test"]'))
        card.locator('summary').click()
        policy=card.locator('form[data-policy]')
        expect(policy.locator('[name=handwriting]')).to_be_checked()
        policy.locator('[name=handwriting]').uncheck()
        policy.get_by_role('button',name='Сохранить ограничения документов').click()
        expect(operator.locator('#status')).to_have_text('Ограничения документов сохранены.')
        path=BACKEND.parent/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-ocr-proof/mixed-real-title-fixture-v1.pdf'
        user.locator('#document-upload input').set_input_files(str(path))
        user.get_by_role('button',name='Загрузить документы',exact=True).click()
        expect(user.locator('#documents')).to_contain_text('Для вашей учётной записи OCR рукописей не разрешён')
        user.get_by_role('button',name='Загрузить только печатный текст',exact=True).click()
        ready(user,path.name,timeout=300)
        user.get_by_role('checkbox',name=path.name,exact=True).check()
        user.locator('#question').fill('What is the annual budget?')
        user.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(user.locator('#history .answer-text')).to_contain_text('100',timeout=120000)
        user.locator('#history .answer-passport summary').click()
        expect(user.locator('#history .answer-passport')).to_contain_text(path.name)
        expect(user.locator('#history .answer-passport')).to_contain_text('рукописные участки пропущены')
        expect(user.locator('#history .answer-passport')).not_to_contain_text('Dreams')
        expect(user.locator('#history .answer-passport')).not_to_contain_text('Hughes')
        assert worker.poll() is None and generation.poll() is None
        print('Actual UI/SMTP/operator policy/explicit PDF choice/native OCR/E5/Qwen answer; print-only source limitation carried in passport.')
    finally:
        for context in contexts:context.close()


def test_old_real_snapshot_cannot_erase_new_request_or_current_fragments(real_answer_browser):
    ((browser,mailbox,frontend,_),_,_),generation,generation_log=real_answer_browser
    context=browser.new_context()
    held=[]
    native_pid=None
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'lifecycle-snapshot@owned.test')
        login(page,'lifecycle-snapshot@owned.test')
        page.locator('#document-upload input').set_input_files({'name':'snapshot-budget.txt','mimeType':'text/plain',
                                                              'buffer':b'The annual budget is 100 euros.\n'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        ready(page,'snapshot-budget.txt')
        page.get_by_role('checkbox',name='snapshot-budget.txt',exact=True).check()
        native_pid=next(json.loads(line)['pid'] for line in generation_log.read_text().splitlines()
                        if line.startswith('{"event": "native_spawn"'))
        os.kill(native_pid,signal.SIGSTOP)
        def hold_old_get(route):
            response=route.fetch()
            assert response.json()['requests']==[]
            held.append((route,response))
        page.route('**/api/conversations/*',hold_old_get)
        page.get_by_role('button',name='Открыть беседу',exact=True).click()
        page.locator('#question').fill('What is the annual budget?')
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#history h3')).to_have_text('What is the annual budget?')
        page.locator('#question').fill('New draft after the old read started')
        route,response=held.pop()
        route.fulfill(response=response)
        expect(page.locator('#history h3')).to_have_text('What is the annual budget?')
        expect(page.get_by_role('button',name='Отправить вопрос',exact=True)).to_be_disabled()
        expect(page.locator('#question')).to_have_value('New draft after the old read started')
        page.unroute('**/api/conversations/*',hold_old_get)
        os.kill(native_pid,signal.SIGCONT);native_pid=None
        expect(page.locator('#history .answer-text')).to_contain_text('100',timeout=30000)
        page.get_by_role('button',name='Открыть беседу',exact=True).click()
        expect(page.locator('#early-fragments blockquote')).to_contain_text('100 euros')
        assert generation.poll() is None
    finally:
        if native_pid is not None:
            try:os.kill(native_pid,signal.SIGCONT)
            except ProcessLookupError:pass
        for route,_ in held:
            try:route.abort()
            except Exception:pass
        context.close()
