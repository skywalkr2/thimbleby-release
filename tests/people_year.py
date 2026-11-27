"""A fictional year of mail headers shaped like a real mailbox, for the look at who the person deals with: a few people
who write and are written back to, sitting under many senders that are machines (digests, shops, notices), which send
far more. Every name and address is made up, on `example.com`. Built from plain numbers so the tally it gives is the
same on every run."""

from __future__ import annotations

from datetime import datetime, timedelta

#: The people the person plainly deals with: the name shown, the address, how many messages came from them in the year
#: and how many the person sent them.
PEOPLE = [
    ("Rowan Achterberg", "rowan.achterberg@example.com", 34, 22),
    ("Imre Vasko", "imre.vasko@example.com", 21, 14),
    ("Odalys Brennecke", "odalys.b@example.com", 15, 9),
    ("Tavish Okonjo", "tavish@okonjo-joinery.example.com", 9, 6),
    ("Liesel Marchetti", "liesel.marchetti@example.com", 7, 5),
    ("Corwin Abara", "careers@staffing.example.com", 6, 4),
]
#: People seen once or twice: nobody to offer on these counts.
PASSING = [
    ("Henrik Solvang", "henrik.solvang@example.com", 1, 0),
    ("Pilar Easton", "pilar.easton@example.com", 1, 1),
]
#: Senders that are machines or lists, each far busier than any person: the name shown, the address, messages a year.
MACHINES = [
    ("Neighborhood Network", "updates@network.example.com", 310),
    ("Spring Shop", "deals@shop.example.com", 160),
    ("Morning Briefing", "newsletter@briefing.example.com", 250),
    ("Calendar", "calendar-notification@cal.example.com", 90),
    ("Parcel Tracking", "no-reply@parcels.example.com", 70),
    ("Account Security", "no-reply@accounts.example.com", 30),
    ("Statements", "notifications@bank.example.com", 44),
    ("Utility Billing", "billing@utility.example.com", 14),
]
#: Smaller machine senders, as a real mailbox has by the dozen: each with more messages than most people.
SMALL_MACHINES = [(f"Store {n} Offers", f"offers@store{n}.example.com", 24 + n) for n in range(1, 41)]


def _spread(key: str, sender: str, count: int, now: datetime, *, bulk: bool, to: list[str] | None = None) -> list[dict]:
    found = []
    for i in range(count):
        days = 8 + (i * 5.5 / count)  # older than the first read's own days, spread over the rest of the import window
        received = (now - timedelta(days=days, minutes=7 * i % 600)).isoformat()
        details = {"sender": sender, "received": received, "unread": bulk, "where": "inbox", "bulk": bulk}
        if to is not None:
            details["participants"] = to
        found.append({"key": f"{key}-{i}", "title": f"Subject {i} of {key}", "text": "", "message": details})
    return found


def inbox_headers(now: datetime) -> list[dict]:
    """The inbox's headers of the year, oldest first."""
    found: list[dict] = []
    for n, (name, address, count) in enumerate([*MACHINES, *SMALL_MACHINES]):
        found += _spread(f"x{n}", f"{name} <{address}>", count, now, bulk=True)
    for n, (name, address, came, _sent) in enumerate([*PEOPLE, *PASSING]):
        found += _spread(f"p{n}", f"{name} <{address}>", came, now, bulk=False)
    return sorted(found, key=lambda e: e["message"]["received"])


def sent_headers(now: datetime, me: str) -> list[dict]:
    """The sent folder's headers of the year, oldest first: each to one of the people."""
    found: list[dict] = []
    for n, (name, address, _came, sent) in enumerate([*PEOPLE, *PASSING]):
        found += _spread(f"s{n}", me, sent, now, bulk=False, to=[f"{name} <{address}>"])
    return sorted(found, key=lambda e: e["message"]["received"])


def recent(now: datetime) -> list[dict]:
    """What the first read itself takes in: the last few days, mostly machines, as a real inbox's are."""
    found = []
    for i, (name, address, _count) in enumerate([*MACHINES[:5], *SMALL_MACHINES[:6]]):
        received = (now - timedelta(days=1 + i % 3, hours=i)).isoformat()
        found.append(
            {
                "key": f"r{i}",
                "title": f"Recent {i}",
                "text": f"From: {name} <{address}>\nSubject: Recent {i}\n\nWords of a notice.",
                "author": f"{name} <{address}>",
                "message": {"sender": f"{name} <{address}>", "received": received, "unread": True, "bulk": True},
            }
        )
    name, address = PEOPLE[0][:2]
    received = (now - timedelta(days=2)).isoformat()
    found.append(
        {
            "key": "r-person",
            "title": "A word about next week",
            "text": f"From: {name} <{address}>\nSubject: A word about next week\n\nA line.",
            "author": f"{name} <{address}>",
            "message": {"sender": f"{name} <{address}>", "received": received, "unread": True},
        }
    )
    return found
