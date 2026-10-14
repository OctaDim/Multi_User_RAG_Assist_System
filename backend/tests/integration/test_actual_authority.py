"""R17 matrix with genuine issuer sessions and UI-controlled account states."""
import json

from playwright.sync_api import expect

from integration.test_answer_lifecycle import environment, operator
from browser.test_accounts import PASSWORD, real_account_browser, register, login
from browser.test_documents import real_document_browser, ready


def protected(page,api,paths,token):
    return page.evaluate('''async ({api,paths,token}) => await Promise.all(paths.map(async path => {
        const response=await fetch(api+path,{headers:token?{Authorization:'Bearer '+token}:{}});
        return {path,status:response.status,body:await response.text()};
    }))''',{'api':api,'paths':paths,'token':token})


def test_anonymous_unverified_inactive_disabled_and_paid_false_actual_issuer_matrix(real_document_browser):
    (browser,mailbox,frontend,api),_,_=real_document_browser
    contexts=[browser.new_context() for _ in range(4)]
    try:
        admin,owner,foreign,unverified=[context.new_page() for context in contexts]
        operator(admin,mailbox,frontend)
        email='u8-authority-owner@owned.test'
        register(owner,mailbox,frontend,email);login(owner,email)
        owner.locator('#document-upload input').set_input_files({'name':'owner-secret.txt','mimeType':'text/plain','buffer':b'Private owner receipt: 74192.'})
        owner.get_by_role('button',name='Загрузить документы',exact=True).click();ready(owner,'owner-secret.txt')
        identity=owner.evaluate('''async api => ({credential:sessionStorage.getItem('rag:credential'),
            me:await (await fetch(api+'/api/accounts/me',{headers:{Authorization:'Bearer '+sessionStorage.getItem('rag:credential')}})).json(),
            document:document.querySelector('#documents li').dataset.document})''',api)
        assert identity['me']['account']['paid'] is False
        conversation=identity['me']['conversations'][0]['id'];document=identity['document']
        paths=[f'/api/conversations/{conversation}',f'/api/documents/{document}',f'/api/documents/{document}/original']
        allowed=protected(owner,api,paths,identity['credential'])
        assert all(row['status']==200 for row in allowed),allowed
        anonymous=protected(owner,api,paths,None)
        assert all(row['status']==401 for row in anonymous),anonymous
        register(foreign,mailbox,frontend,'u8-authority-foreign@owned.test');login(foreign,'u8-authority-foreign@owned.test')
        credential=foreign.evaluate("sessionStorage.getItem('rag:credential')")
        denials=protected(foreign,api,paths,credential)
        assert all(row['status']==404 for row in denials),denials
        assert all('74192' not in row['body'] and 'owner-secret' not in row['body'] for row in denials+anonymous)
        unverified.goto(frontend)
        form=unverified.locator('#register');form.locator('[name=email]').fill('u8-unverified@owned.test')
        form.locator('[name=password]').fill(PASSWORD);form.get_by_role('button',name='Зарегистрироваться',exact=True).click()
        expect(unverified.locator('#status')).to_contain_text('Откройте письмо')
        response=contexts[3].request.post(api+'/api/accounts/login',data={'email':'u8-unverified@owned.test','password':PASSWORD})
        assert response.status==403 and 'token' not in response.json()
        assert mailbox.link('u8-unverified@owned.test')
        admin.reload()
        states={}
        for key in ['disabled','active']:
            form=admin.locator(f'form[data-account="{email}"]')
            form.locator(f'[name={key}]').set_checked(key=='disabled')
            form.get_by_role('button',name='Сохранить права',exact=True).click()
            expect(admin.locator('#status')).to_contain_text('Права сохранены')
            denied=protected(admin,api,paths,identity['credential'])
            assert all(row['status']==401 for row in denied),denied
            assert all('74192' not in row['body'] and 'owner-secret' not in row['body'] for row in denied)
            states[key]=denied
            owner.reload();expect(owner.locator('#authentication')).to_be_visible()
            form=admin.locator(f'form[data-account="{email}"]')
            form.locator(f'[name={key}]').set_checked(key=='active')
            form.get_by_role('button',name='Сохранить права',exact=True).click()
            expect(admin.locator('#status')).to_contain_text('Права сохранены')
            login(owner,email);identity['credential']=owner.evaluate("sessionStorage.getItem('rag:credential')")
        print(json.dumps({'proof':'actual_issuer_r17_matrix','anonymous':anonymous,'foreign':denials,
            'unverified_login':response.status,'state_denials':states,'paid_false_allowed':True}),flush=True)
    finally:
        for context in contexts:context.close()
