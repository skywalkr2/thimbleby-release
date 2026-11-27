"""The reading check (design 6.32): a short, paced read of an account's newest message headers through its gate, so
the person can see on their own account what was sent, refused and waited, without a terminal.

It asks the account's source for `watch.check_reading_headers` of its newest headers, once, as the first sign-in's
sample is asked, and keeps nothing. What it reports is the gate's own counts (`engine/gate.py`) from before the read to
after it: requests sent (each went out, whatever the answer), requests the gate held back, the refusals with their
status and reason code (never the service's words), the waits (how long, until when) and the pace the gate settled on.
Another read of the same account at the same moment shares the gate, so its requests are counted too."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from engine import mail_headers
from engine.connectors import ConnectorError, Poll
from engine.gate import Counts, Gate
from engine.storage import StoreError

_NOTHING = (0, 0, 0.0, 0)


@dataclass(frozen=True)
class CheckRefusal:
    status: int | None
    reason: str
    wait_seconds: float | None
    at: datetime
    until: datetime | None


@dataclass
class CheckResult:
    """What a check found: how many headers it asked for and the source gave, how it ended ("read" when the source
    answered, else the kind of the error that stopped it), and the gate's counts for the account."""

    account: str
    asked: int
    read: int
    ended: str
    requests: int = 0
    held: int = 0
    refusals: list[CheckRefusal] = field(default_factory=list)
    waiting_until: datetime | None = None
    pace_per_second: float | None = None
    declared_per_second: float | None = None
    paced_seconds: float = 0.0


def gates_of(store: Any, source: Any, workspace_root: Any) -> list[Gate]:
    """The gates of the source's account, from its plugin; none for a source with no sign-in."""
    plugins = getattr(store, "plugins", None)
    if plugins is None or not hasattr(plugins, "account_gates"):
        return []
    return plugins.account_gates(source.connector, source.account, workspace_root)


def run(ws: Any, store: Any, cfg: Any, source: Any, now: datetime) -> CheckResult:
    """Ask `source` for its newest headers and report the gate's counts. Raises `StoreError` when the source can't be
    asked for headers alone (nothing about its reading is changed)."""
    from engine.connectors import ConnectorContext

    asking = mail_headers.asker(store, source)
    if asking is None:
        raise StoreError("this account can't be checked: it doesn't list message headers")
    asked = int(cfg.watch.check_reading_headers)
    before = {id(g): g.mark() for g in gates_of(store, source, ws.root)}
    context = ConnectorContext(
        workspace_root=ws.root,
        now=now,
        timezone=cfg.workspace.user.timezone,
        hosted=cfg.server.mode == "hosted",
        fetch_deadline_seconds=cfg.steward.fetch_deadline_minutes * 60.0,
    )
    until = now.date() + timedelta(days=1)
    since = until - timedelta(days=max(cfg.watch.first_headers_days, 1))
    ended, read = "read", 0
    try:
        answer = asking(mail_headers._settings_of(store, source), since, until, asked, context)
        items = answer.items if isinstance(answer, Poll) else answer
        read = len(items)
        if isinstance(answer, Poll) and answer.stopped is not None:
            ended = answer.stopped.kind
    except ConnectorError as err:
        ended = err.kind
    gates = gates_of(store, source, ws.root)
    counts = [g.since(before.get(id(g), _NOTHING)) for g in gates]
    return _result(source.account or "", asked, read, ended, gates, counts)


def _result(account: str, asked: int, read: int, ended: str, gates: list[Gate], counts: list[Counts]) -> CheckResult:
    found = CheckResult(account, asked, read, ended)
    refusals = sorted((r for c in counts for r in c.refusals), key=lambda r: r.at)
    found.requests = sum(c.sent for c in counts)
    found.held = sum(c.held for c in counts)
    found.paced_seconds = sum(c.paced_seconds for c in counts)
    found.refusals = [
        CheckRefusal(
            r.status,
            r.reason,
            r.wait_seconds,
            datetime.fromtimestamp(r.at, UTC),
            datetime.fromtimestamp(r.until, UTC) if r.until is not None else None,
        )
        for r in refusals
    ]
    closed = max((g.closed_for() for g in gates), default=0.0)
    if closed > 0:
        found.waiting_until = datetime.fromtimestamp(time.time() + closed, UTC)
    if gates:
        # The slowest account pace across hosts: the one the check's requests were held to.
        slowest = min(gates, key=lambda g: g.rate)
        found.pace_per_second, found.declared_per_second = slowest.rate, slowest.declared
    return found


def log_line(found: CheckResult) -> str:
    """The same as one line for a log or a message: codes and numbers only, never the service's own words."""
    parts = [
        f"requests={found.requests}",
        f"held={found.held}",
        f"refusals={len(found.refusals)}",
        f"read={found.read}/{found.asked}",
        f"ended={found.ended}",
    ]
    for r in found.refusals:
        wait = "" if r.wait_seconds is None else f" wait={r.wait_seconds:g}s"
        until = "" if r.until is None else f" until={r.until.strftime('%H:%M:%S')}Z"
        parts.append(f"refused({r.status if r.status is not None else '-'} {r.reason}{wait}{until})")
    if found.pace_per_second is not None:
        parts.append(f"pace={found.pace_per_second:.2f}/s of {found.declared_per_second:.2f}/s")
    if found.waiting_until is not None:
        parts.append(f"waiting_until={found.waiting_until.strftime('%H:%M:%S')}Z")
    return "check-reading " + " ".join(parts)
