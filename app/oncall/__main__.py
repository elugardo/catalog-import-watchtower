"""`python -m app.oncall`: the worker process entry point.

CIW-01 stub. It logs once why it is idle, then waits for SIGTERM/SIGINT so
Compose can stop it within the default grace period. It makes no LLM call,
touches no table and claims nothing. CIW-08.2 replaces the wait with the
poll / claim / LLM loop described in `_docs/architecture.md`.

`python -m app.oncall tools <tool> [args]` is the maintenance CLI instead
(`app/oncall/cli.py`): one tool call, then exit.
"""

import logging
import signal
import sys
import threading

from app.settings import get_settings

log = logging.getLogger("app.oncall")


def main(argv: list[str] | None = None) -> int:
    if argv and argv[0] == "tools":
        from app.oncall.cli import run

        return run(argv[1:])

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    settings = get_settings()

    if settings.agent_enabled:
        log.info(
            "oncall-agent: AGENT_ENABLED=true but the worker loop is not implemented yet (CIW-08.2); staying idle"
        )
    else:
        log.info("oncall-agent: idle because AGENT_ENABLED is not true")

    stop = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("oncall-agent: received %s, exiting", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not stop.wait(timeout=1.0):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
