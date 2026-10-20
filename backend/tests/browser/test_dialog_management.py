from playwright.sync_api import expect
from .test_accounts import real_account_browser,register,login,navigate,api_wait_ms
from .test_answer_lifecycle import start_and_stop


def test_file_queue_is_russian_removable_and_only_kept_files_are_uploaded(real_account_browser,tmp_path):
    browser,mailbox,frontend,api=real_account_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'dialog-files@owned.test');login(page,'dialog-files@owned.test')
        expect(page.locator('#new-conversation')).to_contain_text('Новый диалог')
        navigate(page,'library');expect(page.locator('#choose-files')).to_have_text('Выбрать файлы')
        expect(page.locator('#file-selection-status')).to_have_text('Файлы не выбраны.')
        page.locator('#document-files').set_input_files([{'name':'keep.txt','mimeType':'text/plain','buffer':b'Keep this document'},{'name':'remove.txt','mimeType':'text/plain','buffer':b'Remove this document'}])
        expect(page.locator('#selected-files li')).to_have_count(2)
        for width in (1440,768,375):
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(tmp_path/'dialog-file-queue-375.png'))
        page.get_by_role('button',name='Убрать файл remove.txt',exact=True).click()
        expect(page.locator('#selected-files li')).to_have_count(1)
        with page.expect_request(lambda r:r.method=='POST' and r.url.endswith('/documents/uploads')) as pending:
            page.locator('#upload-documents').click()
        assert [row['name'] for row in pending.value.post_data_json['files']]==['keep.txt']
        expect(page.locator('#documents')).to_contain_text('keep.txt',timeout=api_wait_ms(page))
        expect(page.locator('#documents')).not_to_contain_text('remove.txt')
        expect(page.locator('#selected-files li')).to_have_count(0)
        expect(page.locator('#file-selection-status')).to_have_text('Файлы не выбраны.')
    finally:context.close()


def test_dialog_dates_delete_confirmation_and_other_tab_sync(real_account_browser,tmp_path):
    browser,mailbox,frontend,_=real_account_browser
    context=browser.new_context(viewport={'width':1440,'height':1000})
    try:
        page=context.new_page();register(page,mailbox,frontend,'dialog-delete@owned.test');login(page,'dialog-delete@owned.test')
        identifier=start_and_stop(page,'Диалог с датами для удаления')
        row=page.locator(f'#conversations li[data-conversation="{identifier}"]')
        expect(row.locator('time')).to_have_count(2)
        expect(row).to_contain_text('Создан:');expect(row).to_contain_text('Обновлён:')
        row.hover();expect(row.locator('.delete-conversation')).to_have_css('opacity','1')
        neighbor=context.new_page();neighbor.goto(frontend);login(neighbor,'dialog-delete@owned.test')
        expect(neighbor.locator('#conversations li')).to_have_count(1)
        page.bring_to_front();row.locator('.delete-conversation').click()
        expect(page.locator('#confirm-action')).to_be_visible();page.locator('#confirm-cancel').click()
        expect(row).to_be_visible()
        row.hover();row.locator('.delete-conversation').click();page.locator('#confirm-accept').click()
        expect(page.locator('#conversations li')).to_have_count(0,timeout=api_wait_ms(page))
        expect(neighbor.locator('#conversations li')).to_have_count(0,timeout=api_wait_ms(neighbor))
        expect(page.locator('#conversation-title')).to_have_text('Новый диалог')
        page.reload();expect(page.locator('html')).to_have_attribute('data-ready','true')
        expect(page.locator('#conversations li')).to_have_count(0)
        page.screenshot(path=str(tmp_path/'dialog-delete-1440.png'))
    finally:context.close()


