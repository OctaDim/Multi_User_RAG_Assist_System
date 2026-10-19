from playwright.sync_api import expect

from .test_accounts import real_account_browser, register, login, api_wait_ms
from .test_answer_lifecycle import real_answer_browser
from .test_documents import real_document_browser


def test_variant_a_positions_all_controls_and_keeps_new_chats_local(real_account_browser,tmp_path):
    browser,mailbox,frontend,api_url=real_account_browser
    context=browser.new_context(viewport={'width':1440,'height':1000})
    try:
        page=context.new_page();register(page,mailbox,frontend,'variant-a-layout@owned.test');login(page,'variant-a-layout@owned.test')
        expect(page.locator('#workspace-sidebar')).to_be_visible()
        for selector in ['#nav-workspace','#nav-library','#new-conversation','#conversations']:
            assert page.locator(selector).evaluate("el=>Boolean(el.closest('#workspace-sidebar'))")
        sidebar=page.locator('#workspace-sidebar').bounding_box();chat=page.locator('#chat').bounding_box()
        assert sidebar['x']+sidebar['width']<=chat['x']
        heading=page.locator('#chat .area-heading').bounding_box();sources=page.locator('#source-selection').bounding_box()
        history=page.locator('#history').bounding_box();composer=page.locator('#question-form').bounding_box()
        assert heading['y']+heading['height']<=sources['y']+1
        assert sources['y']+sources['height']<=history['y']+1
        assert history['y']+history['height']<=composer['y']+1
        page.locator('#new-conversation').click();page.locator('#new-conversation').click()
        expect(page.locator('#conversations li')).to_have_count(0)
        me=page.evaluate("async url=>await(await fetch(url+'/api/accounts/me',{headers:{Authorization:'Bearer '+sessionStorage.getItem('rag:credential')}})).json()",api_url)
        assert me['conversations']==[]
        page.locator('#question').fill('Remember this draft')
        expect(page.locator('#send-question')).to_be_enabled(timeout=api_wait_ms(page))
        page.locator('#nav-library').click();page.locator('#nav-workspace').click()
        expect(page.locator('#question')).to_have_value('Remember this draft')
        page.locator('#open-evidence').click()
        evidence=page.locator('#evidence').bounding_box();chat=page.locator('#chat').bounding_box()
        assert chat['x']+chat['width']<=evidence['x']
        for width in (1440,1024,768,375):
            page.set_viewport_size({'width':width,'height':900})
            if width<960:
                expect(page.locator('#sidebar-toggle')).to_be_visible()
                page.locator('#sidebar-toggle').click();expect(page.locator('#workspace-sidebar')).to_be_visible()
                page.keyboard.press('Shift+Tab');expect(page.locator('.conversation-picker summary')).to_be_focused()
                page.keyboard.press('Tab');expect(page.locator('#close-sidebar')).to_be_focused()
                page.screenshot(path=str(tmp_path/f'variant-a-menu-{width}.png'),full_page=True)
                page.keyboard.press('Escape');expect(page.locator('#sidebar-toggle')).to_be_focused()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(tmp_path/f'variant-a-{width}.png'),full_page=True)
        page.set_viewport_size({'width':375,'height':812})
        page.locator('#close-evidence').click()
        page.locator('#conversation-title').evaluate("el=>el.textContent='A very long conversation title that should fit beside the evidence button without covering it'")
        page.locator('#active-answer-status').evaluate("el=>{el.hidden=false;el.querySelector('p').textContent='Ответ: Завершён';}")
        send=page.locator('#send-question').bounding_box()
        assert send['y']+send['height']<=812
        assert page.locator('#history').bounding_box()['height']>=180
    finally:context.close()


