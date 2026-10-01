"""HTTP checks using only the standard library (urllib)."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

MAX_BODY_BYTES = 256 * 1024  # enough for a keyword match, never the whole internet


@dataclass
class CheckResult:
    name: str
    url: str
    ok: bool
    latency_ms: float | None
    status_code: int | None
    error: str | None
    ts: float


def _classify(target, status_code: int | None, body: bytes, error: str | None):
    """Decide pass/fail from status code, optional keyword and transport error."""
    if error is not None:
        return False, error
    if status_code not in target.expected_status:
        return False, f"unexpected status {status_code}"
    if target.keyword:
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            text = ""
        if target.keyword not in text:
            return False, f"keyword {target.keyword!r} not found in response"
    return True, None


def check_target(target, timeout: float | None = None) -> CheckResult:
    """Perform a single HTTP(S) check against a target. Never raises."""
    ts = time.time()
    timeout = target.timeout if timeout is None else timeout
    request = urllib.request.Request(
        target.url,
        headers={"User-Agent": "UptimeBeacon/0.1 (+https://github.com/parthmanchanda/uptimebeacon)"},
    )
    start = time.perf_counter()
    status_code: int | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BODY_BYTES)
            status_code = response.status
        latency_ms = (time.perf_counter() - start) * 1000.0
        ok, error = _classify(target, status_code, body, None)
    except urllib.error.HTTPError as exc:
        # HTTPError still carries a status code (e.g. 500) — classify it.
        latency_ms = (time.perf_counter() - start) * 1000.0
        status_code = exc.code
        try:
            body = exc.read(MAX_BODY_BYTES)
        except Exception:
            body = b""
        ok, error = _classify(target, exc.code, body, None)
    except urllib.error.URLError as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        reason = getattr(exc.reason, "strerror", None) or str(exc.reason)
        ok, error = False, f"connection failed: {reason}"
    except (socket.timeout, TimeoutError):
        latency_ms = (time.perf_counter() - start) * 1000.0
        ok, error = False, f"timed out after {timeout}s"
    except Exception as exc:  # never let a check crash the loop
        latency_ms = (time.perf_counter() - start) * 1000.0
        ok, error = False, f"{type(exc).__name__}: {exc}"
    return CheckResult(
        name=target.name,
        url=target.url,
        ok=ok,
        latency_ms=latency_ms,
        status_code=status_code,
        error=error,
        ts=ts,
    )
