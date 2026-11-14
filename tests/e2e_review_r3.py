"""What `tests/e2e_server.py --review-r3` seeds, for the closing browser tests of batch R3 (Today, notes and to-dos,
from the review): the long and the many that the reviewer's states have. A workspace made as a person with no work makes
it, with the many-sides seed's sides; this adds, as the person would have made them: notes (a long note, a calendar
note whose body is its first line, a short one), to-dos with very long titles and with a full stop ending the title,
four items that share a word (so Today offers an area), entries on today's schedule that are past, under way and to
come, one with a title as long as a paragraph, a person with to-dos of theirs (one already sent), the same promise
three times over, and a message that came in. Every name and text is made up."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from engine.storage import WriteContext
from engine.today import zone

THREE_SENTENCES = (
    "I spoke to the caterer this morning about the Saturday lunch, the long table by the windows and the "
    "vegetarian plates for "
    "the late arrivals. They need the final numbers by Thursday noon and the deposit by Friday, and they will"
    " not hold the date "
    "past then without both. The allergy list is attached to the booking confirmation, so please check it "
    "against the guest "
    "list before you reply to them, and tell them about the two children who need a smaller portion."
)
CALENDAR_NOTE = (
    "New in Your calendar: Offsite day Offsite day When: Thu, Nov 19, 2026, 15:13 to Thu, Nov 19, 2026, 15:43"
    " Where: The "
    "lodge Everyone arrives by nine."
)
LONG_TODO = (
    "Print, sign and mail the unclaimed property claim forms, the covering letter and the cheque to the State"
    " Treasurer's office, "
    "14 Quarry Lane, Northampton, NN1 4XY, United Kingdom, before the end of the month, and keep a copy of "
    "the signed forms"
)
VERY_LONG_TODO = " ".join(
    ["Reconcile the supplier invoices against the delivery notes and the purchase orders for the autumn range"] * 6
)
VERY_LONG_EVENT = " ".join(
    ["Annual planning offsite for the whole regional team with the partners and their guests"] * 5
)
STOPPED_TODO = "Send the headcount."
SENT_TITLE = "Send the venue list by 2026-11-02."
DATED_TODO = "Bring the floor plan."
SWATCH_TEXTS = (
    "Order the swatches for the curtains",
    "Compare the swatches by daylight",
    "Return the swatches to the shop",
    "Photograph the swatches",
)


def seed_review_r3(ws, store, cfg, side_ids: list[str]) -> dict:
    me = cfg.workspace.user.person
    personal = cfg.workspace.project.personal
    ctx = WriteContext(actor="pm", trust="trusted", op="e2e.review-r3")
    now = datetime.now(UTC)
    here = zone(cfg)

    def local(moment: datetime) -> str:
        """An entry's time as the app keeps its own entries': the person's own wall clock, with no offset."""
        return moment.astimezone(here).strftime("%Y-%m-%dT%H:%M:00")

    due = (now + timedelta(days=3)).date().isoformat()
    made: dict = {}
    # A message that came in, kept as the watcher keeps one: its text by its hash, and who it was from.
    body = "Hello,\n\nThe swatches for the curtains are ready to collect from the shop on Quarry Lane.\n\nThanks, Sam"
    digest = hashlib.sha256(body.encode()).hexdigest()
    ws.sources_dir.mkdir(exist_ok=True)
    (ws.sources_dir / f"{digest}.txt").write_text(body, encoding="utf-8")
    with store.transaction() as tx:
        made["source"] = tx.create(
            "source",
            {
                "received_at": (now - timedelta(hours=2)).isoformat(),
                "sent_at": (now - timedelta(hours=2, minutes=3)).isoformat(),
                "kind": "watched:mailbox",
                "title": "Swatches ready to collect",
                "content_hash": digest,
                "trust": "untrusted",
                "watched": {
                    "source": "r3-mail",
                    "key": "<swatches@example.com>",
                    "change": "new",
                    "author": "Sam Example <sam@example.com>",
                },
            },
            ctx,
        ).id
        # Someone else's side of the work, for Follow-ups: one to-do already sent (and so waiting), one not yet sent
        # and one whose
        # title is long, all due soon, so the same reading shows in every grouping.
        supplier = tx.create(
            "person", {"full_name": "Sam Vendor", "how_to_reach": {"email": ["sam.vendor@example.com"]}}, ctx
        ).id
        made["supplier"] = supplier
        soon = (now + timedelta(days=2)).date().isoformat()
        told = (now - timedelta(days=1)).date().isoformat()
        made["sent_item"] = tx.create(
            "action",
            {
                "text": "Send the swatches",
                "owners": [{"person": supplier}],
                "due": soon,
                "told": {supplier: told},
                "project": side_ids[1],
            },
            ctx,
        ).id
        made["unsent_item"] = tx.create(
            "action",
            {
                "text": "Return the signed order form",
                "owners": [{"person": supplier}],
                "due": soon,
                "project": side_ids[1],
            },
            ctx,
        ).id
        made["long_item"] = tx.create(
            "action", {"text": LONG_TODO, "owners": [{"person": supplier}], "due": soon}, ctx
        ).id
        made["very_long_item"] = tx.create(
            "action", {"text": VERY_LONG_TODO, "owners": [{"person": supplier}], "due": soon}, ctx
        ).id
        # Enough more that Follow-ups draws its grouping choice (a short list has none).
        for n in range(1, 11):
            tx.create("action", {"text": f"Return the form ({n})", "owners": [{"person": supplier}]}, ctx)
        made["organization"] = tx.create("organization", {"name": "Quarry Press"}, ctx).id
        made["team"] = tx.create("team", {"name": "The print crew"}, ctx).id
    with store.transaction() as tx:
        made["note"] = tx.create("note", {"text": THREE_SENTENCES}, ctx).id
        made["calendar_note"] = tx.create("note", {"text": CALENDAR_NOTE, "trust": "untrusted"}, ctx).id
        made["short_note"] = tx.create("note", {"text": "Ring the printer about the proofs"}, ctx).id
        for key, text in (
            ("long", LONG_TODO),
            ("very_long", VERY_LONG_TODO),
            ("stopped", STOPPED_TODO),
            ("sent", SENT_TITLE),
            ("dated", DATED_TODO),
        ):
            made[key] = tx.create("action", {"text": text, "owners": [{"person": me}], "due": due}, ctx).id
        # The same promise three times over (what one sent message held by three mailboxes made), due one day, for
        # the Month's fold.
        # Today, so the same week (and the same month) shows it whatever the weekday the run starts on.
        alone = now.astimezone(here).date().isoformat()
        for _ in range(3):
            tx.create("action", {"text": "Send the revised budget.", "owners": [{"person": me}], "due": alone}, ctx)
        for text in SWATCH_TEXTS:
            tx.create("action", {"text": text, "owners": [{"person": me}], "project": personal, "due": due}, ctx)
        # Entries of today: one that ended, one under way, one to come, and one with a title as long as a paragraph,
        # all the
        # person's own, so none depends on a calendar being connected.
        for key, title, start, end in (
            ("past", "Take the tablets", now - timedelta(minutes=50), now - timedelta(minutes=35)),
            ("coming", "Yoga class", now + timedelta(minutes=40), now + timedelta(minutes=100)),
            ("later", "Call the printer", now + timedelta(minutes=130), now + timedelta(minutes=150)),
            ("later2", "Collect the proofs", now + timedelta(minutes=170), now + timedelta(minutes=190)),
            ("later3", "Pay the deposit", now + timedelta(minutes=210), now + timedelta(minutes=230)),
            ("long_title", VERY_LONG_EVENT, now + timedelta(days=1), now + timedelta(days=1, hours=1)),
        ):
            made[key] = tx.create(
                "event", {"title": title, "start": local(start), "end": local(end), "trust": "trusted"}, ctx
            ).id
    # A meeting read from a calendar, under way: a calendar's entries and the person's own are one list in time order.
    with store.transaction() as tx:
        tx.create(
            "snapshot",
            {
                "source": "r3-calendar",
                "key": "design-review",
                "title": "Design review",
                "content_hash": "design-review",
                "seen_at": now.isoformat(),
                "event": {
                    "start": (now + timedelta(minutes=15)).isoformat(),
                    "end": (now + timedelta(minutes=75)).isoformat(),
                },
            },
            ctx,
        )
    made.update(
        {
            "three_sentences": THREE_SENTENCES,
            "calendar_note_text": CALENDAR_NOTE,
            "long_todo": LONG_TODO,
            "very_long_todo": VERY_LONG_TODO,
            "very_long_event": VERY_LONG_EVENT,
            "stopped_todo": STOPPED_TODO,
            "sent_title": SENT_TITLE,
            "dated_todo": DATED_TODO,
            "due": due,
        }
    )
    return made
