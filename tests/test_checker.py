"""Tests for the urllib-based checker, against a local HTTP server.

No external network is touched: everything runs on 127.0.0.1.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from uptimebeacon.checker import check_target
from uptimebeacon.config import Target


class Handler(BaseHTTPRequestHandler):
    seen_user_agents: list[str] = []

    def do_GET(self):
        Handler.seen_user_agents.append(self.headers.get("User-Agent", ""))
        if self.path == "/ok":
            body, code = b'{"status":"ok"}', 200
        elif self.path == "/teapot":
            body, code = b"teapot", 418
        elif self.path == "/slow":
            import time as _t
            _t.sleep(2.5)
            body, code = b"late", 200
        else:
            body, code = b"nope", 404
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture(scope="module")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _target(name, url, **kw):
    defaults = dict(interval=60, timeout=5, expected_status=[200], keyword=None)
    defaults.update(kw)
    return Target(name=name, url=url, **defaults)


def test_successful_check(server):
    r = check_target(_target("ok", server + "/ok"))
    assert r.ok and r.status_code == 200
    assert r.latency_ms is not None and r.latency_ms > 0
    assert r.error is None


def test_unexpected_status_fails(server):
    r = check_target(_target("t", server + "/teapot"))
    assert not r.ok
    assert r.status_code == 418
    assert "418" in r.error


def test_keyword_match_and_mismatch(server):
    ok = check_target(_target("k", server + "/ok", keyword="ok"))
    assert ok.ok
    bad = check_target(_target("k", server + "/ok", keyword="definitely-not-here"))
    assert not bad.ok and "keyword" in bad.error


def test_connection_refused_is_a_clean_failure():
    # Port 1 on localhost is (practically) never listening.
    r = check_target(_target("dead", "http://127.0.0.1:1/", timeout=2))
    assert not r.ok
    assert r.status_code is None
    assert r.error


def test_timeout_is_a_clean_failure(server):
    r = check_target(_target("slow", server + "/slow", timeout=1))
    assert not r.ok
    assert "timed out" in r.error


def test_checker_never_raises():
    r = check_target(_target("bad-scheme", "http://[::1]:99999/", timeout=1))
    assert not r.ok


def test_user_agent_identifies_service(server):
    Handler.seen_user_agents.clear()
    r = check_target(_target("ua", server + "/ok"))
    assert r.ok
    assert any(ua.startswith("UptimeBeacon/") for ua in Handler.seen_user_agents)
