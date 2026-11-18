"""What reading a number of a source's messages would cost: about what it will cost, and the most it could.

A read of mail is priced as it will happen. Every message goes through the header sorting (one run per
`watch.sorting_batch`, none when sorting is by rules only); only the share the sorting keeps is read in full; and an
account's cache charges the packet's stable part of every run after the first at its cached price. The most is the
price with none of that: every message read in full and every input token at the full price.

The kept share is counted from what the source already took in (mail the sorting kept or set aside), and
`watch.estimate_kept_share` stands in before a batch of sorted mail is known. The price of one full read comes from a
packet the source's earlier requests built (so its stable and request parts are real), and falls back to the average
of what those requests were estimated at, uncached, when no packet can be built.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from engine import mail_sorting, sorting_cost, watch
from engine.dispatcher import run_price_request
from engine.sorting_lessons import set_aside_by_sorting


@dataclass(frozen=True)
class ReadCost:
    """About what a read costs (`likely`) and the most it could (`at_most`); None when nothing has a price. `unpriced`
    is how many messages some part of the work has no price for."""

    likely: float | None
    at_most: float | None
    unpriced: int = 0


def router_for(cfg: Any, store: Any, router: Any = None) -> Any:
    """The given router, or one made for this workspace."""
    if router is not None:
        return router
    from engine.ai.router import Router

    return Router(cfg, store, env=os.environ)


def kept_share(store: Any, cfg: Any, source_id: str) -> float:
    """The share of this source's messages the sorting kept (read in full), counted from the mail it already took in:
    with the assistant's sorting, the messages it answered and kept against those it set aside; with rules only, the
    messages no rule set aside against those one did. `watch.estimate_kept_share` until a batch (`watch.sorting_batch`)
    of messages is known."""
    view = store.read()
    aside = 0
    snapshots: set[str] = set()
    for snap in view.find("snapshot", {"source": source_id}):
        data = snap.data
        if not data.get("message") or data.get("gone"):
            continue
        if set_aside_by_sorting(data.get("set_aside")):
            aside += 1
        else:
            snapshots.add(data["key"])
    if cfg.watch.sorting == "ai":
        kept = 0
        for req in view.list("request"):
            if req.data.get("mail_kind") is None or req.data.get("set_aside") or not req.data.get("source"):
                continue
            record = view.get("source", req.data["source"])
            watched = (record.data.get("watched") if record else None) or {}
            if watched.get("source") == source_id:
                kept += 1
    else:
        kept = len(snapshots)
    known = kept + aside
    if known < cfg.watch.sorting_batch:
        return cfg.watch.estimate_kept_share
    return kept / known


def sorting_range(
    ws: Any, store: Any, cfg: Any, router: Any, source: Any, count: int, now: datetime
) -> tuple[float, float, int]:
    """What sorting `count` messages' headers costs, as (likely, at most, messages it has no price for): one run per
    `watch.sorting_batch`, each of a full batch of headers like the source's own (an invented ordinary header when
    none was read). Nothing when sorting is by rules only."""
    if cfg.watch.sorting != "ai" or count <= 0:
        return 0.0, 0.0, 0
    size = cfg.watch.sorting_batch
    _per_day, headers = sorting_cost.read_mail(ws, store, cfg, now)
    sample = [h for h in headers if h.key]
    if not sample:
        sample = [mail_sorting.Header("m", sorting_cost._SENDER, sorting_cost._SUBJECT)]
    batch = [sample[n % len(sample)] for n in range(size)]
    task, _ids = mail_sorting.build_task(ws, cfg, batch, store.read())
    level = watch.data_level_of(cfg, source)
    price = router.run_price(task, tier=mail_sorting._tier_of(cfg, task, level), data_level=level)
    if price is None:
        return 0.0, 0.0, count
    likely, at_most = price.runs(math.ceil(count / size))
    return likely, at_most, 0


def read_range(
    ws: Any, store: Any, cfg: Any, router: Any, source_id: str, kept: float, most: int, now: datetime
) -> tuple[float, float] | None:
    """What reading `kept` messages in full costs (likely; the expected number kept, so it may have a fraction) and
    `most` of them (at most), from a packet this source's earlier requests built; None when no price is known."""
    view = store.read()
    mine = sorted(
        (r for r in view.list("request") if r.data.get("intake") == source_id),
        key=lambda r: str(r.data.get("created_at")),
        reverse=True,
    )
    for req in mine[:3]:
        price = run_price_request(ws, store, cfg, router, req.id, now)
        if price is not None:
            return price.runs(kept)[0], price.runs(most)[1]
    prices = [r.data["estimate_usd"] for r in mine if r.data.get("estimate_usd") is not None]
    if prices:
        average = sum(prices) / len(prices)
        return average * kept, average * most
    return None


def cost_of_reading(
    ws: Any,
    store: Any,
    cfg: Any,
    source: Any,
    count: int,
    now: datetime | None = None,
    router: Any = None,
    sorted_count: int | None = None,
) -> ReadCost:
    """About what reading `count` messages of the source costs and the most it could: the sorting for all of them plus
    the full read of the share the sorting keeps (all of them for the most). `sorted_count` is how many still go
    through the sorting when that is fewer than `count`."""
    if count <= 0:
        return ReadCost(0.0, 0.0)
    now = now or datetime.now(UTC)
    router = router_for(cfg, store, router)
    through = count if sorted_count is None else min(sorted_count, count)
    sort_likely, sort_most, sort_unpriced = sorting_range(ws, store, cfg, router, source, through, now)
    kept = min(count, through * kept_share(store, cfg, source.id) + (count - through))
    read = read_range(ws, store, cfg, router, source.id, kept, count, now)
    if read is None:
        if sort_unpriced or (sort_likely == 0.0 and sort_most == 0.0):
            return ReadCost(None, None, count)
        return ReadCost(round(sort_likely, 4), round(sort_most, 4), count)
    unpriced = count if sort_unpriced else 0
    likely, at_most = read[0] + sort_likely, read[1] + sort_most
    return ReadCost(round(likely, 4), round(max(at_most, likely), 4), unpriced)
