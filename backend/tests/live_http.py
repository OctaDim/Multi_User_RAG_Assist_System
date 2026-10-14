"""Test client over a real socket and production H11, retaining in-process patches."""
import socket
from threading import Thread
import time

import httpx
import uvicorn

from app.handoff import GuardedH11Protocol


class LiveClient:
    __test__ = False
    def __init__(self, app):
        self.app = app

    def __enter__(self):
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(128)
        self.server = uvicorn.Server(uvicorn.Config(self.app, http=GuardedH11Protocol,
            loop='asyncio', log_level='error', access_log=False, timeout_graceful_shutdown=2))
        self.thread = Thread(target=self.server.run, kwargs={'sockets':[self.socket]}, daemon=True)
        self.thread.start()
        until = time.monotonic()+10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic()>until:
                raise AssertionError('Owned H11 test API did not start')
            time.sleep(.01)
        self.client = httpx.Client(base_url=f'http://127.0.0.1:{self.socket.getsockname()[1]}', timeout=30)
        return self.client

    def __exit__(self, *args):
        self.client.close()
        self.server.should_exit = True
        self.thread.join(10)
        self.socket.close()
        assert not self.thread.is_alive(), 'Owned H11 test API did not stop'
