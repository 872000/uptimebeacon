"""Tests for the static status-page generator."""

import re
import time

from uptimebeacon import statuspage
from uptimebeacon.config import Target
from uptimebeacon.store import Incident, Store


def _service(name, status="ok"):
    return {
        "name": name,
        "url": f"https://{name}.example.com",
        "status": status,
        "latest": {"ts": time.time(), "ok": status == "ok"},
        "uptime": {"24h": 99.5, "7d": 99.9, "30d": None},
        "latency": {"avg_ms": 123.4, "p95_ms": 210.0,
                    "min_ms": 90.0, "max_ms": 300.0, "count": 42},
        "spark": [(1.0, 100.0), (2.0, None), (3.0, 120.0)],
    }


def test_page_contains_services_and_incidents():
    now = time.time()
    incidents = [
        Incident(id=1, target="api", started_at=now - 3600,
                 ended_at=now - 1800, cause="unexpected status 503"),
        Incident(id=2, target="web", started_at=now - 60,
                 ended_at=None, cause="connection failed"),
    ]
    page = statuspage.build_status_page(
        [_service("api", "ok"), _service("web", "bad")], incidents)
    assert "<!DOCTYPE html>" in page
    assert "api" in page and "web" in page
    assert "99.50%" in page
    assert "Major outage in progress" in page  # open incident present
    assert "OPEN" in page and "RESOLVED" in page
    assert "unexpected status 503" in page
    # No external assets: the page must not fetch anything over the network.
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', page)


def test_all_operational_banner():
    page = statuspage.build_status_page([_service("api")], [])
    assert "All systems operational" in page
    assert "No incidents recorded" in page


def test_sparkline_handles_gaps_and_empty():
    svg = statuspage.sparkline_svg([(1.0, 100.0), (2.0, None), (3.0, 120.0)])
    assert "<svg" in svg and 'stroke="#f87171"' in svg  # red gap tick
    assert "no data yet" in statuspage.sparkline_svg([])
    assert "no successful checks" in statuspage.sparkline_svg([(1.0, None)])


def test_generate_writes_self_contained_file(tmp_path):
    db = str(tmp_path / "t.db")
    out = str(tmp_path / "status.html")
    with Store(db) as store:
        now = time.time()
        store.log_check("api", now - 60, True, 120.0, 200, None)
        store.log_check("api", now, True, 130.0, 200, None)
        statuspage.generate(store, [Target(name="api", url="https://a.io")], out)
    text = open(out, encoding="utf-8").read()
    assert "api" in text and "All systems operational" in text


def test_html_escapes_target_names():
    evil = _service('<script>alert("x")</script>')
    page = statuspage.build_status_page([evil], [])
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
