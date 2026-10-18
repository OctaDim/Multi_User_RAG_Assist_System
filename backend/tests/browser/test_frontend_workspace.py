"""Three-area workspace checks against actual account/API, with controlled policy failure."""
from playwright.sync_api import expect
from .test_accounts import real_account_browser, register, login


def test_three_work_areas_preserve_context_and_role_navigation(real_account_browser):
    browser, mailbox, frontend, _ = real_account_browser
    context = browser.new_context(viewport={'width':1440,'height':1000})
    try:
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        register(page, mailbox, frontend, 'three-areas@owned.test')
        login(page, 'three-areas@owned.test')
        for area in ('library','chat','evidence'):
            expect(page.locator('#'+area)).to_be_visible()
        expect(page.locator('#nav-administration')).to_be_hidden()
        page.locator('#question').fill('Keep this question while reading documents')
        for width in (768,375):
            page.set_viewport_size({'width':width,'height':900})
            expect(page.locator('#chat')).to_be_visible()
            page.locator('[data-area=library]').click()
            expect(page.locator('#library')).to_be_visible()
            expect(page.locator('#chat')).to_be_hidden()
            page.locator('[data-area=evidence]').click()
            expect(page.locator('#evidence')).to_be_visible()
            page.locator('[data-area=chat]').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#question')).to_have_value('Keep this question while reading documents')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert errors == []
    finally:
        context.close()


def test_public_policy_failure_can_retry_without_reloading(real_account_browser):
    browser, _, frontend, api_url = real_account_browser
    context = browser.new_context()
    try:
        page = context.new_page()
        page.route(api_url+'/api/public-settings',lambda route:route.fulfill(status=503,json={'error':'unavailable'}))
        page.goto(frontend)
        expect(page.locator('#retry-bootstrap')).to_be_visible()
        expect(page.locator('#login button')).to_be_disabled()
        page.unroute(api_url+'/api/public-settings')
        page.locator('#retry-bootstrap').click()
        expect(page.locator('#retry-bootstrap')).to_be_hidden()
        expect(page.locator('#login button')).to_be_enabled()
        page.locator('#show-register').click()
        expect(page.locator('#register')).to_be_visible()
        expect(page.locator('#login')).to_be_hidden()
    finally:
        context.close()
