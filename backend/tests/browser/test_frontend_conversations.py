"""Conversation workspace proofs with actual accounts, source publication and model.

Network controls below cover temporary failures; they do not replace the real flow.
"""
import json
import os
import signal

from playwright.sync_api import expect

from .test_accounts import real_account_browser, register, login
from .test_documents import real_document_browser, ready
from .test_answer_lifecycle import real_answer_browser


def upload(page, name, text):
    page.locator('[data-area=library]').click()
    page.locator('#document-upload input').set_input_files(
        {'name':name, 'mimeType':'text/plain', 'buffer':text.encode()})
    page.get_by_role('button',name='Загрузить документы',exact=True).click()
    ready(page,name)
    page.locator('[data-area=chat]').click()


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
        source=page.get_by_role('checkbox',name='first-scope.txt',exact=True)
        source.check()
        selected=source.input_value()
        page.locator('#question').fill('First conversation draft')
        page.get_by_role('button',name='Новая беседа',exact=True).click()
        expect(page.locator('#conversations button[aria-current=true]')).not_to_have_attribute('data-conversation',first)
        second=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
        expect(page.get_by_role('checkbox',name='first-scope.txt',exact=True)).not_to_be_checked()
        page.get_by_role('checkbox',name='second-scope.txt',exact=True).check()
        page.locator('#question').fill('Second conversation draft')
        page.locator(f'#conversations button[data-conversation="{first}"]').click()
        expect(page.locator('#question')).to_have_value('First conversation draft')
        expect(page.get_by_role('checkbox',name='first-scope.txt',exact=True)).to_be_checked()
        expect(page.get_by_role('checkbox',name='second-scope.txt',exact=True)).not_to_be_checked()
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-ready','true')
        expect(page.locator('#question')).to_have_value('First conversation draft')
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
        unavailable.uncheck()
        expect(page.locator('#scope-description')).to_contain_text('Все готовые документы')
        expect(page.locator('#send-question')).to_be_enabled()
        expect(page.locator('#question')).to_have_value('First conversation draft')
        page.locator(f'#conversations button[data-conversation="{second}"]').click()
        expect(page.locator('#question')).to_have_value('Second conversation draft')
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


def test_selected_old_answer_evidence_and_citation_survive_navigation(real_answer_browser):
    ((browser,mailbox,frontend,_),_,_),_,_=real_answer_browser
    context=browser.new_context(viewport={'width':375,'height':812})
    try:
        page=context.new_page()
        register(page,mailbox,frontend,'workspace-evidence@owned.test')
        login(page,'workspace-evidence@owned.test')
        upload(page,'budget-evidence.txt','The annual budget is 100 euros.\n')
        upload(page,'address-evidence.txt','The delivery address is Green Street.\n')
        conversation=page.locator('#conversations button[aria-current=true]').get_attribute('data-conversation')
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
        page.get_by_role('checkbox',name='budget-evidence.txt',exact=True).uncheck()
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
        page.locator(f'#conversations button[data-conversation="{conversation}"]').click()
        expect(page.locator('#question')).to_have_value('Preserve my question while looking at evidence')
        page.locator('[data-area=evidence]').click()
        expect(page.locator('#early-fragments')).to_contain_text('100 euros')
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-ready','true')
        page.locator('[data-area=evidence]').click()
        expect(page.locator('#early-fragments')).to_contain_text('100 euros')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        context.close()
