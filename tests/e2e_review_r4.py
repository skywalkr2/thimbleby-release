"""What `tests/e2e_server.py --review-r4` seeds, for the closing browser tests of batch R4 (trust, mail, sides and
counts, from the review): a workspace with the many-sides seed's sides, and as the person would have made them a
called-off
meeting of one business, overdue to-dos on two sides and on none, and two repeating entries of the person's own, one
with a part they chose (they attend it) and one with none (a class). Every name is made up."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from engine.storage import WriteContext
from engine.today import zone


def seed_review_r4(ws, store, cfg, side_ids: list[str]) -> dict:
    me = cfg.workspace.user.person
    ctx = WriteContext(actor="pm", trust="trusted", op="e2e.review-r4")
    now = datetime.now(UTC)
    here = zone(cfg)

    def local(moment: datetime) -> str:
        return moment.astimezone(here).strftime("%Y-%m-%dT%H:%M:00")

    first, last = side_ids[0], side_ids[3]
    late = (now - timedelta(days=4)).date().isoformat()
    made: dict = {"first_side": first, "last_side": last}
    with store.transaction() as tx:
        made["called_off"] = tx.create(
            "event",
            {
                "title": "Planning chat",
                "start": local(now + timedelta(days=1, hours=1)),
                "end": local(now + timedelta(days=1, hours=2)),
                "project": last,
                "cancelled": True,
                "trust": "trusted",
            },
            ctx,
        ).id
        for text, side in (
            ("Send the board minutes", first),
            ("Pay the venue deposit", first),
            ("Order the lanterns", last),
            ("Renew the passport", None),
        ):
            data = {"text": text, "owners": [{"person": me}], "due": late}
            if side:
                data["project"] = side
            tx.create("action", data, ctx)
        for title, role, begins in (("Yoga class", None, 40), ("Team sync", "attend", 60)):
            entry = {
                "title": title,
                "start": local(now + timedelta(minutes=begins)),
                "end": local(now + timedelta(minutes=begins + 30)),
                "repeat": {"every": "week", "until": None},
                "trust": "trusted",
            }
            if role:
                entry["role"] = role
            tx.create("event", entry, ctx)
    # Two messages a rule set aside, from two senders and two groups, for Handled for you: Bring it in and Undo must
    # put the message back under its own group and reason.
    ws.sources_dir.mkdir(exist_ok=True)
    marks = (
        (
            "Spring sale at the lamp shop",
            "offers@lists.example.com",
            "sales",
            "Mailing list",
            "it was sent to many people",
        ),
        (
            "Neighbors posted a notice",
            "updates@network.example.com",
            "notices",
            "Social",
            "your mail service files it under social",
        ),
    )
    handled: list[dict] = []
    for n, (title, sender, section, rule, reason) in enumerate(marks):
        body = f"From: Someone <{sender}>\nSubject: {title}\n\nPlain words."
        digest = hashlib.sha256(body.encode()).hexdigest()
        (ws.sources_dir / f"{digest}.txt").write_text(body, encoding="utf-8")
        at = (now - timedelta(hours=2 + n)).isoformat()
        with store.transaction() as tx:
            tx.create(
                "snapshot",
                {
                    "source": "r4-mail",
                    "key": f"<r4-{n}@example.com>",
                    "title": title,
                    "content_hash": digest,
                    "author": f"Someone <{sender}>",
                    "seen_at": at,
                    "message": {"sender": f"Someone <{sender}>", "received": at, "unread": True},
                    "set_aside": {"section": section, "rule": rule, "reason": reason, "by": "rule", "at": at},
                },
                ctx,
            )
        handled.append({"title": title, "reason": reason})
    made["handled"] = handled
    # The same unknown name asked about by two inputs (two held items), and one plain question: Today has one line for
    # the name, and the person's own page counts what the Questions tab counts.
    made["me"] = me
    made["unknown_name"] = "Someone New"
    with store.transaction() as tx:
        for n in (1, 2):
            tx.create(
                "question",
                {
                    "to": me,
                    "title": "Who is \u201cSomeone New\u201d?",
                    "kind": "routing",
                    "resolves": {"kind": "held-op", "changeset": f"CS-90{n}", "op": 0, "name": "Someone New"},
                },
                ctx,
            )
        tx.create("question", {"to": me, "title": "Which paper for the program?", "kind": "decision"}, ctx)
    made.update({"sides": side_ids, "late_first": 2, "late_last": 1, "late_none": 1})
    return made
