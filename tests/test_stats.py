"""Tests for latency stats, uptime windows and sparklines."""

import time

import pytest

from uptimebeacon import stats


def _rows(specs, base=None):
    """specs: list of (age_seconds, ok, latency_ms)."""
    base = time.time() if base is None else base
    return [
        {"ts": base - age, "ok": ok, "latency_ms": lat}
        for age, ok, lat in specs
    ]


def test_percentile():
    assert stats.percentile([], 95) is None
    assert stats.percentile([5.0], 95) == 5.0
    vals = list(range(1, 101))
    assert stats.percentile(vals, 95) == 95
    assert stats.percentile(vals, 50) == 50


def test_latency_stats_ignores_failures():
    rows = _rows([(10, True, 100.0), (20, True, 200.0), (30, False, None)])
    s = stats.latency_stats(rows)
    assert s["count"] == 2
    assert s["avg_ms"] == 150.0
    assert s["min_ms"] == 100.0 and s["max_ms"] == 200.0
    assert s["p95_ms"] == 200.0


def test_latency_stats_empty():
    s = stats.latency_stats([])
    assert s["count"] == 0 and s["avg_ms"] is None


def test_uptime_windows():
    now = time.time()
    # 10 recent checks (all inside 24h): 8 ok, 2 failed.
    rows = _rows([(i * 60, i >= 2, 100.0) for i in range(10)], base=now)
    # Plus an old failure 10 days ago (inside 30d, outside 7d).
    rows.append({"ts": now - 10 * 86400, "ok": False, "latency_ms": None})
    up = stats.uptime_windows(rows, now=now)
    assert up["24h"] == pytest.approx(80.0)
    assert up["7d"] == pytest.approx(80.0)
    assert up["30d"] == pytest.approx(8 / 11 * 100.0)


def test_uptime_windows_no_data():
    up = stats.uptime_windows([], now=time.time())
    assert all(v is None for v in up.values())


def test_sparkline_points_marks_failures_as_gaps():
    rows = _rows([(30, True, 120.0), (20, False, None), (10, True, 130.0)])
    pts = stats.sparkline_points(rows)
    assert pts[0][1] == 120.0
    assert pts[1][1] is None
    assert pts[2][1] == 130.0
    assert stats.sparkline_points([]) == []
