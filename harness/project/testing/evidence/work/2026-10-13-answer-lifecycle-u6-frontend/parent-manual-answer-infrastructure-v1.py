"""Fresh service infrastructure for the agent-driven manual U6 browser walkthrough."""
import asyncio
import atexit
from contextlib import ExitStack
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time
from urllib.request import urlopen

import pgserver
import psycopg
from playwright.sync_api import sync_playwright
from app.db import migrate

root = Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System')
evidence = root/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-u6-frontend'
sys.path.insert(0, str(root/'backend/tests'))
from mailbox import Mailbox

stack = ExitStack()
atexit.register(stack.close)
stack.callback(print, 'All owned manual browser/API/document/generation/static/SMTP/PostgreSQL resources reaped.', flush=True)
server = pgserver.get_server(Path(tempfile.mkdtemp(prefix='rag-u6-manual-')), cleanup_mode='stop')
stack.callback(server.cleanup)
os.environ['RAG_DATABASE_URL'] = server.get_uri()
asyncio.run(migrate(server.get_uri()))
with psycopg.connect(server.get_uri()) as connection:
    assert connection.execute('SELECT count(*) FROM accounts').fetchone()[0] == 0
    assert connection.execute('SELECT count(*) FROM documents').fetchone()[0] == 0

with socket.socket() as reservation:
    reservation.bind(('127.0.0.1', 0))
    api_port = reservation.getsockname()[1]
api_url = f'http://127.0.0.1:{api_port}'

class Static(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(root/'frontend'), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.split('?', 1)[0] in ('/', '/index.html'):
            body = (root/'frontend/index.html').read_text().replace('http://127.0.0.1:8000', api_url).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

static = ThreadingHTTPServer(('127.0.0.1', 0), Static)
thread = Thread(target=static.serve_forever, daemon=True)
thread.start()
stack.callback(thread.join)
stack.callback(static.server_close)
stack.callback(static.shutdown)
frontend = f'http://127.0.0.1:{static.server_port}'
mailbox = stack.enter_context(Mailbox())
models = root/'backend/.venv/rag-native-models'
os.environ.update(RAG_FRONTEND_ORIGIN=frontend, RAG_SMTP_HOST='127.0.0.1',
    RAG_SMTP_PORT=str(mailbox.smtp.server_address[1]), RAG_SMTP_SECURITY='plain',
    RAG_SMTP_FROM='accounts@owned.test', RAG_ORIGINALS_DIR=tempfile.mkdtemp(prefix='rag-u6-manual-originals-'),
    RAG_MODEL_PATH=str(models/'Qwen3.5-2B-Q4_K_M.gguf'), RAG_E5_DIR=str(models/'e5'), RAG_OCR_DIR=str(models/'ocr'))

def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(10)

processes = []
for command, label, arguments in [('rag-api', 'api', ['--port', str(api_port)]),
                                  ('rag-documents', 'document-worker', []), ('rag-generation', 'generation', [])]:
    log = stack.enter_context((evidence/f'2026-10-14-manual-answer-{label}-v1.log').open('x'))
    process = subprocess.Popen([str(root/'backend/.venv/bin'/command), *arguments], cwd=root/'backend',
        env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
    processes.append(process)
    stack.callback(stop, process)

deadline = time.monotonic()+30
while True:
    assert all(process.poll() is None for process in processes), 'An owned service exited during manual startup'
    try:
        with urlopen(api_url+'/openapi.json', timeout=.5):
            pass
        with psycopg.connect(server.get_uri()) as connection:
            healthy = connection.execute('SELECT healthy_until>clock_timestamp() FROM coordinator_lease WHERE id=1').fetchone()[0]
        if healthy:
            break
    except OSError:
        pass
    if time.monotonic() > deadline:
        raise RuntimeError('Owned manual services did not become ready')
    time.sleep(.1)

playwright = stack.enter_context(sync_playwright())
browser = playwright.chromium.launch(headless=False)
stack.callback(browser.close)
context = browser.new_context(viewport={'width':1280, 'height':900})
stack.callback(context.close)
page = context.new_page()
console_errors = []
page.on('pageerror', lambda error: console_errors.append(str(error)))
page.goto(frontend)
print('Fresh migrated DB, zero fixture accounts/documents; actual API/SMTP/document worker/native coordinator/browser ready.', flush=True)
print('Frontend:', frontend, 'Mailbox:', f'http://127.0.0.1:{mailbox.http.server_port}', flush=True)
print(page.locator('body').inner_text(), flush=True)
