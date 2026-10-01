"""Generate the images used in the README.

- docs/hero.png:        designed banner (pure matplotlib artwork)
- docs/demo-status.png: REAL dashboard rendered from an actual demo run —
                        `python -m uptimebeacon demo` replays 48h of scripted
                        checks into SQLite, and this script charts that data.

Usage:  python scripts/render_images.py --demo-dir <dir>
The demo itself is offline; only matplotlib is needed for rendering.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

from uptimebeacon import demo as demo_mod
from uptimebeacon import stats as stats_mod

BG = "#0b1220"
INK = "#e8eefc"
MUTED = "#8fa1c2"
GREEN = "#34d399"
RED = "#f87171"
AMBER = "#fbbf24"
COLORS = {"website": "#60a5fa", "api": GREEN, "database": AMBER}


def make_hero(path: str) -> None:
    fig, ax = plt.subplots(figsize=(12, 6.3), dpi=100)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.3)
    ax.axis("off")

    # Beacon pulse rings, top-right.
    cx, cy = 9.6, 3.1
    for r, alpha in ((2.3, 0.10), (1.7, 0.16), (1.15, 0.24)):
        ax.add_patch(Circle((cx, cy), r, color=GREEN, alpha=alpha, lw=0))
    ax.add_patch(Circle((cx, cy), 0.55, color=GREEN, alpha=0.95, lw=0))
    ax.add_patch(Circle((cx, cy), 0.55, color="white", alpha=0.25, lw=0))
    # A tiny "down" blip for story: one red tick in the rings.
    ax.plot([cx + 1.7, cx + 1.7], [cy - 0.28, cy + 0.28],
            color=RED, lw=4, solid_capstyle="round")

    ax.text(0.7, 3.9, "UptimeBeacon", fontsize=52, weight="bold", color=INK,
            va="center", ha="left", family="sans-serif")
    ax.text(0.7, 3.05, "Know the second your site goes down.",
            fontsize=22, color=MUTED, va="center", ha="left")
    ax.text(0.7, 2.45, "Uptime monitoring  •  incident log  •  static status page",
            fontsize=15, color=MUTED, alpha=0.8, va="center", ha="left")

    # Pill badges row.
    pills = ["stdlib-only", "SQLite incidents", "zero-config demo"]
    x = 0.7
    for pill in pills:
        ax.text(x, 1.55, f"  {pill}  ", fontsize=13, color=GREEN,
                va="center", ha="left",
                bbox=dict(boxstyle="round,pad=0.35", fc="#0e2a1f",
                          ec=GREEN, alpha=0.9))
        x += len(pill) * 0.115 + 0.55

    ax.text(0.7, 0.55, "python -m uptimebeacon demo", fontsize=14,
            color=INK, va="center", ha="left", family="monospace",
            bbox=dict(boxstyle="round,pad=0.4", fc="#141d31", ec="#24314f"))
    fig.tight_layout(pad=0.6)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    print(f"wrote {path}")


def _load_rows(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    targets = [r["target"] for r in
               conn.execute("SELECT DISTINCT target FROM checks ORDER BY target")]
    data = {}
    for t in targets:
        data[t] = conn.execute(
            "SELECT * FROM checks WHERE target = ? ORDER BY ts ASC", (t,)).fetchall()
    conn.close()
    return targets, data


def make_dashboard(db_path: str, path: str) -> None:
    targets, data = _load_rows(db_path)
    now = max(r["ts"] for rows in data.values() for r in rows)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), dpi=100,
                                   gridspec_kw={"height_ratios": [3, 2]})
    fig.patch.set_facecolor(BG)
    for ax in (ax1, ax2):
        ax.set_facecolor("#0e1626")
        ax.tick_params(colors=MUTED)
        for spine in ax.spines.values():
            spine.set_color("#24314f")

    # --- latency time series (real check rows) ---
    for t in targets:
        rows = data[t]
        ok_ts = [datetime.datetime.fromtimestamp(r["ts"]) for r in rows if r["ok"]]
        ok_lat = [r["latency_ms"] for r in rows if r["ok"]]
        bad_ts = [datetime.datetime.fromtimestamp(r["ts"]) for r in rows if not r["ok"]]
        ax1.plot(ok_ts, ok_lat, color=COLORS.get(t, INK), lw=1.2, label=t, alpha=0.9)
        if bad_ts:
            ax1.scatter(bad_ts, [5] * len(bad_ts), color=RED, s=26, zorder=5,
                        label=f"{t} outage" if t == "api" else None)
    ax1.set_ylabel("latency (ms)", color=MUTED)
    ax1.set_title("Latency — last 48 hours of scripted checks", color=INK,
                  fontsize=14, weight="bold", loc="left", pad=12)
    ax1.legend(facecolor="#141d31", edgecolor="#24314f", labelcolor=INK,
               fontsize=10, loc="upper right")
    ax1.grid(color="#1a2440", alpha=0.6, lw=0.6)

    # --- uptime % bars per window (computed by the real stats module) ---
    labels = list(stats_mod.WINDOWS)
    x = range(len(targets))
    width = 0.22
    for i, window in enumerate(labels):
        vals = []
        for t in targets:
            up = stats_mod.uptime_windows(data[t], now=now)[window]
            vals.append(up if up is not None else 0.0)
        bars = ax2.bar([p + (i - 1) * width for p in x], vals, width,
                       label=window, color=[GREEN, "#60a5fa", AMBER][i],
                       edgecolor="none")
        for bar, v in zip(bars, vals):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.4,
                     f"{v:.1f}%", ha="center", va="bottom", fontsize=9, color=INK)
    ax2.set_ylim(0, 112)
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(targets, color=INK)
    ax2.set_ylabel("uptime %", color=MUTED)
    ax2.set_title("Uptime by window", color=INK, fontsize=14, weight="bold",
                  loc="left", pad=12)
    ax2.legend(facecolor="#141d31", edgecolor="#24314f", labelcolor=INK,
               fontsize=10, loc="lower right")
    ax2.grid(axis="y", color="#1a2440", alpha=0.6, lw=0.6)

    fig.suptitle("UptimeBeacon — live demo data (offline, scripted, deterministic)",
                 color=MUTED, fontsize=11, y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    print(f"wrote {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-dir", required=True,
                    help="directory holding demo.db from `uptimebeacon demo`")
    ap.add_argument("--docs-dir", default="docs")
    args = ap.parse_args()

    db_path = os.path.join(args.demo_dir, "demo.db")
    if not os.path.exists(db_path):
        print(f"running offline demo into {args.demo_dir} ...")
        demo_mod.run_demo(args.demo_dir, quiet=True)

    os.makedirs(args.docs_dir, exist_ok=True)
    make_hero(os.path.join(args.docs_dir, "hero.png"))
    make_dashboard(db_path, os.path.join(args.docs_dir, "demo-status.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
