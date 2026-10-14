"""D1 real issuer/browser path; documents/OCR and manual G3 proof remain separate."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Thread
import time
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlencode

from playwright.sync_api import expect, sync_playwright
import pytest

from mailbox import Mailbox


BACKEND = Path(__file__).parents[2]
FRONTEND = BACKEND.parent / 'frontend'
PASSWORD = 'A long owned browser password'


@pytest.fixture
def real_account_browser(environment, monkeypatch, tmp_path):
    api_url = None
    monkeypatch.setenv('RAG_ORIGINALS_DIR',str(tmp_path/'originals'))

    class Static(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(FRONTEND), **kwargs)

        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.split('?',1)[0] in ('/', '/index.html'):
                body = (FRONTEND / 'index.html').read_text().replace('http://127.0.0.1:8000', api_url).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)
            else:
                super().do_GET()

    static = ThreadingHTTPServer(('127.0.0.1', 0), Static)
    frontend_url = f'http://127.0.0.1:{static.server_port}'
    static_thread = Thread(target=static.serve_forever, daemon=True)
    static_thread.start()
    api_process = None
    api_log = None
    try:
        with Mailbox() as mailbox:
            mailbox.configure(monkeypatch, frontend_url)
            monkeypatch.setenv('RAG_DATABASE_URL', environment['dsn'])
            api_log = (tmp_path/'api-first.log').open('xb')
            api_process = subprocess.Popen([str(BACKEND / '.venv/bin/rag-api'), '--port', '0'], cwd=BACKEND,
                                           env=os.environ.copy(), stdout=api_log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 15
            while api_url is None:
                match = re.search(r'Uvicorn running on (http://127\.0\.0\.1:\d+)',(tmp_path/'api-first.log').read_text())
                if match:
                    api_url = match.group(1)
                    break
                if api_process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('Owned D1 API did not bind')
                time.sleep(.05)
            while True:
                try:
                    with urlopen(f'{api_url}/openapi.json', timeout=.5):
                        break
                except (OSError, URLError):
                    if api_process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('Owned D1 API did not start')
                    time.sleep(.05)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=playwright.chromium.executable_path, headless=True)
                try:
                    yield browser, mailbox, frontend_url, api_url
                finally:
                    browser.close()
    finally:
        if api_process is not None:
            api_process.terminate()
            try:
                api_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                api_process.kill()
                api_process.wait(timeout=10)
        if api_log is not None:
            api_log.close()
        static.shutdown()
        static.server_close()
        static_thread.join()


def register(page, mailbox, frontend_url, email, invitation_url=None):
    page.goto(invitation_url or frontend_url)
    form = page.locator('#register')
    form.locator('[name=email]').fill(email)
    form.locator('[name=password]').fill(PASSWORD)
    form.get_by_role('button', name='Зарегистрироваться').click()
    expect(page.locator('#status')).to_have_text('Откройте письмо и подтвердите email, затем войдите.')
    page.goto(f'http://127.0.0.1:{mailbox.http.server_port}/?{urlencode({"email": email})}')
    page.get_by_role('link', name='Verify email').click()
    expect(page.locator('#status')).to_have_text('Email подтверждён. Теперь войдите.')
    assert '#' not in page.url


def login(page, email):
    form = page.locator('#login')
    form.locator('[name=email]').fill(email)
    form.locator('[name=password]').fill(PASSWORD)
    form.get_by_role('button', name='Войти', exact=True).click()
    expect(page.locator('#workspace')).to_be_visible()
    expect(page.locator('#identity')).to_contain_text(email)


def test_actual_ui_smtp_roles_block_soft_delete_and_logout(real_account_browser):
    browser, mailbox, frontend, api_url = real_account_browser
    contexts = [browser.new_context() for _ in range(3)]
    try:
        operator, administrator, user = [context.new_page() for context in contexts]
        # Actual operator CLI, never SQL role promotion or fixture principals.
        invitation = subprocess.run([sys.executable, '-m', 'app.accounts', '--email', 'operator-browser@owned.test'],
                                    cwd=BACKEND, env=os.environ.copy(), check=True, capture_output=True, text=True).stdout.strip()
        register(operator, mailbox, frontend, 'operator-browser@owned.test', invitation)
        login(operator, 'operator-browser@owned.test')
        expect(operator.locator('#identity')).to_contain_text('super_admin')
        register(administrator, mailbox, frontend, 'admin-browser@owned.test')
        login(administrator, 'admin-browser@owned.test')
        register(user, mailbox, frontend, 'user-browser@owned.test')
        login(user, 'user-browser@owned.test')
        user.get_by_role('button', name='Открыть беседу').click()
        expect(user.locator('#history')).to_have_text('В этой беседе пока нет сообщений.')
        user_conversation = user.evaluate("async url => { const r = await fetch(url + '/api/accounts/me', {headers:{Authorization:'Bearer '+sessionStorage.getItem('rag:credential')}}); return (await r.json()).conversations[0].id; }", api_url)

        operator.reload()
        admin_form = operator.locator('form[data-account="admin-browser@owned.test"]')
        admin_form.locator('select[name=role]').select_option('admin')
        admin_form.get_by_role('button', name='Сохранить права').click()
        expect(operator.locator('#status')).to_contain_text('Права сохранены')
        administrator.reload()
        expect(administrator.locator('#workspace')).to_be_visible()
        expect(administrator.locator('#identity')).to_contain_text('admin')
        expect(administrator.locator('#administration')).to_be_visible()
        expect(administrator.locator('form[data-account="user-browser@owned.test"] select')).to_be_disabled()
        denials = administrator.evaluate("""async ({url, conversation}) => {
          const headers = {Authorization: 'Bearer ' + sessionStorage.getItem('rag:credential')};
          return await Promise.all(['/api/settings', '/api/conversations/'+conversation].map(async path => (await fetch(url+path,{headers})).status));
        }""", {'url': api_url, 'conversation': user_conversation})
        assert denials == [403, 404]

        user_form = administrator.locator('form[data-account="user-browser@owned.test"]')
        user_form.locator('[name=disabled]').check()
        user_form.get_by_role('button', name='Сохранить права').click()
        expect(administrator.locator('#status')).to_contain_text('Права сохранены')
        user.reload()
        expect(user.locator('#authentication')).to_be_visible()
        user_form = administrator.locator('form[data-account="user-browser@owned.test"]')
        user_form.locator('[name=disabled]').uncheck()
        user_form.get_by_role('button', name='Сохранить права').click()
        expect(administrator.locator('#status')).to_contain_text('Права сохранены')
        login(user, 'user-browser@owned.test')
        user.get_by_role('button', name='Выйти', exact=True).click()
        expect(user.locator('#authentication')).to_be_visible()
        assert user.evaluate('sessionStorage.length') == 0
        login(user, 'user-browser@owned.test')
        user_form = administrator.locator('form[data-account="user-browser@owned.test"]')
        user_form.locator('[name=active]').uncheck()
        user_form.get_by_role('button', name='Сохранить права').click()
        expect(administrator.locator('#status')).to_contain_text('Права сохранены')
        user.reload()
        expect(user.locator('#authentication')).to_be_visible()
        user.locator('#login [name=email]').fill('user-browser@owned.test')
        user.locator('#login [name=password]').fill(PASSWORD)
        user.locator('#login button').click()
        expect(user.locator('#status')).to_contain_text('Доступ закрыт')

        # Same static UI at a narrow width; no horizontal overflow or hidden labels.
        user.set_viewport_size({'width': 375, 'height': 812})
        assert user.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert frontend != api_url
        print('D1: real Chromium; independent static/API/mailbox origins; SMTP delivery; CLI invite; UI signup/verify/login/admin/block/soft-delete/logout; no network mocks.')
    finally:
        for context in contexts:
            context.close()


def test_exact_cors_and_public_registration_escalation_refusal(real_account_browser):
    browser, _, frontend, api_url = real_account_browser
    context = browser.new_context()
    try:
        response = context.request.fetch(f'{api_url}/api/accounts/login', method='OPTIONS', headers={
            'Origin': frontend, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type',
        })
        assert response.status == 200 and response.headers['access-control-allow-origin'] == frontend
        response = context.request.fetch(f'{api_url}/api/accounts/login', method='OPTIONS', headers={
            'Origin': 'https://unrelated.example', 'Access-Control-Request-Method': 'POST',
        })
        assert response.status == 400 and 'access-control-allow-origin' not in response.headers
        response = context.request.post(f'{api_url}/api/accounts/register', data={
            'email': 'public-admin@owned.test', 'password': PASSWORD, 'role': 'super_admin',
        })
        assert response.status == 422 and 'password' not in response.text()
    finally:
        context.close()


def test_invited_registration_retries_actual_smtp_failure(real_account_browser):
    browser, mailbox, frontend, _ = real_account_browser
    context = browser.new_context()
    try:
        page = context.new_page()
        invitation = subprocess.run([sys.executable, '-m', 'app.accounts', '--email', 'retry-operator@owned.test'],
                                    cwd=BACKEND, env=os.environ.copy(), check=True, capture_output=True, text=True).stdout.strip()
        page.goto(invitation)
        form = page.locator('#register')
        form.locator('[name=email]').fill('retry-operator@owned.test')
        form.locator('[name=password]').fill(PASSWORD)
        mailbox.reject_delivery = True
        form.get_by_role('button', name='Зарегистрироваться').click()
        expect(page.locator('#status')).to_have_text('Письмо не доставлено. Повторите регистрацию с тем же паролем.')
        mailbox.reject_delivery = False
        form.get_by_role('button', name='Зарегистрироваться').click()
        expect(page.locator('#status')).to_have_text('Откройте письмо и подтвердите email, затем войдите.')
        page.goto(f'http://127.0.0.1:{mailbox.http.server_port}/?{urlencode({"email": "retry-operator@owned.test"})}')
        page.get_by_role('link', name='Verify email').click()
        expect(page.locator('#status')).to_have_text('Email подтверждён. Теперь войдите.')
        login(page, 'retry-operator@owned.test')
        expect(page.locator('#identity')).to_contain_text('super_admin')
    finally:
        context.close()
