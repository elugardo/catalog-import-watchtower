"""Smoke-check a deployed environment's `/api/health` (CIW-10.1).

    python scripts/smoke_check.py <base-url> <expected-version> [--attempts N] [--interval S]

Passes (exit 0) as soon as one response is HTTP 200 with `db == "ok"` and
`version == <expected-version>`. Otherwise it retries, because a stopped Fly
machine needs a few seconds to wake and a rolling deploy may still be
replacing the old release, and fails (exit 1) once the attempts are used up.
The total wait is bounded: about attempts x (interval + request timeout).

Standard library only, so it runs on a bare CI runner. It prints only the
status code and the health body, which holds no secret.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable


def check_once(health_url: str, expected_version: str, timeout: float) -> tuple[bool, str]:
    """One request. Returns (passed, one-line description of what was seen)."""
    try:
        with urllib.request.urlopen(health_url, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return False, f"no response ({exc.__class__.__name__}: {getattr(exc, 'reason', exc)})"

    text = raw.decode("utf-8", errors="replace")[:500]
    if status != 200:
        return False, f"HTTP {status} {text}"
    try:
        body = json.loads(text)
    except ValueError:
        return False, f"HTTP 200 but not JSON: {text}"
    if not isinstance(body, dict):
        return False, f"HTTP 200 but not an object: {text}"
    problems = []
    if body.get("db") != "ok":
        problems.append(f"db={body.get('db')!r}")
    if body.get("version") != expected_version:
        problems.append(f"version={body.get('version')!r}, expected {expected_version!r}")
    if problems:
        return False, f"HTTP 200 {text} ({'; '.join(problems)})"
    return True, f"HTTP 200 {text}"


def smoke_check(
    base_url: str,
    expected_version: str,
    attempts: int = 30,
    interval: float = 10.0,
    timeout: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    health_url = base_url.rstrip("/") + "/api/health"
    for attempt in range(1, attempts + 1):
        passed, seen = check_once(health_url, expected_version, timeout)
        print(f"[{attempt}/{attempts}] GET {health_url}: {seen}", flush=True)
        if passed:
            return True
        if attempt < attempts:
            sleep(interval)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url")
    parser.add_argument("expected_version")
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")

    if smoke_check(args.base_url, args.expected_version, args.attempts, args.interval, args.timeout):
        print("smoke check passed")
        return 0
    print(f"smoke check FAILED after {args.attempts} attempts", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
