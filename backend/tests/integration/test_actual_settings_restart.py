"""Persisted settings proven by actual UI and production supervisor restart."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psycopg
from playwright.sync_api import expect
import pytest

from integration.test_answer_lifecycle import environment,operator
from integration.test_terminal_lifecycle import controlled_native_browser,records
from browser.test_accounts import real_account_browser, navigate, open_sources
from browser.test_documents import real_document_browser,ready


def test_real_settings_late_refresh_cannot_replace_completed_save(real_account_browser,tmp_path):
    browser,mailbox,frontend,_=real_account_browser
    context=browser.new_context()
    try:
        page=context.new_page();operator(page,mailbox,frontend)
        navigate(page,'administration')
        form=page.locator('#global-settings')
        expect(form.locator('[name=max_active]')).to_have_value('12')
        form.locator('[name=max_active]').fill('6');form.locator('[name=step_width]').fill('2')
        form.get_by_role('button',name='Предпросмотр изменения',exact=True).click()
        page.evaluate('''() => {
            const original=window.fetch;
            window.holdSettings=true;
            window.fetch=async(...args)=>{
                const response=await original(...args);
                if(window.holdSettings && String(args[0]).endsWith('/api/settings') && args[1]?.method==='GET'){
                    window.holdSettings=false;
                    const value=await response.clone().json();
                    const read=response.json.bind(response);
                    response.json=async()=>{
                        const result=await read();
                        setTimeout(()=>window.staleSettingsProcessed=true,0);
                        return result;
                    };
                    return await new Promise(resolve=>window.heldSettings={value,release:()=>resolve(response)});
                }
                return response;
            };
        }''')
        navigate(page,'administration')
        form.get_by_role('button',name='Обновить применение настроек',exact=True).click()
        page.wait_for_function('window.heldSettings?.value.revision===0')
        form.get_by_role('button',name='Сохранить глобальные настройки',exact=True).click()
        expect(form.locator('.settings-revision')).to_contain_text('Сохранена ревизия 1.')
        page.evaluate('window.heldSettings.release()')
        page.wait_for_function('window.staleSettingsProcessed===true')
        expect(form.locator('.settings-revision')).to_contain_text('Сохранена ревизия 1.')
        expect(form.locator('[name=max_active]')).to_have_value('6')
        expect(form.locator('[name=step_width]')).to_have_value('2')
        page.screenshot(path=str(tmp_path/'settings-after-stale-real-response.png'),full_page=True)
    finally:context.close()


@pytest.mark.parametrize('controlled_native_browser',['after'],indirect=True)
def test_real_ui_hot_settings_and_supervisor_restart_preserve_saved_overrides(controlled_native_browser,environment,tmp_path):
    ((browser,mailbox,frontend,_),_,_),_,_,_,native_log,processes,launcher,_=controlled_native_browser
    context=browser.new_context()
    try:
        page=context.new_page();operator(page,mailbox,frontend)
        navigate(page,'administration')
        form=page.locator('#global-settings')
        expect(form.locator('[name=max_active]')).to_have_value('12')
        expect(form.locator('[name=step_width]')).to_have_value('3')
        form.locator('[name=max_active]').fill('6');form.locator('[name=step_width]').fill('2')
        form.get_by_role('button',name='Предпросмотр изменения',exact=True).click()
        form.get_by_role('button',name='Сохранить глобальные настройки',exact=True).click()
        expect(page.locator('#status')).to_contain_text('Ревизия 1 сохранена')
        navigate(page,'library')
        page.locator('#document-upload input').set_input_files({'name':'restart-budget.txt','mimeType':'text/plain','buffer':b'The annual budget is 100 euros.'})
        page.get_by_role('button',name='Загрузить документы',exact=True).click();ready(page,'restart-budget.txt')
        navigate(page,'chat')
        open_sources(page)
        page.get_by_role('checkbox',name='restart-budget.txt',exact=True).check()
        navigate(page,'chat')
        page.locator('#question').fill('What is the annual budget?')
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#history article')).to_contain_text('Завершён',timeout=60000)
        first_records=records(native_log);first_epoch=next(row['epoch'] for row in first_records if row['event']=='native_spawn')
        first_allocations=[row for row in first_records if row['event']=='native_allocate']
        assert len(first_allocations)==1 and first_allocations[0]['max_active']==6
        assert any(row['event']=='native_step' and row['revision']==1 and row['step_width']==2 for row in first_records)
        with psycopg.connect(environment['dsn'],autocommit=True) as connection:
            completed=connection.execute('SELECT id,state,answer_text FROM requests').fetchone()
            assert completed[1]=='completed' and '100' in completed[2]
        processes[0].terminate();processes[0].wait(20)
        first_child=next(row['pid'] for row in first_records if row['event']=='native_spawn')
        assert not Path(f'/proc/{first_child}').exists()
        with native_log.open('ab') as stream:
            replacement=subprocess.Popen([sys.executable,str(launcher)],cwd=Path(__file__).parents[2],env=os.environ.copy(),stdout=stream,stderr=subprocess.STDOUT)
        processes.append(replacement)
        deadline=time.monotonic()+30
        with psycopg.connect(environment['dsn'],autocommit=True) as connection:
            while True:
                epoch,healthy=connection.execute('SELECT epoch,healthy_until>clock_timestamp() FROM coordinator_lease').fetchone()
                if epoch>first_epoch and healthy:break
                assert replacement.poll() is None and time.monotonic()<deadline,native_log.read_text()[-2000:]
                page.wait_for_timeout(50)
            saved=connection.execute('SELECT overrides,revision,applied_revision FROM settings').fetchone()
            assert saved[0]['max_active']==6 and saved[0]['step_width']==2 and saved[1]==1
            assert connection.execute('SELECT state,answer_text FROM requests WHERE id=%s',(completed[0],)).fetchone()==completed[1:]
        page.reload()
        navigate(page,'administration')
        expect(form.locator('[name=max_active]')).to_have_value('6')
        expect(form.locator('[name=step_width]')).to_have_value('2')
        navigate(page,'chat')
        open_sources(page)
        page.get_by_role('checkbox',name='restart-budget.txt',exact=True).check()
        navigate(page,'chat')
        page.locator('#question').fill('What is the annual budget now?')
        page.get_by_role('button',name='Отправить вопрос',exact=True).click()
        expect(page.locator('#history article')).to_have_count(2)
        expect(page.locator('#history article').last).to_contain_text('Завершён',timeout=60000)
        trace=records(native_log);new_allocations=[row for row in trace if row['event']=='native_allocate' and row['epoch']>first_epoch]
        assert len(new_allocations)==1 and new_allocations[0]['max_active']==6
        assert any(row['event']=='native_step' and row['epoch']>first_epoch and row['revision']==1 and row['step_width']==2 for row in trace)
        navigate(page,'administration')
        form.get_by_role('button',name='Обновить применение настроек',exact=True).click()
        expect(form.locator('.settings-revision')).to_contain_text('Применена: 1')
        page.bring_to_front();page.screenshot(path=str(tmp_path/'settings-after-real-restart.png'),full_page=True)
        print(json.dumps({'proof':'actual_ui_settings_production_restart','before_epoch':first_epoch,'after_epoch':epoch,'max_active':6,'step_width':2,'revision':1,'completed_history_preserved':str(completed[0]),'native_log':str(native_log)}),flush=True)
    finally:context.close()
