"""Tests for the SQLite store: checks + automatic incident open/close."""

import time

import pytest

from uptimebeacon.store import Store


@pytest.fixture()
def store(tmp_path):
    with Store(str(tmp_path / "test.db")) as s:
        yield s


def test_incident_opens_on_failure_and_closes_on_recovery(store):
    t0 = time.time()
    store.log_check("api", t0, True, 120.0, 200, None)
    assert store.open_incidents() == []

    # Two consecutive failures -> exactly ONE open incident.
    store.log_check("api", t0 + 60, False, None, 503, "unexpected status 503")
    store.log_check("api", t0 + 120, False, None, 503, "unexpected status 503")
    open_now = store.open_incidents()
    assert len(open_now) == 1
    assert open_now[0].target == "api"
    assert open_now[0].started_at == t0 + 60
    assert open_now[0].cause == "unexpected status 503"

    # Recovery closes it.
    store.log_check("api", t0 + 180, True, 140.0, 200, None)
    assert store.open_incidents() == []
    incidents = store.get_incidents()
    assert len(incidents) == 1
    assert incidents[0].ended_at == t0 + 180
    assert incidents[0].duration_s == pytest.approx(120.0)


def test_incidents_are_per_target(store):
    t0 = time.time()
    store.log_check("api", t0, False, None, 500, "boom")
    store.log_check("web", t0, False, None, 500, "boom")
    assert len(store.open_incidents()) == 2
    store.log_check("api", t0 + 60, True, 100.0, 200, None)
    assert [i.target for i in store.open_incidents()] == ["web"]


def test_get_checks_and_targets(store):
    t0 = time.time()
    store.log_check("api", t0 - 10, True, 100.0, 200, None)
    store.log_check("api", t0, False, None, 500, "x")
    store.log_check("web", t0, True, 50.0, 200, None)
    assert len(store.get_checks("api")) == 2
    assert len(store.get_checks("api", since=t0 - 5)) == 1
    assert store.targets() == ["api", "web"]
    latest = store.latest_check("api")
    assert latest["ok"] == 0 and latest["status_code"] == 500
