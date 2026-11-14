"""What `tests/e2e_server.py --worst-case` seeds: the workspace a careful tester finds the broken things on, not a
tidy one. Made up throughout; nothing here is read from a real service.

- five sides (Personal and four added as setup adds them), the last with a name of 100 characters;
- three signed-in stand-in accounts, the third refused by its mail server in long words of its own (the stand-in
  outside services, `tests/fake_services.py`, run in this process and the sign-ins go through the app's own routes);
- 50 or more to-dos: overdue ones on every side, ones with no owner, ones waiting on someone, repeating ones, and long
  titles in four scripts (Latin with accents, Cyrillic, Chinese and Japanese, Arabic and Hebrew);
- a week of the person's own calendar entries: clashes of 2, 3 and 4 meetings, seven all-day entries on one day and an
  empty day;
- reviews waiting on Today (endings read from an input, held for the person) under more than one side.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock
from pathlib import Path

from engine.storage import WriteContext
from engine.today import zone
from tests.e2e_many_sides import SIDES

FAILING_ACCOUNT = 3
ACCOUNTS = 3

#: The last side's name: exactly 100 characters, the longest a side may have in the reviewer's worst case.
LONG_SIDE = "Fairweather Valley Community Garden and Seasonal Produce Exchange for Neighboring Households Association"[
    :100
]
assert len(LONG_SIDE) == 100, len(LONG_SIDE)

#: Long titles in four scripts. Each is a plain sentence of an ordinary chore.
SCRIPTS = {
    "latin": "Réserver la salle pour l’assemblée générale annuelle, confirmer le traiteur et envoyer les invitations "
    "avant la fin du mois à Zürich",
    "cyrillic": "Подготовить и отправить подписанные документы в налоговую инспекцию до конца месяца и сохранить копии",
    "chinese": "在月底之前准备并寄出已签署的税务文件，并保留一份副本以备查验，同时通知会计师",
    "japanese": "月末までに署名済みの書類を準備して郵送し、控えを保管してから会計士に連絡する",
    "arabic": "تحضير وإرسال المستندات الموقعة إلى مكتب الضرائب قبل نهاية الشهر والاحتفاظ بنسخة منها",
    "hebrew": "להכין ולשלוח את המסמכים החתומים לרשות המסים לפני סוף החודש ולשמור עותק",
}

#: The people the to-dos wait on or belong to.
PEOPLE = ("Marisol Vandenberg", "Tobias Okonkwo-Reyes", "Ingrid Halvorsen", "Dmitri Castellanos")


def side_names() -> list[tuple[str, str]]:
    """The four sides added beside Personal: the many-sides seed's first three and one of 100 characters."""
    return [*SIDES[:3], (LONG_SIDE, "business")]


def monday(cfg) -> date:
    """The Monday of the current week in the person's own time zone."""
    today = datetime.now(UTC).astimezone(zone(cfg)).date()
    return today - timedelta(days=today.weekday())


def seed_sides(client) -> dict:
    """Add the four sides through the setup route, as setup adds them. Returns their names and ids."""
    ids = []
    names = []
    for name, kind in side_names():
        made = client.post("/api/setup/business", json={"name": name, "kind": kind})
        assert made.status_code == 200, made.text
        ids.append(made.json()["project"])
        names.append(name)
    return {"names": names, "ids": ids}


