"""Tests for the CLI: add / check / incidents / status-page / demo."""

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from uptimebeacon.cli import main
from uptimebeacon.config import load_config
from uptimebeacon.store import Store


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture()
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_add_then_check_then_status_page(workdir, server, capsys):
    assert main(["--config", "c.yaml", "add", "--name", "local",
                 "--url", server + "/", "--interval", "60"]) == 0
    config = load_config("c.yaml")
    assert [t.name for t in config.targets] == ["local"]

    assert main(["--config", "c.yaml", "check"]) == 0
    out = capsys.readouterr().out
    assert "[UP  ]" in out and "local" in out

    assert main(["--config", "c.yaml", "status-page",
                 "--out", "status.html"]) == 0
    assert os.path.exists("status.html")
    with Store("uptimebeacon.db") as store:
        assert store.latest_check("local")["ok"] == 1


def test_add_rejects_duplicates(workdir):
    assert main(["--config", "c.yaml", "add", "--name", "a",
                 "--url", "https://example.com"]) == 0
    assert main(["--config", "c.yaml", "add", "--name", "a",
                 "--url", "https://example.com"]) == 1


def test_check_reports_failure_cleanly(workdir, capsys):
    main(["--config", "c.yaml", "add", "--name", "dead",
          "--url", "http://127.0.0.1:1/", "--timeout", "2"])
    assert main(["--config", "c.yaml", "check", "--target", "dead"]) == 0
    out = capsys.readouterr().out
    assert "[DOWN]" in out

    assert main(["--config", "c.yaml", "incidents"]) == 0
    out = capsys.readouterr().out
    assert "OPEN" in out and "dead" in out


def test_demo_runs_fully_offline(workdir):
    assert main(["demo", "--dir", "demo-out", "--quiet"]) == 0
    assert os.path.exists(os.path.join("demo-out", "demo.db"))
    page = os.path.join("demo-out", "status.html")
    assert os.path.exists(page)
    text = open(page, encoding="utf-8").read()
    assert "UptimeBeacon Demo Status" in text
    with Store(os.path.join("demo-out", "demo.db")) as store:
        # The scripted 45-minute API outage becomes exactly one incident.
        incidents = store.get_incidents()
        assert len(incidents) == 1
        assert incidents[0].target == "api"
        assert not incidents[0].is_open  # auto-closed on recovery
        assert 40 * 60 <= incidents[0].duration_s <= 50 * 60
        assert len(store.get_checks("website")) > 500  # ~48h @ 5min


def test_watch_runs_bounded_iterations(workdir, server):
    main(["--config", "c.yaml", "add", "--name", "local",
          "--url", server + "/", "--interval", "1"])
    assert main(["--config", "c.yaml", "watch", "--iterations", "2"]) == 0
    with Store("uptimebeacon.db") as store:
        assert len(store.get_checks("local")) >= 2
