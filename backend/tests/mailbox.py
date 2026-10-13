"""Owned local SMTP receiver and browser mailbox; never a production API shortcut."""

from email import policy
from email.parser import BytesParser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import Thread, Lock
from urllib.parse import parse_qs, urlsplit


class Mailbox:
    def __init__(self):
        self.messages = []
        self.reject_delivery = False
        self.lock = Lock()
        mailbox = self

        class SMTP(StreamRequestHandler):
            def handle(self):
                self.wfile.write(b'220 owned-test-mailbox\r\n')
                recipients = []
                while line := self.rfile.readline():
                    command = line.decode().strip()
                    verb = command.split(' ', 1)[0].upper()
                    if verb in ('EHLO', 'HELO'):
                        self.wfile.write(b'250 owned-test-mailbox\r\n')
                    elif verb == 'MAIL':
                        recipients = []
                        self.wfile.write(b'250 OK\r\n')
                    elif verb == 'RCPT':
                        address = command.split(':', 1)[1].strip(' <>')
                        if not address.endswith('.test'):
                            self.wfile.write(b'550 owned .test recipients only\r\n')
                            continue
                        recipients.append(address)
                        self.wfile.write(b'250 OK\r\n')
                    elif verb == 'DATA':
                        self.wfile.write(b'354 End with dot\r\n')
                        body = b''
                        while (line := self.rfile.readline()) != b'.\r\n':
                            if not line:
                                return
                            body += line[1:] if line.startswith(b'..') else line
                        message = BytesParser(policy=policy.default).parsebytes(body)
                        if mailbox.reject_delivery:
                            self.wfile.write(b'550 Owned delivery failure\r\n')
                            continue
                        with mailbox.lock:
                            for recipient in recipients:
                                mailbox.messages.append((recipient, message.get_content()))
                        self.wfile.write(b'250 Delivered\r\n')
                    elif verb == 'QUIT':
                        self.wfile.write(b'221 Bye\r\n')
                        return
                    else:
                        self.wfile.write(b'250 OK\r\n')

        class HTTP(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                email = parse_qs(urlsplit(self.path).query).get('email', [''])[0]
                with mailbox.lock:
                    messages = [body for recipient, body in mailbox.messages if recipient == email]
                links = [re.search(r'https?://\S+', body).group() for body in messages]
                body = ('<!doctype html><title>Owned test mailbox</title><h1>Mailbox</h1>' +
                        ''.join(f'<p><a href="{escape(link, quote=True)}">Verify email</a></p>' for link in links)).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)

        self.smtp = ThreadingTCPServer(('127.0.0.1', 0), SMTP)
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), HTTP)
        self.threads = [Thread(target=server.serve_forever, daemon=True) for server in (self.smtp, self.http)]

    def __enter__(self):
        for thread in self.threads:
            thread.start()
        return self

    def __exit__(self, *args):
        for server in (self.smtp, self.http):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()

    def link(self, email):
        with self.lock:
            body = next(body for recipient, body in reversed(self.messages) if recipient == email)
        return re.search(r'https?://\S+', body).group()

    def configure(self, monkeypatch, frontend='http://127.0.0.1:8999'):
        monkeypatch.setenv('RAG_SMTP_HOST', '127.0.0.1')
        monkeypatch.setenv('RAG_SMTP_PORT', str(self.smtp.server_address[1]))
        monkeypatch.setenv('RAG_SMTP_SECURITY', 'plain')
        monkeypatch.setenv('RAG_SMTP_FROM', 'accounts@owned.test')
        monkeypatch.setenv('RAG_FRONTEND_ORIGIN', frontend)
