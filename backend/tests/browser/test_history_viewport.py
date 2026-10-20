"""History geometry and streaming scroll against the production renderer."""
from playwright.sync_api import expect
from .test_accounts import real_account_browser, register, login, navigate


def test_history_is_ten_times_taller_at_desktop_and_mobile(real_account_browser):
    browser,mailbox,frontend,_=real_account_browser
    context=browser.new_context()
    try:
        page=context.new_page();register(page,mailbox,frontend,'history-height@owned.test');login(page,'history-height@owned.test')
        for width,height in [(1440,900),(375,812)]:
            page.set_viewport_size({'width':width,'height':height})
            page.wait_for_timeout(100)
            ratio=page.evaluate('''() => {
                const main=document.querySelector('main'),history=document.querySelector('#history');
                const expanded=history.getBoundingClientRect().height;
                const extra=main.style.getPropertyValue('--history-extra-height');
                main.style.removeProperty('--history-extra-height');
                const baseline=history.getBoundingClientRect().height;
                main.style.setProperty('--history-extra-height',extra);
                return expanded/baseline;
            }''')
            assert abs(ratio-10)<.05,ratio
            page.locator('#question').fill('A draft in the enlarged conversation')
            expect(page.locator('#question')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        navigate(page,'library')
        expect(page.locator('#library')).to_be_visible()
        assert page.evaluate('document.querySelector("main").getBoundingClientRect().height<=innerHeight+1')
    finally:context.close()


def test_new_questions_and_streamed_answer_scroll_to_latest_content(real_account_browser,tmp_path):
    browser,mailbox,frontend,_=real_account_browser
    context=browser.new_context(viewport={'width':1440,'height':900})
    try:
        page=context.new_page();register(page,mailbox,frontend,'history-scroll@owned.test');login(page,'history-scroll@owned.test')
        page.evaluate('''async () => {
            const {Conversations}=await import('/src/conversations.js');
            const renderer=Object.create(Conversations.prototype);
            renderer.current=()=>true;renderer.selected='scroll-room';renderer.cards=new Map();renderer.documents=[];
            renderer.drafts={get:()=>({text:'',documentIds:[],answerId:null})};
            renderer.renderComposer=()=>{};renderer.renderEvidence=()=>{};
            const requests=Array.from({length:12},(_,i)=>({id:'answer-'+i,state:'completed',answer_text:('Answer '+i+'\\n').repeat(80),passport:{},citations:[]}));
            const messages=requests.map((r,i)=>({request_id:r.id,role:'user',text:'Question '+i}));
            renderer.histories=new Map([['scroll-room',{requests,messages}]]);
            window.scrollRenderer=renderer;renderer.render();
        }''')
        def at_bottom():
            page.wait_for_function('''() => {
                const h=document.querySelector('#history');
                return h.scrollHeight-h.clientHeight-h.scrollTop<2;
            }''')
        at_bottom()
        page.evaluate('''() => {
            document.querySelector('#history').scrollTop=0;
            const value=scrollRenderer.histories.get('scroll-room');
            value.requests.at(-1).answer_text+='Newest streamed text\\n'.repeat(30);
            scrollRenderer.render();
        }''')
        at_bottom()
        page.evaluate('''() => {
            document.querySelector('#history').scrollTop=0;
            const value=scrollRenderer.histories.get('scroll-room');
            value.requests.push({id:'new-question',state:'accepted',answer_text:'',passport:{},citations:[]});
            value.messages.push({request_id:'new-question',role:'user',text:'The latest user question'});
            scrollRenderer.render();
        }''')
        at_bottom()
        expect(page.locator('#history article').last).to_contain_text('The latest user question')
        assert page.locator('#history article').last.bounding_box()['y']<900
        assert page.locator('#nav-workspace').bounding_box()['y']>=0
        page.locator('#open-evidence').evaluate("el=>el.click()")
        expect(page.locator('#evidence')).to_be_visible()
        assert 0<=page.locator('#evidence').bounding_box()['y']<900
        page.screenshot(path=str(tmp_path/'history-latest-1440.png'))
        page.evaluate('''() => {document.querySelector('#history').scrollTop=0;scrollRenderer.render();}''')
        page.wait_for_timeout(100)
        assert page.locator('#history').evaluate('el=>el.scrollTop')==0
        page.set_viewport_size({'width':375,'height':812})
        expect(page.locator('#history')).to_be_hidden()
        page.evaluate('''() => {
            const request=scrollRenderer.histories.get('scroll-room').requests.at(-1);
            request.answer_text='Mobile streamed answer\\n'.repeat(160);request.state='generating';
            scrollRenderer.render();
        }''')
        page.locator('#close-evidence').click()
        at_bottom()
        page.wait_for_function("document.querySelector('#history .answer-text:last-of-type')!==null")
        assert page.locator('#history .answer-text').last.bounding_box()['y']+page.locator('#history .answer-text').last.bounding_box()['height']<=812
        page.screenshot(path=str(tmp_path/'history-latest-375.png'))
    finally:context.close()
