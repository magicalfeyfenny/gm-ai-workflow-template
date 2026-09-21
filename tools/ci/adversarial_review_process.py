"""Run one Codex session with provider-event liveness, not a work timeout.

The concrete Codex JSONL interface emits startup and turn events, but it does
not emit a reliable heartbeat while the provider is doing model reasoning.  A
silent in-turn stream is therefore indistinguishable from legitimate work at
this boundary.  The runner bounds pre-turn startup and an explicitly closed
event stream, then relies on the provider's own transport error/completion
path after ``turn.started``; it must not invent an elapsed reasoning timeout.
"""

from __future__ import annotations

import codecs
import json
import os
import selectors
import signal
import subprocess
import time
from pathlib import Path


SESSION_STARTUP_TIMEOUT_SECONDS = 120.0


class ProviderHangError(RuntimeError):
    """A bounded provider liveness guard detected a startup or stream hang."""

    def __init__(self, phase: str) -> None:
        self.phase = phase
        super().__init__(f"provider liveness guard failed during {phase}")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _consume_event(line: str) -> bool:
    """Return whether the provider has entered active model work."""
    if not line.strip():
        return False
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return False
    return isinstance(event, dict) and event.get("type") == "turn.started"


def run_provider_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    prompt: str,
    startup_timeout_seconds: float = SESSION_STARTUP_TIMEOUT_SECONDS,
) -> int:
    """Run Codex, bounding only pre-turn liveness and dead event streams.

    ``--json`` is required by the caller.  Provider stdout is consumed only as
    an untrusted event stream; neither it nor stderr is retained or forwarded.
    After ``turn.started`` this function waits without an elapsed-time limit.
    """
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    active_work = False
    deadline = time.monotonic() + startup_timeout_seconds
    try:
        if process.stdin is None or process.stdout is None:
            raise OSError("provider pipes unavailable")
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            returncode = process.poll()
            if returncode is not None:
                break
            wait_for = None
            if not active_work:
                wait_for = max(0.0, deadline - time.monotonic())
            ready = selector.select(wait_for)
            if not ready:
                if not active_work:
                    raise ProviderHangError("pre-turn startup")
                continue
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                try:
                    process.wait(timeout=0.25)
                except subprocess.TimeoutExpired as exc:
                    raise ProviderHangError("closed event stream") from exc
                break
            buffer += decoder.decode(chunk, final=False)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                active_work = _consume_event(line) or active_work
        buffer += decoder.decode(b"", final=True)
        if buffer:
            active_work = _consume_event(buffer) or active_work
        returncode = process.wait()
    except BaseException:
        _terminate(process)
        raise
    finally:
        selector.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stdin is not None:
            process.stdin.close()
    return int(returncode)
