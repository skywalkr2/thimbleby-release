"""A delivery's arrival day, read from the carrier's public tracking page (design 6.19 and 7.7, "Deliveries").

A delivery with no arrival day yet (a mail that gave none) has its carrier's public tracking page read, the same page
its Track link opens. The page is only ever reached at a host one of the known carriers' pages names
(`delivery_tracking.hosts`): the shipped carriers, an add-on's and the workspace's own. The page's words, with scripts
and markup taken out, go to the assistant as outside content, as the note of one request of the `read-arrival` kind
(estimated first and held for the person's go above the configured amount like any other run). The assistant answers
with one `event.add` for that delivery, quoting the page's own words for the day; the applier takes the day only when
those words are in the note. A page that can't be read, has too little text or states no day leaves the delivery as it
was, with its Track link. No account and no key.
"""

from __future__ import annotations

from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any

from engine.storage import WriteContext
from engine.untrusted import neutralize

TASK = "read-arrival"
_ENGINE = WriteContext(actor="engine", trust="trusted", op="delivery_arrival.queue")
#: The request states in which the reading is still with the assistant, or waits for the person.
IN_HAND = ("queued", "running", "review", "needs_you")

_SKIPPED = {"script", "style", "noscript", "template", "svg", "head", "iframe", "object"}
_BLOCKS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "dl", "span", "label", "time", "main", "nav", "form",
}  # fmt: skip


class _Text(HTMLParser):
    """The visible words of a page, one line per block, with scripts, styles and markup left out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIPPED:
            self._skipping += 1
        elif tag in _BLOCKS:
            self.lines.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCKS:
            self.lines.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.lines.append(data)


def page_text(page: str, limit: int) -> str:
    """The words a person would see on a page, in lines, cut at `limit` characters. Plain text comes back as it is."""
    reader = _Text()
    try:
        reader.feed(page)
        reader.close()
    except Exception:  # a page the parser can't read has no words to give
        return ""
    lines = (" ".join(line.split()) for line in "".join(reader.lines).split("\n"))
    return "\n".join(line for line in lines if line)[:limit]


def waiting(entry: Any) -> dict | None:
    """The delivery of a calendar entry that has no day yet and hasn't arrived, or None."""
    delivery = entry.data.get("delivery")
    if not delivery or entry.data.get("cancelled") or entry.data.get("dropped"):
        return None
    if delivery.get("dated", True) or delivery.get("status") == "arrived":
        return None
    return delivery


def lookup(store: Any, cfg: Any, now: datetime, *, web: Any = None) -> list[str]:
    """Read the carrier's page for each delivery with no day and queue the assistant's reading of it. A page that can't
    be read (a refusal, an outage, no connection, a host no carrier names) or has too few words leaves the delivery
    alone; a parcel already being read is skipped. Reads at most `watch.arrival_max_parcels` pages. Returns the ids of
    the requests queued."""
    from engine import delivery_tracking
    from engine.connectors import ConnectorError
    from engine.net import WebClient

    watch = cfg.watch
    added = store.plugins.delivery_carriers() if getattr(store, "plugins", None) else ()
    view = store.read()
    reading = {
        (r.data.get("about") or {}).get("id")
        for r in view.list("request")
        if r.data["task"] == TASK and r.data["state"] in IN_HAND
    }
    client = web
    made: list[str] = []
    done = 0
    try:
        for entry in view.list("event"):
            delivery = waiting(entry)
            if delivery is None or entry.id in reading:
                continue
            page = delivery_tracking.page_for(cfg, delivery.get("carrier"), delivery.get("tracking"), added)
            if page is None:
                continue
            if done >= watch.arrival_max_parcels:
                break
            done += 1
            client = client or WebClient(delivery_tracking.hosts(cfg, added))
            try:
                reply = client.get(page)
            except ConnectorError:
                continue
            if reply.status != 200:
                continue
            text = page_text(reply.text, watch.arrival_page_max_chars)
            if len(text) < max(watch.arrival_page_min_chars, 1):
                continue
            with store.transaction() as tx:
                made.append(
                    tx.create(
                        "request",
                        {
                            "task": TASK,
                            "about": {"kind": "event", "id": entry.id},
                            "note": text,
                            "origin": "schedule",
                            "state": "queued",
                            "waiting": "With the assistant, starting now",
                            "created_at": now.isoformat(),
                        },
                        _ENGINE,
                    ).id
                )
    finally:
        if client is not None and web is None:
            client.close()
    return made


def build(ws: Any, store: Any, cfg: Any, req: Any, kind: Any, today: date) -> Any:
    """The packet for one reading. Stable first: the instructions, the op reference, the practice and what has been
    learned. Then the request: the page's words as outside content, and the parcel as the schedule holds it (its
    carrier, tracking number and order number), so the answer can name the one entry."""
    from dataclasses import replace

    from engine.cleaning import Cleaned
    from engine.dispatcher import _data_level
    from engine.names import PacketPeople
    from engine.ops import reach_choices, reference_for
    from engine.packet import Packet, PacketRefused, _guidance, _learned, _task
    from engine.prompts import render

    about = req.data.get("about") or {}
    target = store.read().get("event", about.get("id", ""))
    if target is None or waiting(target) is None:
        raise PacketRefused("this delivery already has a day, or is gone")
    note = req.data.get("note") or ""
    delivery = target.data["delivery"]
    facts = "\n".join(
        f"{label}: {delivery[key]}"
        for label, key in (("Carrier", "carrier"), ("Tracking number", "tracking"), ("Order", "order"))
        if delivery.get(key)
    )
    people = PacketPeople(store, cfg)
    project = target.data.get("project")
    learned = _learned(
        store,
        cfg,
        kind,
        people,
        projects=[project] if project else [],
        source=None,
        text=note,
        today=today,
    )
    instructions = render(kind.prompt, {"assistant_name": cfg.workspace.assistant_name}, ws.root, kind.prompt_file)
    stable = "\n\n".join(
        part
        for part in (
            "# Op reference\n" + reference_for(list(kind.ops), store.plugins.ops, reach=reach_choices(store.plugins)),
            "# Practice\n" + _guidance(kind),
            learned.stable,
        )
        if part.strip()
    )
    parts = [
        f"Today is {today.isoformat()} ({today.strftime('%A')}).",
        f'<untrusted source="note">\n{neutralize(note)}\n</untrusted>',
        learned.per_input,
        # The carrier, tracking number and order came from a message, so they are outside material too.
        f'# The parcel\n<untrusted source="parcel">\n{neutralize(facts)}\n</untrusted>' if facts else "",
    ]
    request = "\n\n".join(p for p in parts if p)
    task = replace(_task(cfg, store, kind, instructions, stable, request), knowledge=learned.log.model_dump())
    return Packet(
        task,
        facts,
        Cleaned("", 0, 0, False, 0),
        note,
        too_long=False,
        untrusted_material=True,
        cites=f"event:{target.id}",
        about=("event", target.id),
        data_level=_data_level(store, req.data),
        knowledge=learned.log,
    )
