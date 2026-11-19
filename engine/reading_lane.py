"""One lane of older-mail reading per account, in slices (design 6.32).

Nothing reads older mail in a request thread. A person's choice is recorded with the read still to do (`older_read` on
the source's first read) and the worker reads it here: one slice (a page, then yield) for each account in turn, so two
accounts take turns and neither starves. A slice that finds more to read leaves the rest due at once; a slice the
service asked to wait on leaves it due at the service's time, and that wait holds every older read of the account, with
no try counted. The order inside an account is its first reads, then its regular polls (both run before the lane in the
worker's pass), then older mail; the header sample and the rest of the headers join the order where `STAGES` marks.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from engine import mail_headers, source_intake

log = logging.getLogger(__name__)

#: The order of an account's reading work. The worker's pass runs the first reads, the header sample (read with
#: the first read) and the polls before it calls `run_slices`, which does older mail, then the rest of the headers.
STAGES = ("first_read", "header_sample", "poll", "older", "header_rest")

#: How many pages one slice reads before the lane yields to the next account.
PAGES_PER_SLICE = 1


def account_of(source: Any) -> str:
    """The lane a source belongs to: its account, or itself when it has none."""
    return str(source.account or source.id)


def account_wait(view: Any, cfg: Any, account: str, now: datetime) -> datetime | None:
    """When the service lets the account's older mail be read again, when one of its reads was asked to wait and the
    time has not come; None when nothing of the account waits."""
    until = None
    for source in cfg.watch.sources:
        if account_of(source) != account:
            continue
        for waiting in (
            source_intake.older_read_waiting(view, source.id),
            mail_headers.sweep_waiting(view, source.id),
        ):
            if waiting and waiting.get("kind") == "throttled" and waiting.get("at"):
                at = datetime.fromisoformat(str(waiting["at"]))
                if at > now and (until is None or at > until):
                    until = at
    return until


def next_wait_in(view: Any, cfg: Any, now: datetime) -> float | None:
    """Seconds until the earliest wait a service asked for on a read of older mail or of the rest of the headers runs
    out, 0 when one has run out and the read hasn't carried on since; None when no such read waits on a service."""
    soonest: float | None = None
    for source in cfg.watch.sources:
        for waiting in (
            source_intake.older_read_waiting(view, source.id),
            mail_headers.sweep_waiting(view, source.id),
        ):
            if waiting and waiting.get("kind") == "throttled" and waiting.get("at"):
                left = max(0.0, (datetime.fromisoformat(str(waiting["at"])) - now).total_seconds())
                soonest = left if soonest is None else min(soonest, left)
    return soonest


def run_slices(
    ws: Any, store: Any, cfg: Any, now: datetime, router: Any = None, stop: threading.Event | None = None
) -> tuple[list[str], bool]:
    """One slice of older-mail reading for each account that has some due, accounts in turn. Returns the sources read
    and whether more is due now (the worker comes round again at once rather than at its next minute)."""
    view = store.read()
    lanes: dict[str, list[tuple[str, str]]] = {}
    by_id = {s.id: s for s in cfg.watch.sources}
    for source_id in source_intake.older_read_due(view, cfg, now):
        lanes.setdefault(account_of(by_id[source_id]), []).append(("older", source_id))
    for source_id in mail_headers.sweep_due(view, cfg, now):
        lanes.setdefault(account_of(by_id[source_id]), []).append(("header_rest", source_id))
    read: list[str] = []
    for account, work in lanes.items():
        if stop is not None and stop.is_set():
            break
        if account_wait(view, cfg, account, now) is not None:
            continue  # a wait the service asked for holds the whole account
        stage, source_id = min(work, key=lambda w: STAGES.index(w[0]))
        try:
            if stage == "older":
                done = source_intake.continue_older_read(ws, store, cfg, source_id, now, router, pages=PAGES_PER_SLICE)
            else:
                done = mail_headers.sweep_slice(ws, store, cfg, source_id, now) or None
        except Exception:  # it stays waiting and is tried again the next time round
            log.exception("reading a slice failed")
            continue
        if done is not None:
            read.append(source_id)
    after = store.read()
    more = any(
        account_wait(after, cfg, account_of(by_id[i]), now) is None
        for i in [*source_intake.older_read_due(after, cfg, now), *mail_headers.sweep_due(after, cfg, now)]
    )
    return read, more
