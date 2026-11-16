"""Reads a carrier's public tracking page for a delivery that has no arrival day yet.

The carriers' pages are this add-on's data (`carriers.yaml`, `provides.delivery_carriers`): the schedule's Track link
opens them, and the job below reads the same page. The page's text is outside content: it goes to a low-cost AI task
only as the note of a request, which a run may quote as evidence, so a day is taken only when its words are on the
page. A page that can't be read, or says no day, leaves the delivery as it was."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from pydantic import Field

from engine.plugin_api import (
    ConnectorError,
    EventContext,
    PacketContext,
    PacketParts,
    Part,
    Registrar,
    Settings,
)

TASK = "parcels/read-arrival"
JOB = "parcels/lookup"
MINUTES_PER_DAY = 24 * 60


class Config(Settings):
    reads_per_day: int = Field(
        2,
        ge=1,
        le=24,
        description="How many times a day a parcel's carrier page is read while the parcel has no arrival day. The "
        "lookup runs this often, and reads each parcel once each time.",
    )
    max_parcels_per_run: int = Field(
        10, ge=1, le=50, description="The most parcels whose carrier page is read in one run of the lookup."
    )
    page_max_chars: int = Field(
        6000,
        ge=500,
        le=20000,
        description="The most characters of a carrier's page the assistant reads; the rest of a long page is left out.",
    )
    page_min_chars: int = Field(
        40,
        ge=0,
        le=1000,
        description="A page with less text than this once its scripts and markup are taken out (a page that only "
        "works with scripts) is not sent to the assistant, and the parcel stays without a day.",
    )
    task_label: str = Field(
        "Read a delivery's arrival day from the carrier's page",
        description="What the assistant's reading of a carrier's page is called on screen.",
    )


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


def _waiting(entry: Any) -> dict | None:
    """The delivery of a calendar entry that has no day yet and hasn't arrived, or None."""
    delivery = entry.data.get("delivery")
    if not delivery or entry.data.get("cancelled") or entry.data.get("dropped"):
        return None
    if delivery.get("dated", True) or delivery.get("status") == "arrived":
        return None
    return delivery


def lookup(context: EventContext) -> None:
    """Read the carrier's page for each delivery with no day and queue the reading of it. A page that can't be read
    (a refusal, an outage, a host this add-on may not reach) or has no words leaves the delivery alone, with its Track
    link; a parcel already being read is skipped."""
    config = context.config
    reading = {
        r.data["about"]["id"]
        for r in context.list("request", task=TASK)
        if r.data.get("about") and r.data["state"] in ("queued", "running", "review", "needs_you")
    }
    done = 0
    for entry in context.list("event"):
        delivery = _waiting(entry)
        if delivery is None or entry.id in reading:
            continue
        page = context.tracking_page(delivery.get("carrier"), delivery.get("tracking"))
        if page is None or context.web is None:
            continue
        if done >= config.max_parcels_per_run:
            break
        done += 1
        try:
            reply = context.web.get(page)
        except ConnectorError:
            continue
        if reply.status != 200:
            continue
        text = page_text(reply.text, config.page_max_chars)
        if len(text) < max(config.page_min_chars, 1):
            continue
        context.queue_request(TASK, text, about=entry)


def packet(target: Any, view: PacketContext, settings: Config, note: str) -> PacketParts:
    """The parcel as the schedule holds it, and the knowledge that applies; the page's words are the request's note,
    which the run sees as outside content and may quote."""
    delivery = target.data.get("delivery") or {}
    facts = [
        f"{label}: {delivery[key]}"
        for label, key in (("Carrier", "carrier"), ("Tracking number", "tracking"), ("Order", "order"))
        if delivery.get(key)
    ]
    known = view.knowledge(note)
    return PacketParts(
        stable=[known.stable],
        request=[known.per_input, Part("The parcel", "\n".join(facts))],
        max_output=400,
        expected_output=150,
    )


def register(registrar: Registrar) -> None:
    config = registrar.config
    registrar.task_kind(
        TASK,
        ops=("event.add",),
        label=config.task_label,
        prompt=TASK,
        playbook=TASK,
        on="event",
        packet=packet,
        tier="routine",
    )
    registrar.job(JOB, every_minutes=max(MINUTES_PER_DAY // config.reads_per_day, 5), run=lookup)
