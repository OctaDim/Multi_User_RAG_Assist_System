"""Conversation workspace proofs with actual accounts, source publication and model.

Network controls below cover temporary failures; they do not replace the real flow.
"""
import json
import os
import signal
import time

from playwright.sync_api import expect

from .test_accounts import real_account_browser, register, login, open_conversations, open_sources
from .test_documents import real_document_browser, ready
from .test_answer_lifecycle import real_answer_browser


def upload(page, name, text):
    page.locator('[data-area=library]').click()
    page.locator('#document-upload input').set_input_files(
        {'name':name, 'mimeType':'text/plain', 'buffer':text.encode()})
    page.get_by_role('button',name='Загрузить документы',exact=True).click()
    ready(page,name)
    page.locator('[data-area=chat]').click()
    if not page.locator('#source-selection').evaluate('(details)=>details.open'):
        page.locator('#source-selection summary').click()


def test_submission_and_creation_errors_stay_with_their_conversation(real_document_browser,tmp_path):
    (browser,mailbox,frontend,api),_,_=real_document_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'workspace-local-errors@owned.test');login(page,'workspace-local-errors@owned.test')
        upload(page,'local-errors.txt','The annual budget is 100 euros.')
        first=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        question='Keep this question after a refused admission'
        page.route(api+'/api/conversations/*/answers',lambda route:route.fulfill(status=503,json={'error':'coordinator_unavailable'}))
        page.locator('#question').fill(question);page.locator('#send-question').click()
        expect(page.locator('#question-feedback')).to_contain_text('Сервис ответов сейчас недоступен')
        expect(page.locator('#question')).to_have_value(question)
        expect(page.locator('#history article')).to_have_count(0)
        page.route(api+'/api/conversations',lambda route:route.fulfill(status=503,json={'error':'unavailable'}))
        page.locator('#new-conversation').click()
        expect(page.locator('#conversation-feedback')).to_contain_text('Не удалось создать беседу')
        expect(page.locator('#new-conversation')).to_be_enabled()
        page.unroute(api+'/api/conversations')
        page.locator('#new-conversation').click()
        expect(page.locator('#conversations button[aria-current=true]')).not_to_have_attribute('data-conversation',first)
        expect(page.locator('#question-feedback')).to_be_hidden()
        expect(page.locator('#conversation-feedback')).to_be_hidden()
        page.route(api+'/api/conversations/'+first,lambda route:route.fulfill(status=503,json={'error':'unavailable'}))
        open_conversations(page)
        page.locator(f'#conversations button[data-conversation="{first}"]').click()
        expect(page.locator('#conversation-feedback')).to_contain_text('Не удалось открыть беседу')
        expect(page.locator('#question')).to_have_value(question)
        page.unroute(api+'/api/conversations/'+first)
        open_conversations(page)
        page.locator(f'#conversations button[data-conversation="{first}"]').click()
        expect(page.locator('#conversation-feedback')).to_be_hidden()
        expect(page.locator('#question-feedback')).to_contain_text('Сервис ответов сейчас недоступен')
        expect(page.locator('#question')).to_have_value(question)
        page.set_viewport_size({'width':375,'height':812});page.locator('#question').focus()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        expect(page.locator('#send-question')).to_be_visible()
        page.screenshot(path=str(tmp_path/'question-error-375.png'),full_page=True)
        page.locator('#question').fill('A revised question clears the previous error')
        expect(page.locator('#question-feedback')).to_be_hidden()
        page.locator('#logout').click()
        expect(page.locator('#question-feedback')).to_have_text('')
        expect(page.locator('#conversation-feedback')).to_have_text('')
    finally:context.close()


