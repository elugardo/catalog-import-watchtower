"""`scripts/smoke_check.py` (CIW-10.1): passes only on 200 + db ok + the
expected version, retries otherwise, and gives up after a bounded number of
attempts. Runs against a throwaway local HTTP server; no network."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_check.py"
_spec = importlib.util.spec_from_file_location("smoke_check", SCRIPT)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

VERSION = "sha-" + "a" * 40


@pytest.fixture
def server():
    """A local server answering /api/health with the queued (status, body) pairs;
    the last one repeats once the queue is down to it."""
    responses: list[tuple[int, str]] = []
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server API)
            hits.append(self.path)
            status, body = responses.pop(0) if len(responses) > 1 else responses[0]
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", responses, hits
    httpd.shutdown()
    httpd.server_close()


def health(db="ok", version=VERSION) -> str:
    return json.dumps({"status": "ok", "db": db, "agent_enabled": False, "version": version})


def run(base_url, attempts=3):
    sleeps: list[float] = []
    passed = smoke.smoke_check(base_url, VERSION, attempts=attempts, interval=7, timeout=2, sleep=sleeps.append)
    return passed, sleeps


def test_passes_on_first_good_response(server):
    url, responses, hits = server
    responses.append((200, health()))
    passed, sleeps = run(url + "/")  # a trailing slash on the base URL is fine
    assert passed
    assert hits == ["/api/health"]
    assert sleeps == []


def test_retries_until_the_machine_wakes(server):
    url, responses, hits = server
    responses.extend([(503, "starting"), (200, health(db="error")), (200, health())])
    passed, sleeps = run(url, attempts=5)
    assert passed
    assert len(hits) == 3
    assert sleeps == [7, 7]


@pytest.mark.parametrize(
    "status, body",
    [
        (200, health(db="error")),
        (200, health(version="sha-" + "b" * 40)),
        (200, health(version="dev")),
        (500, health()),
        (200, "not json"),
        (200, "[]"),
    ],
    ids=["db-error", "older-sha", "dev-version", "http-500", "not-json", "not-object"],
)
def test_fails_after_bounded_attempts(server, status, body):
    url, responses, hits = server
    responses.append((status, body))
    passed, sleeps = run(url, attempts=3)
    assert not passed
    assert len(hits) == 3  # exactly the attempts, then it stops
    assert sleeps == [7, 7]  # no sleep after the last attempt


def test_unreachable_host_fails_without_raising():
    # Port 9 on localhost: nothing listens, the connection is refused.
    passed, sleeps = run("http://127.0.0.1:9", attempts=2)
    assert not passed
    assert sleeps == [7]


def test_main_exit_codes(server):
    url, responses, _ = server
    responses.append((200, health()))
    assert smoke.main([url, VERSION, "--attempts", "1"]) == 0
    assert smoke.main([url, "sha-" + "c" * 40, "--attempts", "2", "--interval", "0"]) == 1
