"""What the person sees while the app updates itself, and what happens at the next start (design 11.7).

`install` runs the update steps (`engine.app_update`) with the starting window showing their progress; a step that
fails turns the window into the failed-update screen (one reason, Try again, Open Thimbleby, Copy details). `settle`
runs at the start of the app: when the script outside the app put the old version back, it puts the database copy back
too and shows the same screen; when the new version is the one running, it tells the script so.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engine import app_update, launcher, update_offer, updating
from engine.app_update import Steps, UpdateFailed

log = logging.getLogger(__name__)

#: How many characters of the script's own log go in "Copy details".
LOG_TAIL = 1500


def reason(words: Mapping[str, str], kind: str) -> str:
    """One reason in the person's words for a way an update fails."""
    return words.get(f"desktop.update.reason.{kind}") or words["desktop.update.reason.other"]


def _log_tail(ws: Any) -> str:
    try:
        log_file = Path(ws.private_dir) / app_update.HELPER_FOLDER / "hand-over.log"
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-LOG_TAIL:]


def install(
    ws: Any,
    cfg: Any,
    shell: Any,
    version: str,
    *,
    current: str | None = None,
    steps: Steps | None = None,
    install_at: app_update.Install | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Update to `version` from the starting window. True when the hand-over has started, so the caller ends the app;
    False when the person chose to go on with the version they have (or quit)."""
    offer = update_offer.offer(ws.private_dir)
    running = current or update_offer.current_version()
    here = install_at if install_at is not None else app_update.own_install()
    shell.show_update(running)
    began, current_step = time.monotonic(), [""]

    def progress(step: str, fraction: float | None, detail: str) -> None:
        """Each step's start is noted with its time, for the build machines' check and for "Copy details"."""
        if step != current_step[0]:
            current_step[0] = step
            launcher.note(f"update step {step} at {time.monotonic() - began:.1f}s")
        shell.update_step(step, fraction, detail)

    while True:
        try:
            if offer is None or offer.version != version:
                raise UpdateFailed("download", "that version isn't on offer any more")
            app_update.run(
                ws,
                offer,
                cfg.updates,
                install=here,
                from_version=running,
                progress=progress,
                steps=steps,
                environ=environ,
            )
            return True
        except UpdateFailed as err:
            log.warning("the update to %s didn't finish: %s", version, err)
            details = f"Update from {running} to {version}\n{err.kind}: {err.detail}"
            choice = shell.update_failed(running, reason(shell.words, err.kind), details)
            if choice != "again":
                return False


def settle(
    ws: Any,
    cfg: Any,
    shell: Any,
    *,
    current: str | None = None,
    steps: Steps | None = None,
    install_at: app_update.Install | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """At the start of the app, before the workspace is opened: deal with what the last update left. True when the app
    goes on starting; False when the person chose to try the update again and it has been handed over, or quit."""
    running = current or update_offer.current_version()
    found = app_update.read_result(ws)
    if found is None:
        app_update.drop_stale_plan(ws)
        return True
    if found.get("status") != "failed":
        return True
    extra = ""
    if found.get("restore"):
        try:
            if updating.restore(ws):
                extra = "\nThe copy of the work made before updating was put back."
        except updating.UpdateError as err:
            extra = f"\n{err}"
    kind = str(found.get("reason") or "other")
    shown = str(found.get("from") or running)
    details = f"Update didn't finish ({kind}), still on {shown}{extra}\n{_log_tail(ws)}"
    app_update.clear(ws)
    choice = shell.update_failed(shown, reason(shell.words, kind), details)
    if choice == "again":
        offer = update_offer.offer(ws.private_dir)
        if offer is not None and install(
            ws, cfg, shell, offer.version, current=running, steps=steps, install_at=install_at, environ=environ
        ):
            shell.quit()
            return False
    if shell.quit_event.is_set():
        return False
    shell.resume_starting()
    return True


def started(ws: Any, version: str | None = None) -> bool:
    """The app is running: when a hand-over is waiting for the new version to say so, it says so now."""
    return app_update.record_started(ws, version or update_offer.current_version())
