"""`python -m app.oncall`: the worker process entry point.

Without credentials (`AGENT_ENABLED` not true, `LLM_PROVIDER` not
`anthropic`, `ANTHROPIC_API_KEY` missing or empty, or no `LLM_MODEL`) it logs
one idle line naming which, never a value, claims nothing and waits for
SIGTERM/SIGINT. Otherwise it polls every `AGENT_POLL_SECONDS`
(`app/oncall/poller.py`) and runs one LLM conversation per claimed alert
(`app/oncall/llm.py`). A failed poll (the database down, for example) logs
the exception type only and the next poll tries again.

`python -m app.oncall tools <tool> [args]` is the maintenance CLI instead
(`app/oncall/cli.py`): one tool call, then exit.
"""

import logging
import signal
import sys
import threading

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
    from app.oncall import llm, poller

    try:
        config: poller.WorkerConfig | None = poller.WorkerConfig.from_env()
        reason = poller.idle_reason(config)
    except ValueError as exc:  # a tuning variable that is not a positive number
        config, reason = None, str(exc)
    stop = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("oncall-agent: received %s, exiting", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if config is None or reason is not None:
        log.info("oncall-agent: idle because %s", reason)
        while not stop.wait(timeout=1.0):
            pass
        return 0

    client = llm.make_client()
    log.info(
        "oncall-agent: polling every %ss (provider %s, model %s)",
        config.poll_seconds,
        config.provider,
        config.model,
    )
    while not stop.is_set():
        try:
            poller.poll_once(client, config)
        except Exception as exc:  # noqa: BLE001 - one line, the type only
            log.warning("oncall-agent: poll failed: %s", type(exc).__name__)
        stop.wait(timeout=config.poll_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
