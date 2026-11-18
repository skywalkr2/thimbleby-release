"""A year of message headers read once at a mail source's first sign-in (design 6.32, 6.22).

After a mail source's first read, the core asks the connector (when it can: `registrar.connector(..., headers=fn)`)
for the headers of the messages from `watch.first_headers_days` back to the day that read began, and keeps each as a
`mail_header` record: who it was from and to, when, where it ended up and its subject, never its text. Nothing here
calls AI and nothing is handed in: a header is not an input, a request or a packet's outside content, and the sorting
never sees it. The contact tally reads the kept headers like any message's details, and `habit_lines` gathers counts
for the first look at the person's habits: which senders' mail is deleted unopened, what recurs, and where messages
ended up. The rules only gather; every judgment about what a habit means is the assistant's."""

from __future__ import annotations

import logging
import re
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from engine import contact_tally
from engine import people_suggestions as ps
from engine.connectors import MESSAGE_PLACES, ConnectorError
from engine.storage import StoreError, WriteContext

log = logging.getLogger(__name__)

_KEEP = WriteContext(actor="watcher", trust="untrusted", op="watch.headers")
_CHUNK = 500
_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
_SHOWN_SUBJECT = 60


def asker(store: Any, source: Any) -> Any:
    """How the source is asked for headers alone: its plugin connector's `headers` function as the plugin host wraps
    it, or the core mailbox connector's own header fetch, or None when the connector can't be asked (a connector that
    says nothing about headers works as before)."""
    from engine.connectors import header_mail

    core = header_mail(source.connector)
    if core is not None:
        return core
    plugins = getattr(store, "plugins", None)
    connector = plugins.connectors().get(source.connector) if plugins is not None else None
    if connector is None or getattr(connector, "headers", None) is None:
        return None
    return plugins.header_mail(connector, source.account)


def read_first(ws: Any, store: Any, cfg: Any, source: Any, now: datetime, before: date | None = None) -> int | None:
    """Ask the source once for its headers and keep them. `before` is the day the first read's own mail starts from
    (the read began there), else the day after today; the days asked for run from `watch.first_headers_days` before
    it. Returns how many headers were kept, or None when the source can't be asked or the setting is 0. A connector
    error is passed on to the caller, who records it; any message a snapshot already stands for is not kept again."""
    days, limit = cfg.watch.first_headers_days, cfg.watch.first_headers_max_items
    asking = asker(store, source)
    if asking is None or days <= 0:
        return None
    from engine.connectors import ConnectorContext, Poll, skipped_counts

    until = before or (now.date() + timedelta(days=1))
    context = ConnectorContext(
        workspace_root=ws.root, now=now, timezone=cfg.workspace.user.timezone, hosted=cfg.server.mode == "hosted"
    )
    settings = _settings_of(store, source)
    answer = asking(settings, until - timedelta(days=days), until, limit, context)
    items, unreadable = (answer.items, answer.unreadable) if isinstance(answer, Poll) else (answer, [])
    kept = keep(store, source, items, now)
    if unreadable:
        from engine import source_intake, watch

        source_intake.add_older_skipped(store, source.id, skipped_counts(unreadable))
        watch._tell_unreadable(store, cfg, source, unreadable)
    return kept


def _settings_of(store: Any, source: Any) -> Any:
    from engine.connectors import CORE

    if source.connector in CORE:
        return CORE[source.connector].settings.model_validate(source.settings)
    connector = store.plugins.connectors()[source.connector]
    return connector.settings.model_validate(source.settings)


def keep(store: Any, source: Any, items: list[Any], now: datetime) -> int:
    """Keep each item's details and subject as a header: nothing of its text or files, and nothing for a message the
    source already holds (a snapshot or an earlier header of the same key)."""
    from engine.watch import _message_dict

    view = store.read()
    held = {s.data["key"] for s in view.find("snapshot", {"source": source.id})}
    held |= {h.data["key"] for h in view.find("mail_header", {"source": source.id})}
    fresh = []
    for item in items:
        message = _message_dict(item.message)
        if message is None or item.key in held:
            continue
        held.add(item.key)
        fresh.append(
            {"source": source.id, "key": item.key, "title": item.title, "message": message, "seen_at": now.isoformat()}
        )
    for start in range(0, len(fresh), _CHUNK):
        with store.transaction() as tx:
            for data in fresh[start : start + _CHUNK]:
                tx.create("mail_header", data, _KEEP)
    return len(fresh)


