"""Conversation-first workspace checks against actual account/API, with controlled policy failure."""
from playwright.sync_api import expect
from .test_accounts import real_account_browser, register, login


def test_chat_first_workspace_preserves_context_and_role_navigation(real_account_browser,tmp_path):
    browser, mailbox, frontend, _ = real_account_browser
    context = browser.new_context(viewport={'width':1440,'height':1000})
    try:
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        register(page, mailbox, frontend, 'chat-first@owned.test')
        login(page, 'chat-first@owned.test')
        expect(page.locator('#chat')).to_be_visible()
        expect(page.locator('#library')).to_be_hidden()
        expect(page.locator('#evidence')).to_be_hidden()
        page.locator('[data-area=evidence]').click()
        expect(page.locator('#chat')).to_be_visible()
        expect(page.locator('#evidence')).to_be_visible()
        page.locator('#close-evidence').click()
        expect(page.locator('#evidence')).to_be_hidden()
        expect(page.locator('#nav-administration')).to_be_hidden()
        page.locator('#question').fill('Keep this question while reading documents')
        page.locator('[data-area=library]').click()
        page.locator('.skip-link').focus();page.keyboard.press('Enter')
        expect(page.locator('#chat')).to_be_visible()
        expect(page.locator('#question')).to_be_focused()
        for width in (768,375):
            page.set_viewport_size({'width':width,'height':900})
            expect(page.locator('#chat')).to_be_visible()
            page.screenshot(path=str(tmp_path/f'workspace-{width}.png'),full_page=True)
            page.locator('[data-area=library]').click()
            expect(page.locator('#library')).to_be_visible()
            expect(page.locator('#chat')).to_be_hidden()
            page.locator('[data-area=chat]').click()
            page.locator('[data-area=evidence]').click()
            expect(page.locator('#evidence')).to_be_visible()
            page.locator('[data-area=chat]').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#question')).to_have_value('Keep this question while reading documents')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width':375,'height':812})
        assert page.locator('#history').bounding_box()['height'] >= 200, 'The conversation needs a readable viewport on a small screen'
        page.locator('[data-area=library]').click()
        page.reload()
        expect(page.locator('#library')).to_be_visible()
        page.locator('[data-area=chat]').click()
        expect(page.locator('#question')).to_have_value('Keep this question while reading documents')
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


def test_long_chat_menus_keep_source_choices_clickable_on_a_short_screen(real_account_browser):
    """Controlled rows isolate production CSS/navigation; real publication is tested separately."""
    browser,_,frontend,_=real_account_browser
    context=browser.new_context(viewport={'width':1280,'height':720})
    try:
        page=context.new_page();page.goto(frontend)
        page.wait_for_function('document.documentElement.dataset.ready === "true"')
        page.evaluate('''() => {
          document.querySelector('#authentication').hidden=true;
          document.querySelector('#workspace').hidden=false;
          const list=document.querySelector('#conversations');
          for(let i=0;i<20;i++){
            const li=document.createElement('li'),button=document.createElement('button');
            button.type='button';button.textContent='Conversation '+i;li.append(button);list.append(li);
          }
          const choices=document.querySelector('#question-sources');
          for(let i=0;i<9;i++){
            const label=document.createElement('label'),input=document.createElement('input');
            input.type='checkbox';label.append(input,document.createTextNode('Source '+i));choices.append(label);
          }
        }''')
        for selector in ['.conversation-picker','#source-selection']:
            if not page.locator(selector).evaluate('(details)=>details.open'):page.locator(selector+' summary').click()
        page.get_by_role('checkbox',name='Source 8',exact=True).check(timeout=3000)
        expect(page.get_by_role('checkbox',name='Source 8',exact=True)).to_be_checked()
        page.locator('#question').fill('A draft survives opening the source chooser')
        assert not page.locator('#source-selection').evaluate('(details)=>details.open')
        assert not page.locator('.conversation-picker').evaluate('(details)=>details.open')
        page.locator('#source-selection summary').focus();page.keyboard.press('Enter')
        expect(page.get_by_role('checkbox',name='Source 8',exact=True)).to_be_checked()
        expect(page.locator('#question')).to_have_value('A draft survives opening the source chooser')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:context.close()


def test_evidence_render_preserves_focused_citation_when_status_changes(real_account_browser):
    """Exercise the production renderer's focus transition without waiting on model timing."""
    browser,mailbox,frontend,_=real_account_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'evidence-focus@owned.test');login(page,'evidence-focus@owned.test')
        page.locator('[data-area=evidence]').click()
        result=page.evaluate('''async () => {
            const {Conversations}=await import('/src/conversations.js');
            const renderer=Object.create(Conversations.prototype);
            renderer.selected='focus-conversation';renderer.documents=[];
            const request={id:'focus-answer',state:'generating',passport:{available:[],found:[],passed:[]},
                citations:[{number:1,document_id:'focus-source',name:'focus.txt',page:1,quote:'The annual budget is 100 euros.'}]};
            renderer.renderEvidence(request);
            const quote=document.querySelector('#citation-focus-answer-1');quote.tabIndex=-1;quote.focus();
            const before=document.activeElement===quote;
            renderer.renderEvidence({...request,state:'completed'});
            return {before,after:document.activeElement.id};
        }''')
        assert result['before']
        assert result['after']=='citation-focus-answer-1'
    finally:context.close()