def test_scopes_survive_conversation_reload_and_missing_selection_never_broadens(real_document_browser):
    (browser,mailbox,frontend,_),_,_=real_document_browser
    context=browser.new_context()
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'workspace-scopes@owned.test')
        login(page,'workspace-scopes@owned.test')
        upload(page,'first-scope.txt','The annual budget is 100 euros.\n')
        upload(page,'second-scope.txt','The delivery address is Green Street.\n')
        first=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        open_sources(page)
        source=page.get_by_role('checkbox',name='first-scope.txt',exact=True)
        source.check()
        selected=source.input_value()
        page.locator('#question').fill('First conversation draft')
        page.get_by_role('button',name='Новая беседа',exact=True).click()
        expect(page.locator('#conversations button[aria-current=true]')).not_to_have_attribute('data-conversation',first)
        second=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        open_sources(page)
        expect(page.get_by_role('checkbox',name='first-scope.txt',exact=True)).not_to_be_checked()
        open_sources(page)
        page.get_by_role('checkbox',name='second-scope.txt',exact=True).check()
        page.locator('#question').fill('Second conversation draft')
        open_conversations(page)
        page.locator(f'#conversations button[data-conversation="{first}"]').click()
        expect(page.locator('#question')).to_have_value('First conversation draft')
        open_sources(page)
        expect(page.get_by_role('checkbox',name='first-scope.txt',exact=True)).to_be_checked()
        open_sources(page)
        expect(page.get_by_role('checkbox',name='second-scope.txt',exact=True)).not_to_be_checked()
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-ready','true')
        expect(page.locator('#question')).to_have_value('First conversation draft')
        open_sources(page)
        expect(page.get_by_role('checkbox',name='first-scope.txt',exact=True)).to_be_checked()

        # The source disappears from an actual library read while another ready source remains.
        def hide_selected(route):
            response=route.fetch()
            body=response.json()
            body['documents']=[row for row in body['documents'] if row['id']!=selected]
            route.fulfill(response=response,json=body)
        page.route('**/api/documents',hide_selected)
        page.locator('[data-area=library]').click()
        page.get_by_role('button',name='Обновить статусы документов',exact=True).click()
        page.locator('[data-area=chat]').click()
        unavailable=page.locator(f'#question-sources input[value="{selected}"]')
        expect(unavailable).to_be_checked()
        expect(page.locator('#question-sources')).to_contain_text('недоступен')
        expect(page.locator('#scope-description')).to_contain_text('Выбрано источников: 1')
        expect(page.locator('#scope-description')).to_contain_text('Готово для поиска: 0')
        expect(page.locator('#send-question')).to_be_disabled()
        expect(page.locator('#history')).to_have_text('В этой беседе пока нет сообщений.')
        open_sources(page)
        unavailable.uncheck()
        expect(page.locator('#scope-description')).to_contain_text('Все готовые документы')
        expect(page.locator('#send-question')).to_be_enabled()
        expect(page.locator('#question')).to_have_value('First conversation draft')
        open_conversations(page)
        page.locator(f'#conversations button[data-conversation="{second}"]').click()
        expect(page.locator('#question')).to_have_value('Second conversation draft')
        open_sources(page)
        expect(page.get_by_role('checkbox',name='second-scope.txt',exact=True)).to_be_checked()
    finally:
        context.close()


def test_stop_503_retries_and_terminal_event_wins_over_late_stop_response(real_answer_browser):
    ((browser,mailbox,frontend,_),_,_),_,generation_log=real_answer_browser
    context=browser.new_context()
    native_pid=None
    held=[]
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'workspace-stop@owned.test')
        login(page,'workspace-stop@owned.test')
        upload(page,'stop-budget.txt','The annual budget is 100 euros.\n')
        native_pid=next(json.loads(line)['pid'] for line in generation_log.read_text().splitlines()
                        if line.startswith('{"event": "native_spawn"'))
        os.kill(native_pid,signal.SIGSTOP)
        page.locator('#question').fill('What is the annual budget?')
        page.locator('#send-question').click()
        stop=page.get_by_role('button',name='Остановить ответ',exact=True,include_hidden=True)
        expect(stop).to_be_visible(timeout=30000)
        attempts=[]
        def controlled_stop(route):
            attempts.append(route.request)
            if len(attempts)==1:
                route.fulfill(status=503,json={'error':'coordinator_unavailable'})
            else:
                response=route.fetch()
                assert response.status==200
                held.append((route,response))
        page.route('**/api/answers/*/stop',controlled_stop)
        stop.click()
        expect(page.locator('#history .action-feedback')).to_contain_text('Повторите попытку')
        expect(stop).to_be_enabled()
        stop.click()
        expect(page.locator('#history')).to_contain_text('Прерван: Остановлен пользователем')
        expect(stop).to_be_hidden()
        route,response=held.pop()
        route.fulfill(response=response)
        expect(stop).to_be_hidden()
        expect(stop).to_be_disabled()
        assert len(attempts)==2
        expect(page.locator('#history article')).to_have_count(1)
    finally:
        if native_pid is not None:
            try:os.kill(native_pid,signal.SIGCONT)
            except ProcessLookupError:pass
        for route,_ in held:
            try:route.abort()
            except Exception:pass
        context.close()


