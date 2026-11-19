"""A watcher for the browser tests' app that makes a silent stall in reading visible when it happens.

It exists only in the test server (`tests.e2e_serve`), never in the app. It is on when `E2E_STALL_DIR` names a folder:

- a signal (`SIGUSR1`, where the system has it) writes every thread's stack to `stacks-on-signal.txt` there;
- a thread looks every few seconds at how many requests the made-up services counted (`E2E_FAKE_ADDRESS`, their own
  `/__e2e/requests`) and at the sources' latest reads. When no request has reached the services for `quiet` seconds
  while some source's asked-for wait has run out, it writes every thread's stack, the worker's state and every
  source's reads to `stall-<n>.txt`. One file per quiet stretch;
- each look is one line in `watch.log`, so a run that never stalls still leaves what was seen.
"""

from __future__ import annotations

import faulthandler
import json
import os
import signal
import sys
import threading
import time
import traceback
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Seconds with no request reaching the services, while a source's wait has run out, that count as a stall.
QUIET_SECONDS = 60.0
#: Seconds between two looks.
LOOK_SECONDS = 5.0
#: Seconds a pass of the jobs loop may take before its stack is noted in the log.
LONG_PASS_SECONDS = 30.0


def requests_counted(address: str) -> int | None:
    """How many requests the made-up services counted so far; None when they can't be asked."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{address}/__e2e/requests", timeout=5) as answer:  # noqa: S310 - a loopback test address
            return len(json.loads(answer.read())["requests"])
    except Exception:
        return None


def waits_run_out(store: Any, cfg: Any, now: datetime) -> list[str]:
    """The sources that are on and whose latest read was asked to wait until a time that has passed."""
    view = store.read()
    found = []
    for source in cfg.watch.sources:
        if not source.enabled:
            continue
        runs = view.find("watch_run", {"source": source.id})
        retry_at = runs[-1].data.get("retry_at") if runs else None
        if retry_at and datetime.fromisoformat(str(retry_at)) <= now:
            found.append(source.id)
    return found


def stalled(quiet_for: float, run_out: list[str], quiet: float = QUIET_SECONDS) -> bool:
    """Whether this is a stall: nothing reached the services for `quiet` seconds while a source's wait has run out."""
    return quiet_for >= quiet and bool(run_out)


def stack_of(thread_name: str) -> str:
    """The stack of the thread with this name, as text; empty when there is none."""
    frames = sys._current_frames()
    for thread in threading.enumerate():
        if thread.name == thread_name and thread.ident in frames:
            return "".join(traceback.format_stack(frames[thread.ident]))
    return ""


def where(thread_name: str) -> str:
    """Where the thread with this name is, as the innermost line of the app's own code on its stack."""
    frames = sys._current_frames()
    for thread in threading.enumerate():
        if thread.name == thread_name and thread.ident in frames:
            for frame in reversed(traceback.extract_stack(frames[thread.ident])):
                if "/engine/" in frame.filename or "/api/" in frame.filename:
                    return f"{Path(frame.filename).name}:{frame.lineno} {frame.name}"
    return "nowhere"


def worker_state(worker: Any) -> dict[str, Any]:
    """What the worker's loops are doing, read from outside: test-only, so it reads what no screen shows."""
    from engine import gate

    beat = time.monotonic()
    with gate._lock:
        gates = dict(gate._gates)
    return {
        "loop_health": worker.loop_health(),
        "seconds_since_beat": {name: round(beat - at, 1) for name, at in worker._beats.items()},
        "read_now_set": worker._read_now.is_set(),
        "wake_set": worker._wake.is_set(),
        "stop_set": worker._stop.is_set(),
        "restart_needed": worker.restart_needed,
        "restart_requested": worker.restart_requested,
        "restart_for": list(worker.restart_for),
        "accounts_to_read": len(worker._accounts_to_read),
        "gates": {
            "/".join(key): {
                "sent": g.counts.sent,
                "held": g.counts.held,
                "closed_for": round(g.closed_for(), 1),
                "rate": g.rate,
                "next_slot_in": round(g._next_slot - g.clock(), 1),
            }
            for key, g in gates.items()
        },
    }