def test_dialog_delete_failure_keeps_history_and_draft(real_account_browser):
    browser,mailbox,frontend,api=real_account_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'dialog-delete-retry@owned.test');login(page,'dialog-delete-retry@owned.test')
        identifier=start_and_stop(page,'История останется при отказе удаления')
        page.locator('#question').fill('Сохранённый черновик')
        row=page.locator(f'#conversations li[data-conversation="{identifier}"]')
        def reject_delete(route):
            if route.request.method=='DELETE':route.fulfill(status=503,json={'error':'unavailable'})
            else:route.continue_()
        page.route(api+'/api/conversations/'+identifier,reject_delete)
        row.hover();row.locator('.delete-conversation').click();page.locator('#confirm-accept').click()
        expect(page.locator('#conversation-feedback')).to_contain_text('Не удалось подтвердить удаление')
        expect(row).to_be_visible();expect(page.locator('#history article')).to_have_count(1)
        expect(page.locator('#question')).to_have_value('Сохранённый черновик')
        expect(row.locator('.delete-conversation')).to_be_enabled()
        page.unroute(api+'/api/conversations/'+identifier)
        row.hover();row.locator('.delete-conversation').click();page.locator('#confirm-accept').click()
        expect(page.locator('#conversations li')).to_have_count(0,timeout=api_wait_ms(page))
    finally:context.close()


def test_recent_dialogs_scroll_inside_sidebar_at_desktop_and_mobile(real_account_browser,tmp_path):
    """Actual API history; no generated model answers are claimed by this layout check."""
    browser,mailbox,frontend,api=real_account_browser
    context=browser.new_context(viewport={'width':1440,'height':1000})
    try:
        page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        register(page,mailbox,frontend,'dialog-scroll@owned.test');login(page,'dialog-scroll@owned.test')
        page.locator('#question').fill('Проверка соединения')
        expect(page.locator('#send-question')).to_be_enabled(timeout=api_wait_ms(page))
        credentials=page.evaluate("({token:sessionStorage.getItem('rag:credential'),tab:JSON.parse(sessionStorage.getItem('rag:tab'))})")
        headers={'Authorization':'Bearer '+credentials['token'],'X-Tab-Proof':credentials['tab']['proof']}
        from uuid import uuid4
        for index in range(18):
            response=page.request.post(api+'/api/conversations',headers=headers,data={'id':str(uuid4())})
            assert response.ok,response.text()
            identifier=response.json()['id']
            response=page.request.post(api+f'/api/conversations/{identifier}/answers',headers=headers,data={
                'operation_key':str(uuid4()),'question':f'Диалог {index+1}: бюджет и сроки проекта','document_ids':[],'tab_id':credentials['tab']['id']})
            assert response.ok,response.text()
            response=page.request.post(api+'/api/answers/'+response.json()['id']+'/stop',headers=headers)
            assert response.ok,response.text()
        expect(page.locator('#conversations li')).to_have_count(18,timeout=api_wait_ms(page))
        page.evaluate('scrollTo(0,0)')
        picker=page.locator('.conversation-picker')
        assert picker.evaluate("e=>e.scrollHeight>e.clientHeight && getComputedStyle(e).overflowY==='auto'")
        assert picker.evaluate("e=>getComputedStyle(e).scrollbarWidth!=='none'")
        assert page.locator('#workspace-sidebar').bounding_box()['y']+page.locator('#workspace-sidebar').bounding_box()['height']<=1000
        page.locator('#conversations li').first.hover()
        page.screenshot(path=str(tmp_path/'dialog-e1-p1-desktop.png'))
        picker.evaluate('e=>e.scrollTop=e.scrollHeight')
        assert picker.evaluate('e=>e.scrollTop>0')
        page.locator('#conversations li').last.locator('.conversation-open').click()
        expect(page.locator('#history article')).to_have_count(1)
        page.set_viewport_size({'width':375,'height':812});page.evaluate('scrollTo(0,0)')
        page.locator('#sidebar-toggle').click()
        assert picker.evaluate('e=>e.scrollHeight>e.clientHeight')
        picker.evaluate('e=>e.scrollTop=e.scrollHeight')
        assert picker.evaluate('e=>e.scrollTop>0')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(tmp_path/'dialog-e1-p1-mobile.png'))
        assert not errors,errors
    finally:context.close()