def test_selected_old_answer_evidence_and_citation_survive_navigation(real_answer_browser,tmp_path):
    ((browser,mailbox,frontend,_),_,_),_,_=real_answer_browser
    context=browser.new_context(viewport={'width':375,'height':812})
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'workspace-evidence@owned.test')
        login(page,'workspace-evidence@owned.test')
        upload(page,'budget-evidence.txt','The annual budget is 100 euros.\n')
        upload(page,'address-evidence.txt','The delivery address is Green Street.\n')
        conversation=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        open_sources(page)
        page.get_by_role('checkbox',name='budget-evidence.txt',exact=True).check()
        page.locator('#question').fill('What is the annual budget?')
        page.locator('#question').focus()
        page.locator('#question-form').evaluate('form => form.requestSubmit()')
        expect(page.locator('#grounds-indicator')).to_be_visible(timeout=30000)
        expect(page.locator('#question')).to_be_focused()
        first=page.locator('#history article').first
        expect(first).to_contain_text('Завершён',timeout=30000)
        page.locator('[data-area=evidence]').click()
        expect(page.locator('#grounds-indicator')).to_be_hidden()
        expect(page.locator('#early-fragments')).to_contain_text('100 euros')
        page.locator('[data-area=chat]').click()
        page.locator('#source-selection summary').click()
        open_sources(page)
        page.get_by_role('checkbox',name='budget-evidence.txt',exact=True).uncheck()
        open_sources(page)
        page.get_by_role('checkbox',name='address-evidence.txt',exact=True).check()
        page.locator('#question').fill('What is the delivery address?')
        page.locator('#send-question').click()
        second=page.locator('#history article').nth(1)
        expect(second).to_contain_text('Завершён',timeout=30000)
        page.locator('[data-area=evidence]').click()
        expect(page.locator('#early-fragments')).to_contain_text('Green Street')
        expect(page.locator('#early-fragments')).not_to_contain_text('100 euros')
        page.locator('[data-area=chat]').click()
        first.get_by_role('button',name='Показать основания',exact=True).click()
        expect(page.locator('#early-fragments')).to_contain_text('100 euros')
        expect(page.locator('#early-fragments')).not_to_contain_text('Green Street')
        page.locator('[data-area=chat]').click()
        first.locator('.answer-text a').first.click()
        expect(page.locator('#answer-evidence .cited-quote').first).to_be_focused()
        expect(page.locator('#answer-evidence .cited-quote').first).to_contain_text('100 euros')
        page.locator('[data-area=chat]').click()
        page.locator('#question').fill('Preserve my question while looking at evidence')
        page.get_by_role('button',name='Новая беседа',exact=True).click()
        if not page.locator('.conversation-picker').evaluate('(details)=>details.open'):
            page.locator('.conversation-picker summary').click()
        open_conversations(page)
        page.locator(f'#conversations button[data-conversation="{conversation}"]').click()
        expect(page.locator('#question')).to_have_value('Preserve my question while looking at evidence')
        page.locator('[data-area=evidence]').click()
        expect(page.locator('#early-fragments')).to_contain_text('100 euros')
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-ready','true')
        page.locator('[data-area=evidence]').click()
        expect(page.locator('#early-fragments')).to_contain_text('100 euros')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        for width in (1440,768,375):
            page.set_viewport_size({'width':width,'height':1000})
            page.locator('#close-evidence').click()
            page.screenshot(path=str(tmp_path/f'chat-{width}.png'),full_page=True)
            if width==375:
                page.set_viewport_size({'width':375,'height':812})
                assert page.locator('#history').bounding_box()['height'] >= 200
                page.screenshot(path=str(tmp_path/'chat-375-812.png'),full_page=True)
                page.set_viewport_size({'width':375,'height':1000})
            page.locator('[data-area=evidence]').click()
            page.screenshot(path=str(tmp_path/f'evidence-{width}.png'),full_page=True)
            page.locator('[data-area=library]').click()
            page.screenshot(path=str(tmp_path/f'library-{width}.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('[data-area=chat]').click()
            page.locator('[data-area=evidence]').click()
    finally:
        context.close()


def test_empty_selection_searches_all_ready_owned_sources(real_answer_browser):
    ((browser,mailbox,frontend,api_url),_,_),_,_=real_answer_browser
    contexts=[browser.new_context() for _ in range(2)]
    try:
        page,foreign=[context.new_page() for context in contexts]
        register(page,mailbox,frontend,'all-ready-owner@owned.test');login(page,'all-ready-owner@owned.test')
        upload(page,'all-budget.txt','The annual budget is 100 euros.')
        upload(page,'all-address.txt','The delivery address is Green Street.')
        register(foreign,mailbox,frontend,'all-foreign-owner@owned.test');login(foreign,'all-foreign-owner@owned.test')
        upload(foreign,'foreign-private.txt','The annual budget is 400 euros and the address is Other Street.')
        page.locator('[data-area=library]').click()
        page.locator('#document-upload input').set_input_files({'name':'unready-invalid.txt','mimeType':'text/plain','buffer':b'\xff'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click()
        deadline=time.monotonic()+30
        bad=page.locator('#documents li').filter(has=page.get_by_text('unready-invalid.txt',exact=True))
        while 'Обработка неуспешна' not in bad.inner_text():
            assert time.monotonic()<deadline
            page.locator('#refresh-documents').click();page.wait_for_timeout(100)
        page.locator('[data-area=chat]').click()
        expect(page.locator('#question-sources input:checked')).to_have_count(0)
        expect(page.locator('#scope-description')).to_contain_text('Все готовые документы моей библиотеки: 2')
        page.locator('#question').fill('What is the annual budget and delivery address? Cite the supplied sources.')
        page.locator('#send-question').click()
        expect(page.locator('#history article')).to_contain_text('Завершён',timeout=120000)
        page.get_by_role('button',name='Показать основания',exact=True).click()
        expect(page.locator('#early-fragments')).to_contain_text('100 euros')
        expect(page.locator('#early-fragments')).to_contain_text('Green Street')
        expect(page.locator('#early-fragments')).not_to_contain_text('400 euros')
        expect(page.locator('#answer-evidence')).to_contain_text('все готовые документы моей библиотеки на момент отправки')
        expect(page.locator('#answer-evidence')).not_to_contain_text('foreign-private.txt')
        result=page.evaluate('''async api => {
            const id=sessionStorage.getItem('rag:conversation');
            return await (await fetch(api+'/api/conversations/'+id,{headers:{Authorization:'Bearer '+sessionStorage.getItem('rag:credential')}})).json();
        }''',api_url)
        request=result['requests'][0];passport=request['passport']
        assert passport['scope_mode']=='all' and passport['selected_document_ids']==[]
        assert {source['name'] for source in passport['available']}=={'all-budget.txt','all-address.txt'}
        assert len(request['scope'])==2
        assert {source['document_id'] for source in passport['passed']}==set(request['scope'])
    finally:
        for context in contexts:context.close()
