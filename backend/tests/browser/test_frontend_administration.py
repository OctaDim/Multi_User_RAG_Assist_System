"""Administration uses the real role/account/settings API; failures are bounded probes."""
import os,sys,subprocess,re
from playwright.sync_api import expect
from .test_accounts import BACKEND,real_account_browser,register,login


def test_management_retry_foreign_library_and_settings_write_failure(real_account_browser,tmp_path):
    browser,mailbox,frontend,api_url=real_account_browser
    contexts=[browser.new_context() for _ in range(2)]
    try:
        operator,user=[context.new_page() for context in contexts]
        invitation=subprocess.run([sys.executable,'-m','app.accounts','--email','manage-operator@owned.test'],cwd=BACKEND,env=os.environ.copy(),check=True,capture_output=True,text=True).stdout.strip()
        register(operator,mailbox,frontend,'manage-operator@owned.test',invitation);login(operator,'manage-operator@owned.test')
        register(user,mailbox,frontend,'manage-user@owned.test');login(user,'manage-user@owned.test')
        operator.route(api_url+'/api/accounts',lambda route:route.fulfill(status=503,json={'error':'unavailable'}))
        operator.reload()
        operator.locator('#nav-administration').click()
        expect(operator.locator('#status')).to_contain_text('Не удалось выполнить действие')
        operator.unroute(api_url+'/api/accounts')
        expect(operator.locator('#refresh-administration')).to_be_visible()
        operator.locator('#refresh-administration').click()
        card=operator.locator('#accounts article').filter(has=operator.locator('form[data-account="manage-user@owned.test"]'))
        expect(card).to_be_visible()
        card.get_by_role('button',name='Читать библиотеку',exact=True).click()
        expect(operator.locator('#library-context')).to_contain_text('manage-user@owned.test')
        expect(operator.locator('#library-context')).to_contain_text('Только чтение')
        expect(operator.locator('#document-upload')).to_be_hidden()
        operator.locator('#refresh-documents').click()
        expect(operator.locator('#library-context')).to_contain_text('manage-user@owned.test')
        owner=card.locator('form[data-policy]').get_attribute('data-policy')
        held=[]
        def hold_foreign(route): held.append((route,route.fetch()))
        operator.route(api_url+'/api/documents/admin/'+owner+'/library',hold_foreign)
        operator.locator('#refresh-documents').click()
        operator.locator('#own-library').click()
        expect(operator.locator('#library-title')).to_have_text('Мои документы')
        expect(operator.locator('#document-upload')).to_be_visible()
        route,response=held.pop();route.fulfill(response=response)
        expect(operator.locator('#library-title')).to_have_text('Мои документы')
        expect(operator.locator('#library-context')).not_to_contain_text('manage-user@owned.test')
        operator.locator('#nav-administration').click()
        form=operator.locator('#global-settings')
        previous_revision=int(re.search(r'Сохранена ревизия (\d+)',form.locator('.settings-revision').inner_text()).group(1))
        field=form.locator('[name=max_active]')
        changed=str(int(field.input_value())+1)
        field.fill(changed)
        expect(form.locator('[name=model]')).to_be_disabled()
        form.get_by_role('button',name='Предпросмотр изменения',exact=True).click()
        expect(form.locator('.settings-preview')).to_contain_text('Область действия: весь сервис')
        attempts=[]
        def fail_first(route):
            if route.request.method=='PATCH':
                attempts.append(route.request)
                if len(attempts)==1:
                    route.fulfill(status=503,json={'error':'unavailable'});return
            route.continue_()
        operator.route(api_url+'/api/settings',fail_first)
        save=form.get_by_role('button',name='Сохранить глобальные настройки',exact=True)
        save.click()
        expect(form.locator('.operation-status')).to_contain_text('Не удалось выполнить действие')
        expect(field).to_have_value(changed)
        expect(save).to_be_enabled()
        assert len(attempts)==1
        save.click()
        expect(form.locator('.settings-revision')).to_contain_text(f'Сохранена ревизия {previous_revision+1}')
        expect(form.locator('.settings-revision')).to_contain_text('Ожидает применения')
        assert len(attempts)==2
        for width in (1440,768,375):
            operator.set_viewport_size({'width':width,'height':1000})
            assert operator.evaluate('document.documentElement.scrollWidth <= innerWidth')
            operator.screenshot(path=str(tmp_path/f'administration-{width}.png'),full_page=True)
    finally:
        for context in contexts:context.close()