def seed_worst_case(ws, store, cfg, side_ids: list[str]) -> dict:
    """The people, to-dos, week and reviews described above, on the sides given. Returns what a test reads."""
    from engine.applier import Context, Inputs, apply_changeset
    from engine.names import People
    from engine.ops import CHANGESET

    me = cfg.workspace.user.person
    personal = cfg.workspace.project.personal
    homes = [personal, *side_ids]
    ctx = WriteContext(actor="pm", trust="trusted", op="e2e.worst-case")
    now = datetime.now(UTC)
    here = zone(cfg)
    today = now.astimezone(here).date()

    def day(n: int) -> str:
        return (today + timedelta(days=n)).isoformat()

    def local(moment: datetime) -> str:
        return moment.astimezone(here).strftime("%Y-%m-%dT%H:%M:00")

    made: dict = {"todos": 0, "overdue": 0, "no_owner": 0, "waiting": 0, "repeating": 0, "scripts": 0}
    with store.transaction() as tx:
        people = [
            tx.create("person", {"full_name": name, "how_to_reach": {"email": [f"person{n}@example.com"]}}, ctx).id
            for n, name in enumerate(PEOPLE, 1)
        ]
        made["people"] = people

        def todo(text: str, side: int | None, **more) -> str:
            data = {"text": text, "owners": [{"person": me}], **more}
            if side is not None:
                data["project"] = homes[side]
            made["todos"] += 1
            return tx.create("action", data, ctx).id

        # Overdue, on every side: 3 each, the oldest well over a week back.
        for side in range(len(homes)):
            for n in range(3):
                todo(f"Pay invoice {side}{n} for the {n + 2}-week project", side, due=day(-(3 + 4 * n + side)))
                made["overdue"] += 1
        # Due soon and later, some of each, so lists are in order and some have no date at all.
        for n in range(8):
            todo(f"Draft the outline for report {n + 1}", n % len(homes), due=day(n + 1))
        for n in range(6):
            todo(f"Sort the receipts folder {n + 1}", n % len(homes))
        # Long titles in four scripts (Chinese and Japanese are separate, as are Arabic and Hebrew).
        for n, text in enumerate(SCRIPTS.values()):
            todo(text, n % len(homes), due=day(n + 2))
            made["scripts"] += 1
        # No owner: held for "Pick an owner".
        for n in range(5):
            made["todos"] += 1
            made["no_owner"] += 1
            text = f"Find someone to cover shift {n + 1}"
            held = tx.create(
                "action", {"text": text, "owners": [], "status": "held", "project": homes[n % len(homes)]}, ctx
            )
            # What the applier makes with an action that has no owner: the question that puts "Pick an owner" on Today.
            tx.create(
                "question",
                {
                    "to": me,
                    "title": f"Pick an owner: {text}",
                    "kind": "routing",
                    "options": [],
                    "resolves": {"kind": "owner", "action": held.id, "changeset": None},
                    "projects": [homes[n % len(homes)]],
                },
                ctx,
            )
        # Waiting on someone: on hold with words, and others' to-dos the person already told them about.
        for n in range(4):
            todo(
                f"Move forward with the quote {n + 1}",
                n % len(homes),
                on_hold={"waiting_for": f"The reply from {PEOPLE[n % len(PEOPLE)]}", "since": day(-2 - n)},
            )
            made["waiting"] += 1
        for n in range(4):
            made["todos"] += 1
            made["waiting"] += 1
            tx.create(
                "action",
                {
                    "text": f"Send the signed form {n + 1}",
                    "owners": [{"person": people[n % len(people)]}],
                    "told": {people[n % len(people)]: day(-3 - n)},
                    "due": day(2 + n),
                    "project": homes[n % len(homes)],
                },
                ctx,
            )
        # Repeating: each is the first occurrence of a series.
        for n, (phrase, rule) in enumerate(
            (
                ("every week", "FREQ=WEEKLY"),
                ("every day", "FREQ=DAILY"),
                ("every month", "FREQ=MONTHLY"),
                ("every Friday", "FREQ=WEEKLY;BYDAY=FR"),
            )
        ):
            todo(
                f"Water the plants ({phrase})",
                n % len(homes),
                due=day(n),
                repeat={"rule": rule, "phrase": phrase, "start": day(n)},
            )
            made["repeating"] += 1
        # A few to-dos that are plainly ordinary, so the list is not only the hard cases.
        for n in range(8):
            todo(f"Call the supplier about order {n + 1}", n % len(homes), due=day(5 + n))
    # Questions and others' promises, so the other tabs hold something.
    with store.transaction() as tx:
        for n, home in enumerate(homes):
            tx.create(
                "question",
                {
                    "to": me,
                    "title": f"Which option do you want for plan {n + 1}?",
                    "kind": "decision",
                    "projects": [home],
                },
                ctx,
            )
        for n, home in enumerate(homes[:3]):
            tx.create(
                "action",
                {
                    "text": f"Confirm the print run {n + 1}",
                    "owners": [{"person": made["people"][n]}],
                    "promised_to": [me],
                    "project": home,
                },
                ctx,
            )
    # The week: Monday a clash of 2, Tuesday of 3, Wednesday of 4 and seven all-day entries, Thursday empty, Friday a
    # plain day. Some entries sit on a side, some on none.
    start = monday(cfg)

    def at(n: int, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(start + timedelta(days=n), clock(hour, minute), tzinfo=here)

    def meeting(tx, title: str, begins: datetime, minutes: int, side: int | None = None) -> None:
        data = {
            "title": title,
            "start": local(begins),
            "end": local(begins + timedelta(minutes=minutes)),
            "trust": "trusted",
        }
        if side is not None:
            data["project"] = homes[side]
        tx.create("event", data, ctx)

    with store.transaction() as tx:
        for n in range(2):
            meeting(tx, f"Budget review {n + 1} with the finance group", at(0, 10, 30 * n), 60, n % len(homes))
        for n in range(3):
            meeting(tx, f"Supplier call {n + 1}", at(1, 14, 15 * n), 60, (n + 1) % len(homes))
        for n in range(4):
            meeting(tx, f"Planning session {n + 1} for the spring season", at(2, 11, 10 * n), 90, (n + 2) % len(homes))
        for n in range(7):
            tx.create(
                "event",
                {
                    "title": f"All-day entry {n + 1}: "
                    + ("Community open house and tour of the garden program for every season" if n % 2 else "Holiday"),
                    "start": (start + timedelta(days=2)).isoformat(),
                    "trust": "trusted",
                    **({"project": homes[n % len(homes)]} if n % 3 else {}),
                },
                ctx,
            )
        meeting(tx, "Quarterly review of the whole year with all the partners and their guests", at(4, 9), 120, 1)
        meeting(tx, "Team lunch", at(4, 12, 30), 60)
        # Nothing on Thursday.
    made["week"] = {
        "monday": start.isoformat(),
        "clashes": {"mon": 2, "tue": 3, "wed": 4},
        "all_day": {"wed": 7},
        "empty": (start + timedelta(days=3)).isoformat(),
    }

    # Reviews waiting on Today: an ending read from an input (a message), held for the person's yes, one per side, each
    # on a to-do of someone else's that sits on that side.
    reviews = []
    for n, home in enumerate(homes):
        with store.transaction() as tx:
            action = tx.create(
                "action",
                {
                    "text": f"Send the draft agreement {n + 1}",
                    "owners": [{"person": people[n % len(people)]}],
                    "project": home,
                    "due": day(2),
                },
                ctx,
            ).id
            quote = f"The agreement {n + 1} went out yesterday"
            source = tx.create(
                "source",
                {
                    "received_at": now.isoformat(),
                    "kind": "pasted",
                    "title": f"Message {n + 1}",
                    "content_hash": f"{n:064d}",
                    "trust": "untrusted",
                },
                ctx,
            ).id
            request = tx.create(
                "request",
                {"task": "notes", "origin": "input", "state": "done", "created_at": now.isoformat(), "source": source},
                ctx,
            ).id
        changeset = CHANGESET.validate_python(
            {"ops": [{"op": "action.close", "id": action, "evidence": {"quote": quote}}]},
            context={"op_models": store.plugins.ops},
        )
        inputs = Inputs(request, source, quote, "", "untrusted")
        context = Context(store, cfg, People(store, cfg), tuple(store.plugins.ops), inputs, actor="assistant")
        changeset_id = apply_changeset(changeset, [], context, run=None)
        with store.transaction() as tx:
            found = tx.get("request", request)
            tx.update("request", request, {"changeset": changeset_id}, ctx, read_version=found.version)
        status = store.read().get("changeset", changeset_id).data["ops"][0]["status"]
        reviews.append({"side": home, "action": action, "changeset": changeset_id, "status": status})
    made["reviews"] = reviews
    made["sides"] = homes
    return made


# ---- the stand-in accounts -----------------------------------------------------------------------------------------


def start_services(state_folder: Path, https_port: int):
    """Run the stand-in outside services (mail and calendar for three accounts, the third refused in long words) over
    HTTPS from this process, and make this process trust them the standard way. Returns their state. Call it before
    the app is made, so the mail add-on finds where its service is."""
    from tests import fake_services

    state_folder.mkdir(parents=True, exist_ok=True)
    state = fake_services.State(state_folder)
    state.accounts = ACCOUNTS
    state.spread_week = True
    state.failing_account = FAILING_ACCOUNT
    state.failing_how = "refused"
    fake_services.start_secure(state, https_port, ())
    os.environ["SSL_CERT_FILE"] = str(state_folder / "tls" / "authority.pem")
    os.environ.pop("SSL_CERT_DIR", None)
    os.environ["JOURNEY_SERVICE_ADDRESS"] = f"https://127.0.0.1:{https_port}"
    for name in ("NO_PROXY", "no_proxy"):
        hosts = [h for h in os.environ.get(name, "").split(",") if h]
        if "127.0.0.1" not in hosts:
            os.environ[name] = ",".join([*hosts, "127.0.0.1"])
    return state


def sign_in_all(base: str, token: str, sign_in: str = "journey-mail/account", outcome: dict | None = None) -> None:
    """Sign each stand-in account in through the app's own routes, as the sign-in window does: start, follow the
    service's page to the app's callback. Runs once the app answers; `outcome` is filled with how it went."""
    import httpx

    from tests import fake_services

    headers = {"Authorization": f"Bearer {token}"}
    result = outcome if outcome is not None else {}
    result.update({"signed_in": [], "error": None})
    try:
        with httpx.Client(base_url=base, headers=headers, timeout=30, trust_env=False) as app:
            for _ in range(200):
                try:
                    if app.get("/api/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            for number in range(ACCOUNTS):
                address = fake_services.account_address(number)
                started = app.post(f"/api/sign-ins/{sign_in}/start")
                started.raise_for_status()
                url = started.json()["url"]
                url += ("&" if "?" in url else "?") + "login_hint=" + address
                verify = os.environ["SSL_CERT_FILE"]
                with httpx.Client(verify=verify, follow_redirects=False, trust_env=False, timeout=30) as service:
                    landed = service.get(url)
                    assert landed.status_code == 302, landed.text
                    back = landed.headers["location"]
                done = app.get(back.replace(base, ""), headers={})
                done.raise_for_status()
                result["signed_in"].append(address)
    except Exception as err:  # noqa: BLE001 - reported through `outcome`, never raised into the server
        result["error"] = repr(err)


def sign_in_in_background(base: str, token: str, outcome: dict) -> threading.Thread:
    thread = threading.Thread(target=sign_in_all, args=(base, token, "journey-mail/account", outcome), daemon=True)
    thread.start()
    return thread


def describe(seeded: dict) -> str:
    return json.dumps({k: v for k, v in seeded.items() if k != "reviews"}, default=str)