def write_stall(folder: Path, number: int, worker: Any, store: Any, quiet_for: float, run_out: list[str]) -> Path:
    """Every thread's stack, the worker's state and every source's reads, in one file."""
    path = folder / f"stall-{number}.txt"
    cfg = worker.cfg
    view = store.read()
    with path.open("w", encoding="utf-8") as out:
        out.write(f"stall seen at {datetime.now(UTC).isoformat()} (the app's clock)\n")
        out.write(f"no request reached the services for {quiet_for:.0f} s; waits run out: {run_out}\n\n")
        out.write(json.dumps(worker_state(worker), indent=1, default=str) + "\n\n== threads ==\n")
        out.flush()
        faulthandler.dump_traceback(file=out, all_threads=True)
        out.write("\n== the jobs thread, with its lines ==\n" + stack_of("cockpit-jobs"))
        out.write("\n== the reads of every source ==\n")
        for source in cfg.watch.sources:
            out.write(f"\n{source.id} (account {source.account}, on {source.enabled})\n")
            for run in view.find("watch_run", {"source": source.id}):
                kept = {k: v for k, v in run.data.items() if k not in ("state", "unreadable") and v is not None}
                out.write(f"  {run.id} {json.dumps(kept, default=str)}\n")
    return path


def start(worker: Any, store: Any) -> threading.Thread | None:
    """Start the watcher when `E2E_STALL_DIR` names a folder; returns its thread."""
    named = os.environ.get("E2E_STALL_DIR")
    if not named:
        return None
    folder = Path(named)
    folder.mkdir(parents=True, exist_ok=True)
    if hasattr(signal, "SIGUSR1"):
        on_signal = (folder / "stacks-on-signal.txt").open("a", encoding="utf-8")
        faulthandler.register(signal.SIGUSR1, file=on_signal, all_threads=True)
    address = os.environ.get("E2E_FAKE_ADDRESS")
    rest = threading.Event()

    def watch() -> None:
        counted, moved_at, written, armed, noted_pass = None, time.monotonic(), 0, True, 0.0
        with (folder / "watch.log").open("a", encoding="utf-8") as log:
            log.write(f"watching (pid {os.getpid()}), services at {address}\n")
            while not rest.wait(LOOK_SECONDS):
                try:
                    seen = requests_counted(address) if address else None
                    beat = time.monotonic()
                    if seen != counted:
                        counted, moved_at, armed = seen, beat, True
                    run_out = waits_run_out(store, worker.cfg, worker.now())
                    quiet_for = beat - moved_at
                    in_pass = beat - worker._beats.get("jobs", beat)
                    log.write(
                        f"{datetime.now(UTC).isoformat()} requests {seen} quiet {quiet_for:.0f}s "
                        f"run-out {run_out} jobs-beat {in_pass:.0f}s at {where('cockpit-jobs')} "
                        f"restart {worker.restart_needed!r}\n"
                    )
                    if in_pass >= LONG_PASS_SECONDS and in_pass - noted_pass >= LONG_PASS_SECONDS:
                        noted_pass = in_pass
                        log.write(f"the jobs thread, {in_pass:.0f}s since its beat:\n{stack_of('cockpit-jobs')}\n")
                    elif in_pass < LONG_PASS_SECONDS:
                        noted_pass = 0.0
                    if armed and seen is not None and stalled(quiet_for, run_out):
                        written += 1
                        armed = False
                        path = write_stall(folder, written, worker, store, quiet_for, run_out)
                        log.write(f"STALL written to {path}\n")
                    log.flush()
                except Exception:
                    log.write(traceback.format_exc())
                    log.flush()

    thread = threading.Thread(target=watch, name="e2e-stall-watch", daemon=True)
    thread.start()
    return thread
