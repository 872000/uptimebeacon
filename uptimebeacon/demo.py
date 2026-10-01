"""Offline demo mode: scripted up/down/latency scenarios, zero network.

`run_demo()` writes a demo config, replays ~48h of 5-minute checks for three
services (including a scripted 45-minute API outage that becomes a real
incident in the SQLite log), and renders the static status page — so the
entire pipeline works end-to-end on a plane with no wifi.
"""

from __future__ import annotations

import os
import random
import time

from . import statuspage
from .config import AppConfig, Target, save_config
from .store import Store

STEP_S = 300          # 5-minute check cadence in the scripted history
HISTORY_S = 48 * 3600  # 48 hours of history

DEMO_TARGETS = [
    Target(name="website", url="https://website.example.com",
           interval=300, timeout=10, expected_status=[200]),
    Target(name="api", url="https://api.example.com/health",
           interval=300, timeout=10, expected_status=[200], keyword="ok"),
    Target(name="database", url="https://db.example.com/ping",
           interval=300, timeout=10, expected_status=[200]),
]


def _scenario(target_name: str, ts: float, anchor: float, rng: random.Random):
    """Return (ok, latency_ms, status_code, error) for a scripted moment."""
    age = anchor - ts  # seconds ago
    if target_name == "website":
        return True, rng.uniform(110, 190), 200, None
    if target_name == "api":
        # Scripted incident: API down 26h -> 25h15m ago (45 minutes).
        if 25 * 3600 + 15 * 60 <= age <= 26 * 3600:
            return False, None, 503, "unexpected status 503"
        jitter = rng.uniform(180, 260)
        # A brief wobble right after recovery.
        if 24 * 3600 <= age <= 25 * 3600:
            jitter += rng.uniform(0, 120)
        return True, jitter, 200, None
    if target_name == "database":
        latency = rng.uniform(8, 22)
        if rng.random() < 0.04:  # occasional slow query spike
            latency += rng.uniform(150, 400)
        return True, latency, 200, None
    raise AssertionError(f"unknown demo target {target_name!r}")


def run_demo(out_dir: str, seed: int = 42, quiet: bool = False) -> dict:
    """Run the full offline demo. Returns paths of generated artifacts."""
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(seed)
    anchor = time.time()

    config_path = os.path.join(out_dir, "demo-config.yaml")
    db_path = os.path.join(out_dir, "demo.db")
    page_path = os.path.join(out_dir, "status.html")
    for stale in (db_path,):
        if os.path.exists(stale):
            os.remove(stale)

    config = AppConfig(database=db_path, targets=DEMO_TARGETS)
    save_config(config, config_path)

    total_checks = 0
    entries = []
    with Store(db_path) as store:
        ts = anchor - HISTORY_S
        while ts <= anchor:
            for target in DEMO_TARGETS:
                ok, latency_ms, status_code, error = _scenario(
                    target.name, ts, anchor, rng)
                entries.append((target.name, ts, ok, latency_ms,
                                status_code, error))
                total_checks += 1
            ts += STEP_S
        # One final "live" round stamped at the anchor so the page looks fresh.
        for target in DEMO_TARGETS:
            ok, latency_ms, status_code, error = _scenario(
                target.name, anchor, anchor, rng)
            entries.append((target.name, anchor, ok, latency_ms,
                            status_code, error))
            total_checks += 1
        store.log_many(entries)  # single transaction: fast even on slow disks

        statuspage.generate(store, DEMO_TARGETS, page_path,
                            title="UptimeBeacon Demo Status")
        incidents = store.get_incidents()
        open_now = store.open_incidents()

    if not quiet:
        print(f"demo: replayed {total_checks} scripted checks "
              f"({len(DEMO_TARGETS)} targets x 48h @ 5min)")
        print(f"demo: {len(incidents)} incident(s) in log, "
              f"{len(open_now)} currently open")
        for inc in incidents:
            state = "OPEN" if inc.is_open else "resolved"
            print(f"      [{state}] {inc.target}: "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(inc.started_at))}")
        print(f"demo: config -> {config_path}")
        print(f"demo: sqlite -> {db_path}")
        print(f"demo: status page -> {page_path}")
    return {
        "config": config_path,
        "db": db_path,
        "status_page": page_path,
        "checks": total_checks,
        "incidents": len(incidents),
    }
