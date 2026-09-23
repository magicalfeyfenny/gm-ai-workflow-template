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
MAX_PRETURN_EVENT_BUFFER_BYTES = 1_048_576
PROVIDER_STATUS_POLL_SECONDS = 1.0


class ProviderHangError(RuntimeError):
    """A bounded provider liveness guard detected a startup or stream hang."""

    def __init__(self, phase: str) -> None:
        self.phase = phase
        super().__init__(f"provider liveness guard failed during {phase}")


class ProviderEventDecodeError(UnicodeError):
    """The provider event stream was not valid UTF-8."""

    diagnostic_code = "output_event_stream_encoding"

    def __init__(self) -> None:
        super().__init__("provider event stream decoding failed")


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
    prompt_bytes = prompt.encode("utf-8")
    prompt_offset = 0
    input_closed = False
    turn_started = False
    active_work = False
    deadline = time.monotonic() + startup_timeout_seconds
    try:
        if process.stdin is None or process.stdout is None:
            raise OSError("provider pipes unavailable")
        stdin = process.stdin
        stdout = process.stdout
        os.set_blocking(stdin.fileno(), False)
        selector.register(stdin, selectors.EVENT_WRITE)
        selector.register(process.stdout, selectors.EVENT_READ)

        def close_input() -> None:
            nonlocal input_closed
            if input_closed:
                return
            try:
                selector.unregister(stdin)
            except KeyError:
                pass
            try:
                stdin.close()
            except OSError as exc:
                raise ProviderHangError("stdin closure") from exc
            input_closed = True

        if not prompt_bytes:
            close_input()
        while True:
            returncode = process.poll()
            if returncode is not None:
                break
            if not active_work and time.monotonic() >= deadline:
                phase = "pre-turn prompt delivery" if not input_closed else "pre-turn startup"
                raise ProviderHangError(phase)
            wait_for = None
            if not active_work:
                wait_for = max(0.0, deadline - time.monotonic())
            else:
                # This is only a process-status observation interval.  It is
                # not an idle-work timeout: silent active reasoning remains
                # allowed indefinitely unless positive transport evidence
                # arrives.
                wait_for = PROVIDER_STATUS_POLL_SECONDS
            ready = selector.select(wait_for)
            if not ready:
                if not active_work:
                    phase = "pre-turn prompt delivery" if not input_closed else "pre-turn startup"
                    raise ProviderHangError(phase)
                if process.poll() is not None:
                    break
                continue
            for key, mask in ready:
                if key.fileobj is stdin and mask & selectors.EVENT_WRITE:
                    try:
                        written = os.write(stdin.fileno(), prompt_bytes[prompt_offset:])
                    except BlockingIOError:
                        written = 0
                    except OSError as exc:
                        raise ProviderHangError("prompt delivery") from exc
                    prompt_offset += written
                    if prompt_offset >= len(prompt_bytes):
                        close_input()
                        active_work = turn_started
                if key.fileobj is stdout and mask & selectors.EVENT_READ:
                    try:
                        chunk = os.read(stdout.fileno(), 4096)
                    except OSError as exc:
                        raise ProviderHangError("provider transport") from exc
                    if not chunk:
                        try:
                            process.wait(timeout=0.25)
                        except subprocess.TimeoutExpired as exc:
                            raise ProviderHangError("closed event stream") from exc
                        break
                    try:
                        decoded = decoder.decode(chunk, final=False)
                    except UnicodeDecodeError as exc:
                        raise ProviderEventDecodeError() from exc
                    buffer += decoded
                    if not active_work and len(buffer.encode("utf-8")) > MAX_PRETURN_EVENT_BUFFER_BYTES:
                        raise ProviderHangError("pre-turn event buffering")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        turn_started = _consume_event(line) or turn_started
                        active_work = input_closed and turn_started
            if process.poll() is not None:
                break
        try:
            buffer += decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise ProviderEventDecodeError() from exc
        if buffer:
            turn_started = _consume_event(buffer) or turn_started
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