def test_actual_llm_answers_without_documents_and_preserves_chat_history(real_answer_browser,tmp_path):
    ((browser,mailbox,frontend,_),_,_),_,_=real_answer_browser
    context=browser.new_context(viewport={"width":1440,"height":900})
    try:
        page=context.new_page();register(page,mailbox,frontend,'variant-a-general@owned.test');login(page,'variant-a-general@owned.test')
        page.locator('#question').fill('Remember that my favorite color is azure. Reply briefly in English.')
        expect(page.locator('#send-question')).to_be_enabled(timeout=api_wait_ms(page))
        page.locator('#send-question').click()
        expect(page.locator('#history article')).to_contain_text('Завершён',timeout=120000)
        expect(page.locator('#history .answer-text')).not_to_have_text('')
        expect(page.locator('#conversations li')).to_have_count(1)
        strip=page.locator('#active-answer-status').bounding_box()
        composer=page.locator('#question-form').bounding_box()
        history=page.locator('#history').bounding_box()
        assert history['y']+history['height']<=strip['y']+1
        assert strip['y']+strip['height']<=composer['y']+1
        expect(page.locator('#conversation-title')).to_contain_text('favorite color')
        page.screenshot(path=str(tmp_path/'variant-a-populated-1440.png'),full_page=True)
        page.locator('#question').fill('What is my favorite color? Reply with the color only.')
        page.locator('#send-question').click()
        expect(page.locator('#history article')).to_have_count(2,timeout=30000)
        expect(page.locator('#history article').last).to_contain_text('Завершён',timeout=120000)
        expect(page.locator('#check-question')).to_be_hidden()
        expect(page.locator('#history .answer-text').last).to_contain_text('azure',ignore_case=True)
        page.locator('#history article').last.get_by_role('button',name='Показать основания').click()
        expect(page.locator('#answer-evidence')).to_contain_text('Без документов')
        expect(page.locator('#answer-evidence .cited-quote')).to_have_count(0)
        page.screenshot(path=str(tmp_path/'variant-a-evidence-1440.png'),full_page=True)
        page.set_viewport_size({'width':375,'height':812})
        page.locator('#close-evidence').click()
        expect(page.locator('#question-form')).to_be_visible()
        send=page.locator('#send-question').bounding_box()
        assert send['y']+send['height']<=812
        assert page.locator('#history').bounding_box()['height']>=180
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(tmp_path/'variant-a-populated-375.png'),full_page=True)
    finally:context.close()


def test_lost_first_creation_response_retries_same_conversation_and_question(real_account_browser):
    browser,mailbox,frontend,api=real_account_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'variant-a-create-retry@owned.test');login(page,'variant-a-create-retry@owned.test')
        attempts=[]
        def lose_first_response(route):
            response=route.fetch()
            assert response.status==201
            attempts.append(route.request.post_data_json['id'])
            if len(attempts)==1:route.fulfill(status=503,json={'error':'unavailable'})
            else:route.fulfill(response=response)
        page.route(api+'/api/conversations',lose_first_response)
        page.locator('#question').fill('The originally submitted question')
        page.locator('#send-question').click()
        expect(page.locator('#check-question')).to_be_visible()
        page.locator('#question').fill('A new unsent draft')
        original=page.locator('#chat').get_attribute('data-conversation')
        page.locator('#new-conversation').click()
        expect(page.locator('#chat')).not_to_have_attribute('data-conversation',original)
        page.reload();expect(page.locator('html')).to_have_attribute('data-ready','true')
        page.locator(f'#conversations button[data-conversation="{original}"]').click()
        expect(page.locator('#question')).to_have_value('A new unsent draft')
        expect(page.locator('#check-question')).to_be_visible()
        page.locator('#check-question').click()
        expect(page.locator('#history h3')).to_have_text('The originally submitted question',timeout=api_wait_ms(page))
        expect(page.locator('#question')).to_have_value('A new unsent draft')
        expect(page.locator('#conversations li')).to_have_count(1)
        assert 1<=len(attempts)<=2 and set(attempts)=={original}
        snapshot=page.evaluate("async api=>await(await fetch(api+'/api/accounts/me',{headers:{Authorization:'Bearer '+sessionStorage.getItem('rag:credential')}})).json()",api)
        assert len(snapshot['conversations'])==1
        page.get_by_role('button',name='Остановить ответ',exact=True).click()
        expect(page.locator('#active-answer-state')).to_contain_text('Прерван')
    finally:context.close()


def test_late_answer_ack_does_not_restore_previous_account_sidebar(real_account_browser):
    browser,mailbox,frontend,api=real_account_browser
    context=browser.new_context();held=[]
    try:
        other=context.new_page();register(other,mailbox,frontend,'variant-a-next@owned.test');other.close()
        page=context.new_page();register(page,mailbox,frontend,'variant-a-previous@owned.test');login(page,'variant-a-previous@owned.test')
        def hold_ack(route):
            response=route.fetch();assert response.status==200;held.append((route,response))
        page.route(api+'/api/conversations/*/answers',hold_ack)
        page.locator('#question').fill('Private question of the previous account')
        page.locator('#send-question').click()
        expect(page.locator('#conversations li')).to_have_count(1,timeout=api_wait_ms(page))
        page.locator('#logout').click()
        login(page,'variant-a-next@owned.test')
        expect(page.locator('#conversations li')).to_have_count(0)
        route,response=held.pop()
        with page.expect_request_finished(lambda request:request.url.endswith('/answers')):
            route.fulfill(response=response)
        page.wait_for_timeout(100)
        expect(page.locator('#conversations li')).to_have_count(0)
        expect(page.locator('#conversation-title')).to_have_text('Новая беседа')
        expect(page.locator('#workspace')).not_to_contain_text('Private question of the previous account')
    finally:
        for route,_ in held:
            try:route.abort()
            except Exception:pass
        context.close()
