"""What the assistant's sorting costs a typical day of mail (design 6.5, step 3), worked out by rules and no AI run.

The day's count is the median number of messages a day over the mail read in the last `DAYS` days (days with mail),
or `watch.sorting_typical_day` before enough mail has been read. A run's size is measured on the sorting packet built
for real messages by the packet builder: the fixed part of the packet shared by a batch, plus what each message adds.
The price is the router's estimate for the account the sorting would use first: money for a priced account, runs a day
for a plan or an account of unknown price, and nothing when no account takes the work.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from engine import mail_sorting
from engine.ai import pricing
from engine.ai.calibration import estimate_tokens
from engine.connectors import SourceItem

#: How many days of mail read count towards a typical day.
DAYS = 14
#: The most real messages whose packet is measured.
SAMPLE = 25
#: Stand-ins for the size of one message's header while no mail has been read (an invented, ordinary one).
_SENDER = "A Sender <a.sender@example.com>"
_SUBJECT = "A subject line of an ordinary length for a message"

MONEY, RUNS, UNKNOWN, NONE = "money", "runs", "unknown", "none"


@dataclass(frozen=True)
class SortingCost:
    """`kind`: money (a priced account), runs (a plan: runs a day, no money), unknown (an account with no known price)
    or none (no account takes the work). `messages` is the typical day; `measured` says it came from mail read."""

    kind: str
    messages: int
    runs: int
    estimate_usd: float | None
    measured: bool


def _when(message: dict[str, Any], seen_at: Any) -> datetime | None:
    raw = message.get("received") or str(seen_at)
    try:
        at = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def read_mail(ws: Any, store: Any, cfg: Any, now: datetime) -> tuple[list[int], list[mail_sorting.Header]]:
    """The messages read per day over the last `DAYS` days (days with mail only), and the headers of the newest
    messages as the sorting would see them (from the snapshots the watcher keeps)."""
    from engine import watch

    sources = {s.id: s for s in cfg.watch.sources}
    from engine.today import zone

    local = zone(cfg)
    since = now - timedelta(days=DAYS)
    per_day: dict[Any, int] = {}
    found: list[tuple[datetime, Any]] = []
    for snap in store.read().list("snapshot"):
        sd = snap.data
        if not sd.get("message") or sd.get("deleted"):
            continue
        at = _when(sd["message"], sd.get("seen_at"))
        if at is None or at < since or at > now + timedelta(days=1):
            continue
        day = at.astimezone(local).date()  # the person's own day, not UTC's
        per_day[day] = per_day.get(day, 0) + 1
        found.append((at, sd))
    headers: list[mail_sorting.Header] = []
    for _at, sd in sorted(found, key=lambda x: x[0], reverse=True)[:SAMPLE]:
        source = sources.get(sd["source"])
        if source is None:
            continue
        item = SourceItem(
            sd["key"],
            sd["title"],
            watch._read_text(ws, sd["content_hash"]),
            author=sd.get("author"),
            changed_at=sd.get("changed_at"),
            message=watch._message_of(sd.get("message")),
        )
        facts = watch._change(cfg, source, item, "new", None)
        headers.append(mail_sorting.header_of(item.key, facts, cfg.watch.mail_kinds, cfg))
    return list(per_day.values()), headers


def tokens_per_run(ws: Any, cfg: Any, headers: list[mail_sorting.Header], view: Any = None) -> tuple[int, float]:
    """The sorting packet's fixed tokens (instructions and the stable part) and the tokens each message adds, measured
    on the packet the builder makes for these headers (an invented ordinary header when none is given)."""
    sample = headers or [mail_sorting.Header("m", _SENDER, _SUBJECT)]
    task, _ids = mail_sorting.build_task(ws, cfg, sample, view)
    fixed = len(task.instructions) + len(task.stable)
    each = len(task.request) / len(sample)
    return estimate_tokens(fixed), estimate_tokens(round(each))


def cost_of_a_day(ws: Any, store: Any, cfg: Any, router: Any, now: datetime | None = None) -> SortingCost:
    """What a typical day of mail costs to sort, on the account the sorting would use first."""
    now = now or datetime.now(UTC)
    per_day, headers = read_mail(ws, store, cfg, now)
    measured = bool(per_day)
    messages = round(statistics.median(per_day)) if measured else cfg.watch.sorting_typical_day
    size = cfg.watch.sorting_batch
    runs = -(-messages // size)
    from engine.watch import data_level_of

    level = data_level_of(cfg, cfg.watch.sources[0]) if cfg.watch.sources else cfg.watch.default_data_level
    first = router.first_choice_for(mail_sorting.KIND, level)
    if first is None:
        return SortingCost(NONE, messages, runs, None, measured)
    if pricing.is_flat(cfg, first.provider):
        return SortingCost(RUNS, messages, runs, None, measured)
    fixed, each = tokens_per_run(ws, cfg, headers, store.read())
    total, left = 0.0, messages
    while left > 0:
        n = min(size, left)
        left -= n
        out = mail_sorting.OUTPUT_TOKENS_PER_MESSAGE * n + 20
        price = router.estimate_for(mail_sorting.KIND, fixed + each * n, out, data_level=level)
        if price is None:
            return SortingCost(UNKNOWN, messages, runs, None, measured)
        total += price
    return SortingCost(MONEY, messages, runs, total, measured)
