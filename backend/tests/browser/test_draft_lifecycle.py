"""U1/G2 proof on a real browser; failures are gates, not expected successes."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import expect, sync_playwright


FIXTURE = Path(__file__).parents[1] / "fixtures" / "answer_lifecycle"


@pytest.fixture
def browser_session(tmp_path):
    handler = partial(SimpleHTTPRequestHandler, directory=str(FIXTURE))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    extension = FIXTURE / "restore_extension"
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                tmp_path / "profile",
                executable_path=playwright.chromium.executable_path,
                headless=False,
                ignore_default_args=["--disable-extensions"],
                args=[
                    f"--disable-extensions-except={extension}",
                    f"--load-extension={extension}",
                ],
            )
            try:
                worker = (
                    context.service_workers[0]
                    if context.service_workers
                    else context.wait_for_event("serviceworker")
                )
                print(f"browser={context.pages[0].evaluate('navigator.userAgent')}")
                yield context, worker, f"http://127.0.0.1:{server.server_port}/", playwright
            finally:
                context.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def open_fixture(context, url):
    page = context.new_page()
    page.goto(url)
    expect(page.locator("html")).to_have_attribute("data-ready", "true")
    return page


def test_reload_keeps_independent_conversation_and_tab_drafts(browser_session):
    context, _, url, _ = browser_session
    first = open_fixture(context, url)
    second = open_fixture(context, url)
    first.locator("#draft").fill("first A")
    first.locator("#conversation").select_option("B")
    first.locator("#draft").fill("first B")
    second.locator("#draft").fill("second A")
    for page, value in ((first, "first A"), (second, "second A")):
        tab = page.locator("html").get_attribute("data-tab")
        page.reload()
        expect(page.locator("#draft")).to_have_value(value)
        expect(page.locator("html")).to_have_attribute("data-tab", tab)
    first.locator("#conversation").select_option("B")
    expect(first.locator("#draft")).to_have_value("first B")


def test_close_and_new_tab_discards_drafts_without_changing_neighbor(browser_session):
    context, _, url, _ = browser_session
    closed = open_fixture(context, url)
    neighbor = open_fixture(context, url)
    closed.locator("#draft").fill("closed A")
    neighbor.locator("#draft").fill("neighbor A")
    closed.close()
    fresh = open_fixture(context, url)
    expect(fresh.locator("#draft")).to_have_value("")
    expect(neighbor.locator("#draft")).to_have_value("neighbor A")


def test_browser_restore_does_not_restore_closed_drafts(browser_session):
    context, worker, url, _ = browser_session
    closed = open_fixture(context, url + "?restore-proof")
    neighbor = open_fixture(context, url)
    closed.locator("#draft").fill("closed draft must disappear")
    closed.locator("#conversation").select_option("B")
    closed.locator("#draft").fill("closed B must disappear")
    closed.locator("#conversation").select_option("A")
    neighbor.locator("#draft").fill("neighbor A")
    closed_url = closed.url
    closed.close()
    with context.expect_page() as restored_page:
        worker.evaluate(
            """async url => {
                for (let attempt = 0; attempt < 50; attempt++) {
                    const sessions = await chrome.sessions.getRecentlyClosed();
                    const entry = sessions.find(item => item.tab?.url === url);
                    if (entry) return await chrome.sessions.restore(entry.tab.sessionId);
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                throw new Error('The closed browser tab was not recorded');
            }""",
            closed_url,
        )
    restored = restored_page.value
    expect(restored.locator("html")).to_have_attribute("data-ready", "true")
    observed = restored.locator("#draft").input_value()
    print(f"restore navigation={restored.locator('html').get_attribute('data-navigation')}, draft={observed!r}")
    expect(neighbor.locator("#draft")).to_have_value("neighbor A")
    assert observed == "", "R27/G2 failed: the browser restored the closed tab's draft"
    restored.locator("#conversation").select_option("B")
    expect(restored.locator("#draft")).to_have_value("")


def test_opener_has_an_independent_draft(browser_session):
    context, _, url, _ = browser_session
    original = open_fixture(context, url)
    original.locator("#draft").fill("original draft")
    with context.expect_page() as opened_page:
        original.evaluate("url => window.open(url)", url)
    opened = opened_page.value
    expect(opened.locator("html")).to_have_attribute("data-ready", "true")
    expect(opened.locator("#draft")).to_have_value("")
    expect(original.locator("#draft")).to_have_value("original draft")
    assert opened.locator("html").get_attribute("data-tab") != original.locator("html").get_attribute("data-tab")


def test_duplicate_has_an_independent_draft_and_tab_identity(browser_session):
    context, worker, url, _ = browser_session
    original = open_fixture(context, url + "?duplicate-proof")
    original.locator("#draft").fill("original draft")
    with context.expect_page() as duplicated_page:
        worker.evaluate(
            """async url => {
                const tabs = await chrome.tabs.query({});
                const original = tabs.find(tab => tab.url === url);
                return await chrome.tabs.duplicate(original.id);
            }""",
            original.url,
        )
    duplicated = duplicated_page.value
    expect(duplicated.locator("html")).to_have_attribute("data-ready", "true")
    print(f"duplicate navigation={duplicated.locator('html').get_attribute('data-navigation')}")
    expect(duplicated.locator("#draft")).to_have_value("")
    assert duplicated.locator("html").get_attribute("data-tab") != original.locator("html").get_attribute("data-tab")
    expect(original.locator("#draft")).to_have_value("original draft")


def test_browser_restart_restore_discards_closed_drafts(browser_session, tmp_path):
    _, _, url, playwright = browser_session
    profile = tmp_path / "restart-profile"
    options = {
        "executable_path": playwright.chromium.executable_path,
        "headless": False,
        "args": ["--restore-last-session"],
    }
    first = playwright.chromium.launch_persistent_context(profile, **options)
    try:
        page = open_fixture(first, url + "?restart-proof")
        page.locator("#draft").fill("closed session draft")
    finally:
        first.close()
    restored = playwright.chromium.launch_persistent_context(profile, **options)
    try:
        page = next(page for page in restored.pages if "restart-proof" in page.url)
        expect(page.locator("html")).to_have_attribute("data-ready", "true")
        print(f"restart navigation={page.locator('html').get_attribute('data-navigation')}")
        expect(page.locator("#draft")).to_have_value("")
    finally:
        restored.close()
