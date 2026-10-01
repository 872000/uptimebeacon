"""Static status-page generator.

Produces ONE self-contained HTML file: all CSS and charts are inline,
so the page can be dropped onto any static host (GitHub Pages, S3, nginx)
with zero backend and zero external requests.
"""

from __future__ import annotations

import datetime
import html
import time

from . import stats as stats_mod

CSS = """
:root { --bg:#0b1220; --card:#141d31; --ink:#e8eefc; --muted:#8fa1c2;
        --ok:#34d399; --warn:#fbbf24; --bad:#f87171; --line:#24314f; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
       Helvetica,Arial,sans-serif; background:var(--bg); color:var(--ink); }
.wrap { max-width:960px; margin:0 auto; padding:32px 20px 64px; }
.banner { border-radius:14px; padding:22px 26px; margin-bottom:28px;
          display:flex; align-items:center; gap:16px;
          background:linear-gradient(135deg,#0e2a1f,#123); border:1px solid var(--line); }
.banner.bad  { background:linear-gradient(135deg,#3a1414,#1c0f0f); }
.banner.warn { background:linear-gradient(135deg,#3a2c10,#1c170c); }
.dot { width:18px; height:18px; border-radius:50%; background:var(--ok);
       box-shadow:0 0 14px var(--ok); flex:none; }
.banner.bad .dot  { background:var(--bad);  box-shadow:0 0 14px var(--bad); }
.banner.warn .dot { background:var(--warn); box-shadow:0 0 14px var(--warn); }
.banner h1 { margin:0; font-size:24px; }
.banner p { margin:4px 0 0; color:var(--muted); font-size:14px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
        gap:18px; margin-bottom:32px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:18px 20px; }
.card h2 { margin:0 0 2px; font-size:18px; display:flex; align-items:center; gap:10px; }
.card .url { color:var(--muted); font-size:12px; word-break:break-all; }
.sdot { width:11px; height:11px; border-radius:50%; display:inline-block; }
.sdot.ok { background:var(--ok); } .sdot.bad { background:var(--bad); }
.sdot.unknown { background:var(--muted); }
.metrics { display:flex; gap:18px; margin:12px 0 6px; flex-wrap:wrap; }
.metric .v { font-size:20px; font-weight:700; }
.metric .k { font-size:11px; color:var(--muted); text-transform:uppercase;
             letter-spacing:.06em; }
.spark { margin-top:10px; }
.spark svg { width:100%; height:56px; display:block; }
h3 { font-size:16px; margin:0 0 12px; color:var(--muted);
     text-transform:uppercase; letter-spacing:.08em; }
.inc { background:var(--card); border:1px solid var(--line); border-radius:10px;
       padding:12px 16px; margin-bottom:10px; font-size:14px; }
.inc .t { font-weight:700; }
.inc .meta { color:var(--muted); font-size:12px; margin-top:4px; }
.inc .cause { color:var(--warn); }
.open { border-color:var(--bad); }
.pill { display:inline-block; font-size:11px; font-weight:700; padding:2px 10px;
        border-radius:999px; margin-left:8px; vertical-align:middle; }
.pill.open { background:#3a1414; color:var(--bad); border:1px solid var(--bad); }
.pill.closed { background:#0e2a1f; color:var(--ok); border:1px solid var(--ok); }
.empty { color:var(--muted); font-size:14px; }
footer { margin-top:40px; color:var(--muted); font-size:12px; text-align:center; }
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _fmt_dt(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def sparkline_svg(points: list[tuple[float, float | None]],
                  width: int = 280, height: int = 56) -> str:
    """Inline SVG latency sparkline; gaps (None) are drawn as red ticks."""
    if not points:
        return '<div class="empty">no data yet</div>'
    vals = [v for _, v in points if v is not None]
    if not vals:
        return '<div class="empty">no successful checks yet</div>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = len(points)
    step_x = width / max(1, n - 1)

    def xy(i, v):
        x = i * step_x
        y = height - 6 - ((v - lo) / span) * (height - 16)
        return x, y

    path, started = [], False
    for i, (_, v) in enumerate(points):
        if v is None:
            started = False
            continue
        x, y = xy(i, v)
        path.append(f"{'M' if not started else 'L'}{x:.1f},{y:.1f}")
        started = True

    ticks = "".join(
        f'<line x1="{i * step_x:.1f}" y1="{height - 8}" x2="{i * step_x:.1f}"'
        f' y2="{height - 2}" stroke="#f87171" stroke-width="2"/>'
        for i, (_, v) in enumerate(points) if v is None
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none"'
        f' role="img" aria-label="latency sparkline">'
        f'<path d="{" ".join(path)}" fill="none" stroke="#34d399"'
        f' stroke-width="1.6"/>{ticks}</svg>'
    )


def _service_status(latest) -> str:
    if latest is None:
        return "unknown"
    return "ok" if latest["ok"] else "bad"


def build_status_page(services: list[dict], incidents: list,
                      generated_at: float | None = None,
                      title: str = "UptimeBeacon Status") -> str:
    """Render the full status page HTML.

    `services`: list of dicts with keys name, url, latest (check row or None),
    uptime (dict of window->pct), latency (latency_stats dict), spark (points).
    `incidents`: list of Incident objects (newest first).
    """
    generated_at = time.time() if generated_at is None else generated_at

    open_count = sum(1 for i in incidents if i.is_open)
    any_bad = any(s["status"] == "bad" for s in services)
    if open_count or any_bad:
        banner_class, banner_title = "bad", "Major outage in progress"
    elif any(s["status"] == "unknown" for s in services):
        banner_class, banner_title = "warn", "Some services have no data yet"
    else:
        banner_class, banner_title = "", "All systems operational"
    banner_sub = (f"{open_count} open incident{'s' if open_count != 1 else ''}"
                  if open_count else
                  f"{len(services)} service{'s' if len(services) != 1 else ''} monitored")

    cards = []
    for s in services:
        up = s["uptime"]
        lat = s["latency"]

        def pct(label):
            v = up.get(label)
            return f"{v:.2f}%" if v is not None else "—"

        def ms(v):
            return f"{v:.0f} ms" if v is not None else "—"

        last_txt = _fmt_dt(s["latest"]["ts"]) if s["latest"] else "never"
        cards.append(f"""
        <div class="card">
          <h2><span class="sdot {s['status']}"></span>{_esc(s['name'])}</h2>
          <div class="url">{_esc(s['url'])}</div>
          <div class="metrics">
            <div class="metric"><div class="v">{pct('24h')}</div><div class="k">uptime 24h</div></div>
            <div class="metric"><div class="v">{pct('30d')}</div><div class="k">uptime 30d</div></div>
            <div class="metric"><div class="v">{ms(lat['avg_ms'])}</div><div class="k">avg latency</div></div>
            <div class="metric"><div class="v">{ms(lat['p95_ms'])}</div><div class="k">p95 latency</div></div>
          </div>
          <div class="spark">{sparkline_svg(s['spark'])}</div>
          <div class="url">last check: {last_txt}</div>
        </div>""")

    if incidents:
        inc_html = []
        for inc in incidents[:20]:
            pill = ('<span class="pill open">OPEN</span>' if inc.is_open
                    else '<span class="pill closed">RESOLVED</span>')
            end_txt = _fmt_dt(inc.ended_at) if inc.ended_at else "ongoing"
            cause = (f'<div class="cause">cause: {_esc(inc.cause)}</div>'
                     if inc.cause else "")
            inc_html.append(f"""
        <div class="inc{' open' if inc.is_open else ''}">
          <span class="t">{_esc(inc.target)}</span>{pill}
          {cause}
          <div class="meta">started {_fmt_dt(inc.started_at)} &middot;
            ended {end_txt} &middot; duration {_fmt_duration(inc.duration_s)}</div>
        </div>""")
        incidents_block = "\n".join(inc_html)
    else:
        incidents_block = '<div class="empty">No incidents recorded. Quiet skies.</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="banner {banner_class}">
    <div class="dot"></div>
    <div><h1>{banner_title}</h1><p>{banner_sub}</p></div>
  </div>
  <div class="grid">
{''.join(cards)}
  </div>
  <h3>Recent incidents</h3>
{incidents_block}
  <footer>Generated by UptimeBeacon &middot; {_fmt_dt(generated_at)}</footer>
</div>
</body>
</html>
"""


def collect_service(store, target, now: float | None = None) -> dict:
    """Gather everything the status page needs for one target."""
    now = time.time() if now is None else now
    rows = store.get_checks(target.name, since=now - 30 * 24 * 3600)
    latest = store.latest_check(target.name)
    return {
        "name": target.name,
        "url": target.url,
        "status": _service_status(latest),
        "latest": latest,
        "uptime": stats_mod.uptime_windows(rows, now=now),
        "latency": stats_mod.latency_stats(rows),
        "spark": stats_mod.sparkline_points(rows),
    }


def generate(store, targets, out_path: str,
             title: str = "UptimeBeacon Status",
             incident_limit: int = 50) -> str:
    """Build the status page from the store and write it to `out_path`."""
    now = time.time()
    services = [collect_service(store, t, now=now) for t in targets]
    incidents = store.get_incidents(limit=incident_limit)
    page = build_status_page(services, incidents, generated_at=now, title=title)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out_path
