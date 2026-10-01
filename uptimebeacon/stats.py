"""Latency and uptime statistics computed from stored check rows."""

from __future__ import annotations

import math
import time

# Named windows shown on the status page.
WINDOWS = {
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
    "30d": 30 * 24 * 3600,
}


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (e.g. p95). Returns None for empty input."""
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(pct / 100.0 * len(ordered))
    return ordered[max(0, min(rank - 1, len(ordered) - 1))]


def latency_stats(rows, max_points: int = 500) -> dict:
    """Rolling latency summary over (successful) check rows."""
    latencies = [r["latency_ms"] for r in rows
                 if r["ok"] and r["latency_ms"] is not None]
    recent = latencies[-max_points:]
    if not recent:
        return {"count": 0, "avg_ms": None, "p95_ms": None,
                "min_ms": None, "max_ms": None}
    return {
        "count": len(recent),
        "avg_ms": sum(recent) / len(recent),
        "p95_ms": percentile(recent, 95),
        "min_ms": min(recent),
        "max_ms": max(recent),
    }


def uptime_windows(rows, now: float | None = None) -> dict[str, float | None]:
    """Uptime % per named window. None means 'no data in window'."""
    now = time.time() if now is None else now
    result: dict[str, float | None] = {}
    for label, span in WINDOWS.items():
        window_rows = [r for r in rows if r["ts"] >= now - span]
        if not window_rows:
            result[label] = None
        else:
            ok = sum(1 for r in window_rows if r["ok"])
            result[label] = ok / len(window_rows) * 100.0
    return result


def sparkline_points(rows, max_points: int = 60) -> list[tuple[float, float | None]]:
    """Downsampled (ts, latency_ms|None) series for the status-page sparkline.

    Failed checks are represented as None so the chart shows gaps.
    """
    if not rows:
        return []
    step = max(1, len(rows) // max_points)
    sampled = rows[::step]
    return [(r["ts"], r["latency_ms"] if r["ok"] else None) for r in sampled]
