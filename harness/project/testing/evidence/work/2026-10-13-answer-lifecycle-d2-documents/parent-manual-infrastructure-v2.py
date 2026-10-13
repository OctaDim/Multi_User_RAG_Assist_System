import sys,os,asyncio,socket,tempfile,subprocess,time,atexit
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen
sys.path.insert(0,'/home/octadim/MyProjects/Multi_User_RAG_Assist_System/backend/tests')
from mailbox import Mailbox
import pgserver
from app.db import migrate
from playwright.sync_api import sync_playwright
root=Path('/home/octadim/MyProjects/Multi_User_RAG_Assist_System')
evidence=root/'harness/project/testing/evidence/work/2026-10-13-answer-lifecycle-d2-documents'
server=pgserver.get_server(Path(tempfile.mkdtemp(prefix='rag-d2-manual-')),cleanup_mode='stop')
os.environ['RAG_DATABASE_URL']=server.get_uri()
asyncio.run(migrate(server.get_uri()))
with socket.socket() as reservation:
 reservation.bind(('127.0.0.1',0));api_port=reservation.getsockname()[1]
api_url=f'http://127.0.0.1:{api_port}'
class Static(SimpleHTTPRequestHandler):
 def __init__(self,*a,**k):super().__init__(*a,directory=str(root/'frontend'),**k)
 def log_message(self,*a):pass
 def do_GET(self):
  if self.path in ('/','/index.html'):
   body=(root/'frontend/index.html').read_text().replace('http://127.0.0.1:8000',api_url).encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
  else:super().do_GET()
static=ThreadingHTTPServer(('127.0.0.1',0),Static);thread=Thread(target=static.serve_forever,daemon=True);thread.start()
frontend=f'http://127.0.0.1:{static.server_port}'
mailbox=Mailbox();mailbox.__enter__()
os.environ.update(RAG_FRONTEND_ORIGIN=frontend,RAG_SMTP_HOST='127.0.0.1',RAG_SMTP_PORT=str(mailbox.smtp.server_address[1]),RAG_SMTP_SECURITY='plain',RAG_SMTP_FROM='accounts@owned.test')
os.environ.update(RAG_ORIGINALS_DIR=tempfile.mkdtemp(prefix='rag-d2-manual-originals-'),RAG_E5_DIR='/tmp/rag-answer-lifecycle-models/e5',RAG_OCR_DIR='/tmp/rag-answer-lifecycle-models/ocr')
api_log=(evidence/'parent-manual-api-v2.txt').open('x')
api_process=subprocess.Popen([str(root/'backend/.venv/bin/rag-api'),'--port',str(api_port)],cwd=root/'backend',env=os.environ.copy(),stdout=api_log,stderr=subprocess.STDOUT,start_new_session=True)
for attempt in range(100):
 try:
  with urlopen(api_url+'/openapi.json',timeout=.5):break
 except OSError:time.sleep(.1)
else:raise RuntimeError('manual API did not start')
worker_log=(evidence/'parent-manual-worker-v2.txt').open('x')
worker_process=subprocess.Popen([str(root/'backend/.venv/bin/rag-documents')],cwd=root/'backend',env=os.environ.copy(),stdout=worker_log,stderr=subprocess.STDOUT,start_new_session=True)
playwright=sync_playwright().start();browser=playwright.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1280,'height':900});page=context.new_page()
def cleanup():
 browser.close();playwright.stop();api_process.terminate()
 try:api_process.wait(10)
 except subprocess.TimeoutExpired:api_process.kill();api_process.wait(10)
 worker_process.terminate()
 try:worker_process.wait(15)
 except subprocess.TimeoutExpired:worker_process.kill();worker_process.wait(10)
 worker_log.close();api_log.close();static.shutdown();static.server_close();thread.join();mailbox.__exit__();server.cleanup()
 print('All owned manual browser/API/static/SMTP/PostgreSQL resources reaped.',flush=True)
atexit.register(cleanup)
print('Fresh migrated DB; no account/session/document fixture inserts. Manual browser ready. Frontend',frontend,'mailbox',mailbox.http.server_port,flush=True)