def read_after_first(
    ws: Any, store: Any, cfg: Any, source: Any, now: datetime, clock: float, before: date | None = None
) -> ConnectorError | None:
    """The read made after a mail source's first one. A failure never fails the first read: it is recorded and told as
    any failed read is, once, and not tried again. Returns the connector's error, or None."""
    from engine import watch

    try:
        read_first(ws, store, cfg, source, now, before)
    except ConnectorError as err:
        watch._failed_read(store, cfg, source, err, now, clock)
        return err
    except StoreError as err:
        log.warning("The headers of %s couldn't be kept: %s", source.id, err)
    return None


# ---- what the headers show, as counts ----------------------------------------------------------------------------


def _when(data: dict[str, Any]) -> date | None:
    stamp = (data.get("message") or {}).get("received") or data.get("seen_at")
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment.astimezone(UTC) if moment.tzinfo else moment).date()


def _pattern(title: str) -> str:
    """A subject with its reply marks and numbers taken out, so a message that repeats under a new number is one."""
    plain = _PREFIX.sub("", title or "")
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", plain)).strip().lower()


def _steady(days: list[date]) -> int | None:
    """The interval in days when the dates repeat at a steady one (at least three, each gap within a quarter of the
    middle gap, at least a day), else None."""
    days = sorted(set(days))
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    if len(days) < 3 or not gaps:
        return None
    middle = statistics.median(gaps)
    if middle < 1:
        return None
    room = max(1.0, middle * 0.25)
    return round(middle) if all(abs(g - middle) <= room for g in gaps) else None


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("|", "/")).strip()


def habit_lines(store: Any, cfg: Any, only: set[str] | None = None) -> list[str]:
    """Short lines of counts about the received mail the app holds the details of (kept headers and snapshots), for
    the first judgment run's packet: which senders' mail the person deletes unopened, where each sender's messages
    ended up, and what recurs (the same sender and a similar subject at a steady interval). Only senders with at
    least `person_look_min_messages` messages are counted, the most dealt with first, at most `person_look_entries`
    for each kind of line. Facts to weigh, never verdicts; subject words are outside content and the caller marks
    them so. `only` limits the senders to those addresses (the ones the look reads)."""
    settings = cfg.dispatch.knowledge
    sources = ps._mail_sources(store, cfg)
    person = cfg.workspace.user.person
    own = ps._own_addresses(store, cfg, sources)
    view = store.read()
    places: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unopened: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    series: dict[tuple[str, str], list[date]] = defaultdict(list)
    shown: dict[tuple[str, str], str] = {}
    for s in sources:
        if person and s.author == person:
            continue  # sent mail says who the person writes to, which the tally already gives
        for held in contact_tally.held_messages(view, s.id):
            message = held.data["message"]
            display, address = ps._parsed(message.get("sender") or "")
            if not address or address in own:
                continue
            totals[address] += 1
            names.setdefault(address, ps._name_of(re.sub(r"\s+", " ", display.replace('"', "")).strip(), address))
            where = message.get("where") if message.get("where") in MESSAGE_PLACES else "unknown"
            places[address][where] += 1
            if where == "deleted" and message.get("unread") is True:
                unopened[address] += 1
            title = held.data.get("title") or ""
            day = _when(held.data)
            if day is not None and _pattern(title):
                series[(address, _pattern(title))].append(day)
                shown.setdefault((address, _pattern(title)), title)
    floor, cap = settings.person_look_min_messages, settings.person_look_entries
    ranked = sorted(
        (a for a in totals if totals[a] >= floor and (only is None or a in only)), key=lambda a: (-totals[a], a)
    )
    lines: list[str] = []
    gone = [a for a in ranked if unopened[a]]
    gone.sort(key=lambda a: (-unopened[a], a))
    for a in gone[:cap]:
        lines.append(f"deleted unopened | {a} | {_one_line(names[a])} | {unopened[a]} of {totals[a]} messages")
    for a in ranked[:cap]:
        known = {k: v for k, v in places[a].items() if k != "unknown"}
        if not known:
            continue  # the service doesn't say where this sender's messages were
        spread = ", ".join(f"{k} {v}" for k, v in sorted(known.items()))
        lines.append(f"where they ended up | {a} | {_one_line(names[a])} | {spread}")
    repeats = []
    for (a, pattern), days in series.items():
        if a not in ranked:
            continue
        interval = _steady(days)
        if interval is not None:
            repeats.append((-len(days), a, pattern, interval, max(days)))
    for count, a, pattern, interval, last in sorted(repeats)[:cap]:
        subject = _one_line(shown[(a, pattern)])[:_SHOWN_SUBJECT]
        lines.append(f'recurs | {a} | "{subject}" | {-count} times, about every {interval} days, last {last}')
    return lines
