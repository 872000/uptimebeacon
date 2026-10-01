"""Command-line interface for UptimeBeacon.

Commands:
  add          register a new target in the YAML config
  check        run one check round right now (check-once)
  watch        daemon-style loop that checks each target on its interval
               (alias: serve-loop)
  status-page  render the static HTML status page from the SQLite log
  incidents    list recorded incidents
  demo         run the fully-offline scripted demo end to end
"""

from __future__ import annotations

import argparse
import sys
import time

from . import demo as demo_mod
from . import statuspage
from .checker import check_target
from .config import AppConfig, ConfigError, Target, load_config, save_config
from .store import Store

DEFAULT_CONFIG = "uptimebeacon.yaml"


def _resolve_db(args, config: AppConfig) -> str:
    return args.db or config.database


def cmd_add(args) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if any(t.name == args.name for t in config.targets):
        print(f"error: target {args.name!r} already exists", file=sys.stderr)
        return 1
    expected = [int(s) for s in args.expected_status.split(",")]
    config.targets.append(Target(
        name=args.name, url=args.url, interval=args.interval,
        timeout=args.timeout, expected_status=expected, keyword=args.keyword))
    save_config(config, args.config)
    print(f"added target {args.name!r} -> {args.config}")
    return 0


def _pick_targets(config: AppConfig, only: str | None) -> list[Target]:
    targets = config.targets
    if only:
        targets = [t for t in targets if t.name == only]
        if not targets:
            print(f"error: no target named {only!r}", file=sys.stderr)
            raise SystemExit(1)
    return targets


def _print_result_row(result) -> None:
    status = "UP  " if result.ok else "DOWN"
    lat = f"{result.latency_ms:7.1f} ms" if result.latency_ms is not None else "      n/a"
    detail = (f"status={result.status_code}" if result.ok
              else f"error={result.error}")
    print(f"[{status}] {result.name:16s} {lat}  {detail}")


def cmd_check(args) -> int:
    try:
        config = load_config(args.config)
        targets = _pick_targets(config, args.target)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not targets:
        print(f"no targets configured (see `add`, or run `demo`).", file=sys.stderr)
        return 1
    with Store(_resolve_db(args, config)) as store:
        for target in targets:
            result = check_target(target)
            store.log_check(result.name, result.ts, result.ok,
                            result.latency_ms, result.status_code, result.error)
            _print_result_row(result)
            if not result.ok:
                print(f"       incident tracking: "
                      f"{len(store.open_incidents(result.name))} open incident(s) "
                      f"for {result.name!r}")
    return 0


def cmd_watch(args) -> int:
    try:
        config = load_config(args.config)
        targets = _pick_targets(config, args.target)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not targets:
        print("no targets configured (see `add`, or run `demo`).", file=sys.stderr)
        return 1
    print(f"watching {len(targets)} target(s) — Ctrl-C to stop")
    next_run = {t.name: 0.0 for t in targets}
    passes = 0
    with Store(_resolve_db(args, config)) as store:
        try:
            while True:
                now = time.time()
                due = [t for t in targets if now >= next_run[t.name]]
                for target in due:
                    result = check_target(target)
                    store.log_check(result.name, result.ts, result.ok,
                                    result.latency_ms, result.status_code,
                                    result.error)
                    _print_result_row(result)
                    next_run[target.name] = time.time() + target.interval
                passes += 1
                if args.iterations and passes >= args.iterations:
                    break
                # Sleep until the next target is due (or 1s, whichever first).
                wake = min(next_run.values())
                time.sleep(max(0.2, min(1.0, wake - time.time())))
        except KeyboardInterrupt:
            print("\nstopped.")
    return 0


def cmd_status_page(args) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with Store(_resolve_db(args, config)) as store:
        targets = list(config.targets)
        if not targets:
            # Fall back to whatever the database has seen.
            targets = [Target(name=n, url="") for n in store.targets()]
        if not targets:
            print("nothing to render: no targets and an empty database.",
                  file=sys.stderr)
            return 1
        statuspage.generate(store, targets, args.out, title=args.title)
    print(f"status page written to {args.out}")
    return 0


def cmd_incidents(args) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with Store(_resolve_db(args, config)) as store:
        incidents = store.get_incidents(target=args.target, limit=args.limit)
    if not incidents:
        print("no incidents recorded.")
        return 0
    for inc in incidents:
        state = "OPEN    " if inc.is_open else "resolved"
        start = time.strftime("%Y-%m-%d %H:%M", time.localtime(inc.started_at))
        if inc.is_open:
            span = f"since {start} (ongoing)"
        else:
            end = time.strftime("%Y-%m-%d %H:%M", time.localtime(inc.ended_at))
            span = f"{start} -> {end}"
        print(f"[{state}] {inc.target:16s} {span}")
        if inc.cause:
            print(f"           cause: {inc.cause}")
    return 0


def cmd_demo(args) -> int:
    demo_mod.run_demo(args.dir, quiet=args.quiet)
    if not args.quiet:
        print(f"\nopen {args.dir}/status.html in a browser to see the status page.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uptimebeacon",
        description="Uptime monitor with incident log and a static status page.")
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help="path to YAML config (default: %(default)s)")
    parser.add_argument("--db", default=None,
                        help="override SQLite database path from the config")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="register a target to monitor")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--url", required=True)
    p_add.add_argument("--interval", type=int, default=60,
                       help="seconds between checks (default: 60)")
    p_add.add_argument("--timeout", type=int, default=10,
                       help="per-check timeout in seconds (default: 10)")
    p_add.add_argument("--expected-status", default="200",
                       help="comma-separated acceptable statuses (default: 200)")
    p_add.add_argument("--keyword", default=None,
                       help="require this string in the response body")
    p_add.set_defaults(func=cmd_add)

    p_check = sub.add_parser("check", help="run one check round now")
    p_check.add_argument("--target", default=None,
                         help="only check this target")
    p_check.set_defaults(func=cmd_check)

    p_watch = sub.add_parser("watch", help="check on a loop until Ctrl-C")
    p_watch.add_argument("--target", default=None)
    p_watch.add_argument("--iterations", type=int, default=0,
                         help="stop after N loop passes (0 = forever)")
    p_watch.set_defaults(func=cmd_watch)
    # Backwards-friendly alias.
    p_loop = sub.add_parser("serve-loop", help="alias for `watch`")
    p_loop.add_argument("--target", default=None)
    p_loop.add_argument("--iterations", type=int, default=0)
    p_loop.set_defaults(func=cmd_watch)

    p_page = sub.add_parser("status-page", help="render the static status page")
    p_page.add_argument("--out", default="status.html")
    p_page.add_argument("--title", default="UptimeBeacon Status")
    p_page.set_defaults(func=cmd_status_page)

    p_inc = sub.add_parser("incidents", help="list recorded incidents")
    p_inc.add_argument("--target", default=None)
    p_inc.add_argument("--limit", type=int, default=20)
    p_inc.set_defaults(func=cmd_incidents)

    p_demo = sub.add_parser("demo", help="run the offline scripted demo")
    p_demo.add_argument("--dir", default="demo-out",
                        help="output directory (default: %(default)s)")
    p_demo.add_argument("--quiet", action="store_true")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
