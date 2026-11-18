"""A server for the browser tests: a fresh copy of the imprint fixture whose stand-in AI answers each pasted case with
that case's ideal answer, so the run checks the UI and the pipeline rather than a model.

    uv run python -m tests.e2e_server --port 8781 --base-path /

It also serves the cases at /__e2e/cases so the browser test reads names from the fixture instead of writing them out,
and a few read-only checks of what no screen shows: the ledger of a record, whether the rules and settings are as they
were, and the export round trip of the workspace as it stands. /__e2e/backup-targets switches the configured backup
folder off and on, for the step about having none.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from api.app import create_app
from engine.ai.adapters.stub import set_responder
from engine.cleaning import normalize
from engine.cli import KEEP_ALIVE, add_plugin
from engine.config.yaml_edit import set_key
from engine.evaluate import load_cases
from engine.setup import keep_walkthrough, note_set_by_setup
from engine.storage import WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records
from tests.e2e_just_me import seed_first_go, seed_just_me, the_person
from tests.e2e_many_sides import seed_many_sides
from tests.e2e_meetings import seed_meetings
from tests.e2e_quality import seed_found_promises
from tests.e2e_review_r3 import seed_review_r3
from tests.e2e_review_r4 import seed_review_r4
from tests.e2e_sides import calendar_sources, seed_sides, seed_views
from tests.e2e_worst_case import ACCOUNTS, seed_worst_case, sign_in_in_background, start_services
from tests.e2e_worst_case import seed_sides as seed_worst_sides
from tests.roundtrip import round_trip

TOKEN = "e2e-token"
#: The id of the extra stand-in account `--standin-account` adds; the browser test reads its label from the screen.
STANDIN_ACCOUNT = "standin"
# The longest a run that was told to hold waits for its release.
HOLD_LIMIT_SECONDS = 60
# How long the worst-case server's requests stay unchanged before it says it is ready.
READY_QUIET_SECONDS = 4
LAYOUT_FIXTURE = Path(__file__).parents[1] / "web" / "e2e" / "fixtures" / "layout-strings.json"

# The browser tests run with the wording check on, so a message that names a file, a key or a command fails there too.
os.environ["COCKPIT_CHECK_WORDING"] = "1"


#: The layout check's sources: a mailbox and a calendar that failed to be read, so Today's right column has problems.
LAYOUT_SOURCES = [
    {
        "id": "layout-mail",
        "connector": "mailbox",
        "label": "Work mail",
        "every_minutes": 43200,
        "settings": {"host": "mail.example.com", "user": "rowan@example.com", "password": "env:LAYOUT_PASSWORD"},
    },
    {
        "id": "layout-calendar",
        "connector": "calendar",
        "label": "Work calendar",
        "every_minutes": 43200,
        "settings": {"address": "env:LAYOUT_CALENDAR"},
    },
]


def layout_strings() -> dict[str, str]:
    """Long unbroken made-up strings from the shared layout fixture, by the place each is put."""
    found = {s["id"]: s["text"] for s in json.loads(LAYOUT_FIXTURE.read_text(encoding="utf-8"))}
    return {
        "title": found["token-02"],
        "note": found["web-02"] + " " + found["path-02"],
        "name": found["email-03"],
        "summary": found["token-06"],
        "refusal": found["mail-01"],
        "question": found["invisible-03"],
    }


def seed_layout(store, cfg, stress: dict[str, str]) -> None:
    """Records and a failed read that hold the long strings, so every screen has some to lay out."""
    from datetime import UTC, datetime

    pm = cfg.workspace.user.person
    ctx = WriteContext(actor="pm", trust="trusted", op="e2e.layout")
    with store.transaction() as tx:
        long_project = tx.create("project", {"name": stress["title"], "summary": stress["summary"]}, ctx).id
        tx.create("person", {"full_name": stress["name"], "role": stress["summary"]}, ctx)
        # Forty to-dos under the long-named project: every list is laid out with many rows as well as long ones.
        if pm:
            for number in range(1, 41):
                text = f"Item {number:02d} of the long list"
                tx.create("action", {"text": text, "owners": [{"person": pm}], "project": long_project}, ctx)
        if pm:
            tx.create(
                "question",
                {"to": pm, "title": stress["title"], "text": stress["question"], "kind": "decision"},
                ctx,
            )
        now = datetime.now(UTC).isoformat()
        for source in LAYOUT_SOURCES:
            tx.create(
                "watch_run",
                {
                    "source": source["id"],
                    "started_at": now,
                    "outcome": "failed",
                    "error_kind": "auth",
                    "error": stress["refusal"],
                },
                WriteContext(actor="watcher", trust="trusted", op="watch.run"),
            )


def seed_failed_read(store, cfg) -> str:
    """One failed read of a source an hour before the server's clock, so a problem report has a line to show. Returns
    the error text it was given, so the browser test reads it from here and does not write it out."""
    text = "the source did not answer in time"
    at = datetime.fromisoformat(store.clock()) - timedelta(hours=1)
    data = {
        "source": cfg.watch.sources[0].id,
        "started_at": at.isoformat(),
        "outcome": "failed",
        "error_kind": "outage",
        "error": text,
    }
    with store.transaction() as tx:
        tx.create("watch_run", data, WriteContext(actor="engine", trust="trusted", op="e2e-seed"))
    return text


def seed_outgoing(store, cfg):
    """The core's stand-in channel, registered, and one message drafted to a known person who has an address, waiting
    for the person's yes. Returns the channel and what the browser test reads from the fixture."""
    from engine.applier import apply_as_person
    from engine.channels import FakeChannel
    from engine.names import People

    channel = FakeChannel()
    store.plugins.core_channels["fake"] = channel.registration()
    pm = cfg.workspace.user.person
    person = next(p["id"] for p in fixture_records(DEMO_B, "person") if p["id"] != pm)
    address = "outgoing.recipient@example.com"
    with store.transaction() as tx:
        found = tx.get("person", person)
        reach = {**(found.data.get("how_to_reach") or {}), "email": address}
        tx.update(
            "person",
            person,
            {"how_to_reach": reach},
            WriteContext(actor="pm", trust="trusted", op="e2e.outgoing"),
            read_version=found.version,
        )
    parts = {"subject": "The proofs", "body": "The proofs ship on Monday."}
    op = {
        "op": "act.draft",
        "channel": "fake",
        "target": {"kind": "message", "recipients": [{"person": person, "kind": "email"}]},
        "parts": parts,
    }
    apply_as_person(store, cfg, [op], "Drafted a message to send")
    return channel, {"name": People(store, cfg).name(person), "address": address, **parts}


#: The mailbox the act journey's saved messages came in on, and the account acting is switched on for.
ACTS_SOURCE = "e2e-mail"
ACTS_ACCOUNT = f"mailbox:{ACTS_SOURCE}"
ACTS_SENDER = "sender.one@example.com"
ACTS_ORGANIZER = "organizer@example.com"


def seed_acts(ws, store, cfg):
    """The stand-in channel serving a plain mailbox, with acting on for it, and what the journey acts on: two saved
    messages (one to reply to, one to file away) and an invitation on the calendar. The mailbox's folders are a fixed
    list, since nothing reads a real one. Returns the channel and what the browser test reads from the fixture."""
    from types import SimpleNamespace

    import engine.connectors.mailbox as mailbox
    from engine.channels import FakeChannel

    channel = FakeChannel(accounts=("mailbox",))
    store.plugins.core_channels.pop("mailbox", None)
    store.plugins.core_channels["fake"] = channel.registration()
    mailbox.list_folders = lambda _settings: SimpleNamespace(names=("Inbox", "Projects", "Sent"), sent="Sent")
    pm = cfg.workspace.user.person
    ctx = WriteContext(actor="engine", trust="trusted", op="e2e.acts")
    ws.sources_dir.mkdir(exist_ok=True)

    def message(title: str, text: str, key: str) -> str:
        digest = hashlib.sha256(text.encode()).hexdigest()
        (ws.sources_dir / f"{digest}.txt").write_text(text, encoding="utf-8")
        with store.transaction() as tx:
            return tx.create(
                "source",
                {
                    "received_at": datetime.now(UTC).isoformat(),
                    "kind": "watched:mailbox",
                    "title": title,
                    "content_hash": digest,
                    "trust": "untrusted",
                    "watched": {"source": ACTS_SOURCE, "key": key, "change": "new", "author": ACTS_SENDER},
                },
                ctx,
            ).id

    me = f"{pm or 'me'}@example.com"
    ask = message(
        "Interior proofs",
        f"From: Sender One <{ACTS_SENDER}>\nTo: {me}\nSubject: Interior proofs\n\nCan you confirm the proof date?",
        "<proofs@example.com>",
    )
    tidy = message(
        "Printer invoice",
        f"From: Sender One <{ACTS_SENDER}>\nTo: {me}\nSubject: Printer invoice\n\nThe invoice is attached.",
        "<invoice@example.com>",
    )
    invite = message(
        "Invitation: Planning session",
        f"From: The Organizer <{ACTS_ORGANIZER}>\nTo: {me}\nSubject: Invitation: Planning session\n\nPlease join.",
        "<invite@example.com>",
    )
    with store.transaction() as tx:
        entry = tx.create(
            "event",
            {
                "title": "Planning session",
                "start": "2026-11-03T14:00:00+00:00",
                "end": "2026-11-03T15:00:00+00:00",
                "key": "<planning@example.com>",
                "source": invite,
                "invitation": True,
                "organizer": {"address": ACTS_ORGANIZER, "name": "The Organizer"},
                "trust": "untrusted",
            },
            ctx,
        ).id
    return channel, {
        "account": "E2E mail",
        "reply": {"id": ask, "title": "Interior proofs", "sender": ACTS_SENDER},
        "tidy": {"id": tidy, "title": "Printer invoice"},
        "invitation": {"id": entry, "title": "Planning session", "organizer": ACTS_ORGANIZER},
    }


class FakeForm:
    """The website's problem-report form, played on this computer: it keeps what each report posted and answers with the
    status the test sets (200 takes it)."""

    def __init__(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.received: list[dict] = []
        self.status = 200
        form = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if form.status < 300:
                    form.received.append(json.loads(body))
                self.send_response(form.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": form.status < 300}).encode())

            def log_message(self, *args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.address = f"http://127.0.0.1:{self._server.server_address[1]}/api/report"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--base-path", default="/")
    parser.add_argument(
        "--layout-stress",
        action="store_true",
        help="hold long unbroken made-up text in titles, a Today row, a failing source and a note",
    )
    parser.add_argument(
        "--standin-account",
        action="store_true",
        help="add a second stand-in AI account whose person said Not now about reading work mail and notes, so Today "
        "has the line that offers Allow",
    )
    parser.add_argument(
        "--fake-report",
        action="store_true",
        help="play the website's problem-report form on this computer and point Report a problem at it; "
        "/__e2e/reports says what it received and POST /__e2e/reports/status?code=N sets its answer",
    )
    parser.add_argument(
        "--fake-channel",
        action="store_true",
        help="register the core's stand-in channel and draft one message to a known person on it, so the browser test "
        "can approve and send it; /__e2e/delivered says what the channel was handed",
    )
    parser.add_argument(
        "--acts",
        action="store_true",
        help="serve the stand-in channel for a plain mailbox with acting on, and seed two saved messages and an "
        "invitation for the browser test to reply to, file away and answer; /__e2e/acts says what the channel was "
        "handed and what it took back",
    )
    parser.add_argument(
        "--meetings",
        action="store_true",
        help="seed a calendar entry with another person that starts in a few hours, one with them that has ended with "
        "nothing written down, and a promise of theirs gone quiet, for the meeting journey; /__e2e/meetings says what "
        "was seeded and whether the ended entry has its notes",
    )
    parser.add_argument(
        "--just-me",
        action="store_true",
        help="make the workspace as a person with no work does (no template, nothing besides Personal) and seed an "
        "area, a person with their relation, a to-do and a question on Personal, for the check that no screen shows "
        "work words; /__e2e/just-me says what was seeded",
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help="make a disabled capture-folder source and a private folder for the capture journey",
    )
    parser.add_argument(
        "--sides",
        action="store_true",
        help="make the workspace as --just-me does, add a job and a business as setup adds them, and seed a to-do and "
        "a promise on each side, one to-do on none, a calendar for each side and two meetings of the business "
        "calendar that clash, for the check that the side filter changes what Today, To-dos, Follow-ups and the "
        "Schedule show; "
        "/__e2e/sides says what was seeded",
    )
    parser.add_argument(
        "--assistant-found",
        action="store_true",
        help="seed three promises of the person's own that the assistant found, made at the server's own clock so they "
        "fall inside the quality window, one of them closed, so the quality page shows its figures and not the "
        "too-early card",
    )
    parser.add_argument(
        "--many-sides",
        action="store_true",
        help="make the workspace as --just-me does and add a job and three businesses as setup adds them (five sides "
        "with Personal), three of them with long names, for the check on a person with several businesses; "
        "/__e2e/many-sides says what was seeded",
    )
    parser.add_argument(
        "--review-r3",
        action="store_true",
        help="make the workspace as --many-sides does and seed what the closing tests of batch R3 read: notes, long "
        "to-dos, entries of today past and to come, four items sharing a word; /__e2e/review-r3 says what was seeded",
    )
    parser.add_argument(
        "--review-r4",
        action="store_true",
        help="make the workspace as --many-sides does and seed what the closing tests of batch R4 read: a business's "
        "called-off meeting, overdue to-dos on two sides and none, a repeating solo entry; /__e2e/review-r4 says what "
        "was seeded",
    )
    parser.add_argument(
        "--worst-case",
        action="store_true",
        help="make the workspace as --just-me does and seed the worst case a tester finds the broken things on: five "
        "sides (one named with 100 characters), three signed-in stand-in accounts (the third refused in long words; "
        "the stand-in services run in this process on the next port but one), 50 or more to-dos (overdue, no owner, "
        "waiting, repeating, long titles in four scripts), a week with clashes of 2, 3 and 4 meetings, seven all-day "
        "entries on a day and an empty day, and reviews waiting on Today under several sides; /__e2e/worst-case "
        "says what was seeded and how the sign-ins went",
    )
    parser.add_argument(
        "--first-day",
        action="store_true",
        help="make the workspace as --just-me does but seed nothing except one run waiting for the person's first go, "
        "so Today has the line that offers it: what a person sees on the first day after setup, for the captures and "
        "the check on rows of empty parts",
    )
    parser.add_argument(
        "--all-clear",
        action="store_true",
        help="make the workspace as --just-me does and finish every counted setup step the way the app records it "
        "(the person named, the work answered, an AI account that passed its test, a mail source read, a note handed "
        "in, a backup made, two people) so nothing waits on Today and it shows Nothing needs you",
    )
    parser.add_argument(
        "--plain-stages",
        action="store_true",
        help="leave the stage list as the files hold it (no stage that starts work), so a side added while the app "
        "runs is taken in at once: a changed setting that was also given as a flag waits for a restart and holds back "
        "the rest",
    )
    parser.add_argument(
        "--clock-at",
        metavar="MOMENT",
        help="start the clock at this ISO 8601 moment in UTC (for example 2026-10-21T00:30:00Z); it keeps ticking",
    )
    args = parser.parse_args()
    if args.clock_at:
        import time_machine

        moment = datetime.fromisoformat(args.clock_at.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        time_machine.travel(moment, tick=True).start()
    stress = layout_strings() if args.layout_stress else {}

    # One folder per port, cleared when the next app on that port starts, so stopped runs leave at most one behind.
    tmp = Path(tempfile.gettempdir()) / f"cockpit-e2e-port-{args.port}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    capture_folder = tmp / "capture" if args.capture else None
    if capture_folder is not None:
        capture_folder.mkdir()
    if args.all_clear:
        from tests import e2e_all_clear

        ws = e2e_all_clear.make_workspace(tmp)
    elif (
        args.just_me
        or args.first_day
        or args.sides
        or args.many_sides
        or args.review_r3
        or args.review_r4
        or args.worst_case
    ):
        # Saving the person's name names a workspace that still has the default name after them, as the app does, so no
        # header reads "Workspace".
        ws = init_workspace(tmp / "ws", git=False, you=the_person(), name=f"{the_person().split()[0]}'s")
        note_set_by_setup(ws, {"workspace.name": f"{the_person().split()[0]}'s"})
        # The same stand-in account and tiers the fixture workspaces have, so the person has chosen an account and the
        # walkthrough does not open by itself (a new workspace has none).
        fixture = yaml.safe_load((DEMO_B / "config" / "ai.yaml").read_text(encoding="utf-8"))
        path = ws.config_dir / "ai.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("providers", {})["stub"] = fixture["providers"]["stub"]
        data["tiers"] = fixture["tiers"]
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        # The person pressed Finish later on the walkthrough, so the first visit opens on Today.
        keep_walkthrough(ws, closed=True)
    else:
        ws = init_workspace(tmp / "ws", template=DEMO_B, git=False, history=True)
    (tmp / "offsite").mkdir(exist_ok=True)
    worst_outcome: dict = {"signed_in": [], "error": "not started"}
    if args.worst_case:
        # The mail add-on, and the stand-in outside services it signs in to, before the app is made.
        add_plugin(ws, str(Path(__file__).parent / "fixtures" / "plugins" / "journey_mail"))
        # The example add-on: items with stages whose entry check can fail, for the Stages screen.
        add_plugin(ws, "example")
        start_services(tmp / "services", args.port + 1)
    flags = {
        "server.base_path": args.base_path,
        "server.port": args.port,
        "ai.tiers.routine.use": "stub/default",
        "ai.tiers.routine.fallback": [],
        "storage.backups.targets": [{"path": str(tmp / "offsite"), "label": "test folder"}],
        # Backups only on request, so the browser tests see the state before the first one.
        "storage.backups.automatic": False,
        # Add-ons this test app installs go to its own folder, never the computer's real add-ons folder. Given as a
        # flag like the rest: settings read again from the files and the environment leave a flag's key alone.
        "server.addons_dir": str(tmp / "addons"),
    }
    form = FakeForm() if args.fake_report else None
    if form is not None:
        flags["ui.report_to"] = form.address
    if args.review_r4 or args.review_r3 or args.worst_case:
        # What the seed adds on its own shows whatever the hour the test runs at, so the lines are read as they stand.
        flags["steward.hold_outside_hours"] = False
    if args.all_clear:
        flags.update(e2e_all_clear.flags())
    if args.worst_case:
        # The person's own projects move through steps too, with nothing started by entering one.
        flags["stages.types.project.stages"] = [
            {"id": "planned", "label": "Planned"},
            {"id": "active", "label": "In progress"},
            {"id": "complete", "label": "Complete"},
        ]
    if not (args.plain_stages or args.worst_case):
        # A stage that starts work when entered, so the browser tests can exercise waiting for the go.
        flags["stages.types.project.stages"] = [
            {"id": "planned", "label": "Planned"},
            {"id": "active", "label": "In progress", "starts": ["notes"]},
            {"id": "complete", "label": "Complete"},
        ]
    if stress:
        flags["storage.backups.automatic"] = False
        flags["watch.sources"] = LAYOUT_SOURCES
    if args.acts:
        # A mailbox that is never read (nothing here reaches a real one), with acting switched on for it. In the
        # settings file, so every screen reads it as it would a person's own.
        path = ws.config_dir / "watch.yaml"
        watch = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        watch["sources"] = [
            {"id": ACTS_SOURCE, "connector": "mailbox", "label": "E2E mail", "enabled": False, "every_minutes": 43200}
        ]
        watch["acting"] = [ACTS_ACCOUNT]
        path.write_text(yaml.safe_dump(watch, sort_keys=False), encoding="utf-8")
    if args.sides:
        # The calendars name the sides they serve; the sides are made after the app starts and get these ids.
        path = ws.config_dir / "watch.yaml"
        watch = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        watch["sources"] = calendar_sources()
        path.write_text(yaml.safe_dump(watch, sort_keys=False), encoding="utf-8")
    if capture_folder is not None:
        path = ws.config_dir / "watch.yaml"
        watch = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        watch.setdefault("sources", []).append(
            {
                "id": "capture-journey",
                "connector": "capture",
                "label": "Capture folder",
                "enabled": False,
                "every_minutes": 43200,
                "settings": {"path": str(capture_folder)},
            }
        )
        path.write_text(yaml.safe_dump(watch, sort_keys=False), encoding="utf-8")
    if args.standin_account:
        # In the settings file, not a flag, so Allow's save is what the app reads afterwards.
        path = ws.config_dir / "ai.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["providers"][STANDIN_ACCOUNT] = {
            "adapter": "stub",
            "label": "Second stand-in",
            "models": {"default": "scripted"},
            "allowed_data": ["open"],
            "work_data": "not_now",
        }
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    # The browser tests never read the product's own catalog feed over the network. In the settings file, since the
    # Add-ons screen reads the saved settings.
    path = ws.config_dir / "workspace.yaml"
    path.write_text(
        set_key(path.read_text(encoding="utf-8"), ["plugins", "catalog", "shipped_feed"], False), encoding="utf-8"
    )
    cfg = ws.config(env={}, flags=flags)
    cases = load_cases(DEMO_B)
    project = fixture_records(DEMO_B, "project")[0]["id"]

    capture_text: dict[str, str | None] = {"text": None}

    # A note that says to hold the assistant keeps its run going until /__e2e/release, so a test can look at the header
    # while the assistant is working (and a run left holding ends by itself after the limit).
    release = threading.Event()

    def responder(task):  # the case whose longest pasted line is in the request
        request = normalize(task.request)
        if "hold the assistant" in request:
            release.clear()
            release.wait(timeout=HOLD_LIMIT_SECONDS)
        for case in cases:
            longest = max(case.get("pasted", "").splitlines() or [""], key=len)
            if longest.strip() and normalize(longest) in request:
                return json.dumps(case["stub_answer"])
        if capture_text["text"] and normalize(capture_text["text"]) in request:
            return json.dumps({"summary": "Filed as a note.", "ops": [{"op": "note", "text": capture_text["text"]}]})
        # A note that says it belongs to a project is filed under the fixture's first one; any other is filed loose.
        note = {
            "op": "note",
            "text": "Kept this note for later.",
            **({"project": project} if "under the project" in request else {}),
        }
        if stress:
            note["text"] = stress["note"]
            return json.dumps({"summary": "Filed as a note.", "topic": stress["title"], "ops": [note]})
        return json.dumps({"summary": "Filed as a note.", "ops": [note]})

    set_responder(responder)
    app = create_app(ws, cfg, TOKEN, start_worker=True)
    # The browser tests' own helpers send this token as the bearer; the product takes only a session there.
    app.state.sessions.pin(TOKEN)

    store = app.state.store
    if stress:
        seed_layout(store, cfg, stress)
    folder_targets = list(cfg.storage.backups.targets)
    fake_channel = seed_outgoing(store, cfg) if args.fake_channel else None
    failed_read = seed_failed_read(store, cfg) if form is not None else None
    acts = seed_acts(ws, store, cfg) if args.acts else None
    meetings = seed_meetings(store, cfg) if args.meetings else None
    just_me = seed_just_me(store, cfg) if args.just_me else None
    many_sided = None
    worst_case = None
    if args.sides or args.many_sides or args.review_r3 or args.review_r4 or args.worst_case:
        from starlette.testclient import TestClient

        # The sides are made through the setup route, as setup makes them, so the running app takes them in at once.
        client = TestClient(app, base_url=f"http://127.0.0.1:{args.port}", headers={"Authorization": f"Bearer {TOKEN}"})
        sided = seed_views(store, cfg, seed_sides(client, store, cfg)) if args.sides else None
        many_sided = seed_many_sides(client) if args.many_sides or args.review_r3 or args.review_r4 else None
        if args.worst_case:
            worst_sides = seed_worst_sides(client)
            worst_case = {**worst_sides, **seed_worst_case(ws, store, cfg, worst_sides["ids"])}
    else:
        sided = None
    review_r3 = seed_review_r3(ws, store, cfg, many_sided["ids"]) if args.review_r3 else None
    review_r4 = seed_review_r4(ws, store, cfg, many_sided["ids"]) if args.review_r4 else None
    if args.assistant_found:
        seed_found_promises(store, cfg)
    if args.first_day:
        seed_first_go(store)
    if args.all_clear:
        e2e_all_clear.seed_all_clear(ws, cfg, store)

    async def release_run(_request):
        release.set()
        return JSONResponse({"released": True})

    async def request_burst(request):
        """Stand for the assistant working through many requests at once: write `count` finished requests, one every
        `gap_ms`, each announced to the live stream as its own change, so a page can be tested under a burst."""
        body = await request.json()
        count, gap = int(body.get("count", 50)), int(body.get("gap_ms", 20)) / 1000
        events = app.state.events
        for _ in range(count):
            data = {
                "task": "e2e/burst",
                "origin": "schedule",
                "state": "done",
                "waiting": "",
                "created_at": store.clock(),
                "dismissed": True,
            }
            with store.transaction() as tx:
                tx.create("request", data, WriteContext(actor="engine", trust="trusted", op="e2e.burst"))
            events.changed()
            await asyncio.sleep(gap)
        return JSONResponse({"written": count})

    async def server_now(_request):
        """The server's clock now, in milliseconds, so a page can follow it (web/e2e/test.ts)."""
        return JSONResponse({"now": time.time() * 1000})

    async def case_list(_request):
        return JSONResponse(cases)

    async def ledger(request):
        """The ledger rows of one record, oldest first."""
        kind, record_id = request.query_params["kind"], request.query_params["id"]
        return JSONResponse(store.read().ledger(kind=kind, record_id=record_id))

    async def closed_by_assistant(request):
        """Close an action the way the assistant's own `action.close` does, quoting words from an input, so a journey
        can see the Done tab say who closed it and reopen it: `{"id": ..., "quote": ..., "days_ago": 0}` (the close
        is dated that many days before the server's own clock)."""
        body = await request.json()
        w = WriteContext(
            actor="assistant",
            trust="untrusted",
            op="action.close#0",
            changeset="CS-e2e",
            evidence={"source": None, "quote": body["quote"]},
        )
        with store.transaction() as tx:
            cur = tx.get("action", body["id"])
            owners = [o["person"] for o in cur.data.get("owners", [])]
            tx.update("action", body["id"], {"status": "done", "done_by": owners}, w, read_version=cur.version)
            if body.get("days_ago"):
                then = datetime.fromisoformat(store.clock()) - timedelta(days=int(body["days_ago"]))
                tx.sql(
                    "UPDATE ledger SET at=? WHERE kind='action' AND record_id=?",
                    (then.isoformat(timespec="seconds"), body["id"]),
                )
        return JSONResponse({"closed": body["id"]})

    async def standing(_request):
        """What the rules and settings are: how many rules, and a hash of the settings files and of the settings as the
        app reads them, plus how many changes to settings were proposed or made."""
        files = sorted(ws.config_dir.rglob("*"))
        on_disk = hashlib.sha256(b"".join(p.read_bytes() for p in files if p.is_file())).hexdigest()
        effective = hashlib.sha256(json.dumps(cfg.flat(), default=str).encode()).hexdigest()
        reader = store.read()
        return JSONResponse(
            {
                "rules": len(cfg.rules.rules),
                "settings_files": on_disk,
                "settings": effective,
                "setting_proposals": len(reader.list("setting_proposal", include_deleted=True)),
                "setting_changes": len(reader.list("setting_change", include_deleted=True)),
            }
        )

    async def export_round_trip(_request):
        """Export the workspace as it stands, load that into a fresh database and compare."""
        with tempfile.TemporaryDirectory(prefix="cockpit-e2e-round-trip-") as work:
            return JSONResponse(round_trip(store, cfg, Path(work)))

    async def backup_targets(request):
        """Turn the configured backup folder off (`configured=0`) or back on (`configured=1`)."""
        cfg.storage.backups.targets = folder_targets if request.query_params["configured"] == "1" else []
        return JSONResponse({"configured": len(cfg.storage.backups.targets)})

    async def reports(request):
        """What the played form received (reports it took), and the status it answers with; a POST sets the status."""
        if form is None:
            return JSONResponse({"enabled": False})
        if request.method == "POST":
            form.status = int(request.query_params["code"])
        return JSONResponse(
            {"enabled": True, "received": form.received, "status": form.status, "failed_read": failed_read}
        )

    async def delivered(_request):
        """What the stand-in channel was handed and the message waiting for it: who, where and the parts as drafted."""
        if fake_channel is None:
            return JSONResponse({"enabled": False})
        channel, drafted = fake_channel
        return JSONResponse(
            {
                "enabled": True,
                **drafted,
                "delivered": [
                    {"parts": a.parts, "to": [r.address for r in a.recipients]} for a, _key in channel.delivered
                ],
            }
        )

    async def acted(_request):
        """What the act journey's records are, what the stand-in channel was handed (each act with what it is about, who
        it goes to and what it carries) and what it was asked to take back."""
        if acts is None:
            return JSONResponse({"enabled": False})
        channel, seeded = acts

        def shown(act):
            return {
                "kind": act.kind,
                "action": act.action,
                "parts": act.parts,
                "to": [r.address for r in act.recipients],
                "about": [a.id for a in act.about],
                "label": act.label,
                "folder": act.folder,
                "answer": act.answer,
                "proposed_start": act.proposed_start,
                "proposed_end": act.proposed_end,
            }

        return JSONResponse(
            {
                "enabled": True,
                **seeded,
                "delivered": [shown(a) for a, _key in channel.delivered],
                "undone": [shown(a) for a, _service_id in channel.undone],
            }
        )

    async def met(_request):
        """What the meeting journey's records are, and whether what happened at the ended entry was written down."""
        if meetings is None:
            return JSONResponse({"enabled": False})
        entry = store.read().get("event", meetings["ended"]["id"])
        return JSONResponse({"enabled": True, **meetings, "captured": bool(entry and entry.data.get("captured_at"))})

    async def alone(_request):
        """What the "Just me" journey's records are."""
        return JSONResponse({"enabled": just_me is not None, **(just_me or {})})

    async def with_sides(_request):
        """What the side filter's records are."""
        return JSONResponse({"enabled": sided is not None, **(sided or {})})

    async def with_many_sides(_request):
        """The sides the many-sides seed made, with their long names."""
        return JSONResponse({"enabled": many_sided is not None, **(many_sided or {})})

    async def with_worst_case(_request):
        """What the worst-case seed made, and how the sign-ins of its stand-in accounts went."""
        return JSONResponse({"enabled": worst_case is not None, **(worst_case or {}), "sign_ins": worst_outcome})

    quiet = {"seen": None, "since": time.monotonic()}

    async def worst_case_ready(_request):
        """Answers 200 once the seed's background work is over: every stand-in account is signed in, nothing the
        assistant read from them is queued or running, and the requests have not changed for a few seconds (they are
        filed a moment after the sign-ins), so a first test never races that work."""
        if worst_case is None:
            return JSONResponse({"ready": False}, status_code=404)
        view = store.read()
        every = [r for r in view.find("request", {}) if not r.data.get("dismissed")]
        open_requests = sum(r.data.get("state") in ("queued", "running") for r in every)
        seen = (len(every), open_requests)
        if seen != quiet["seen"]:
            quiet["seen"], quiet["since"] = seen, time.monotonic()
        signed = worst_outcome.get("error") is not None or len(worst_outcome.get("signed_in") or []) >= ACCOUNTS
        ready = signed and open_requests == 0 and time.monotonic() - quiet["since"] >= READY_QUIET_SECONDS
        return JSONResponse({"ready": ready, "open": open_requests}, status_code=200 if ready else 503)

    async def with_review_r3(_request):
        """What the batch R3 closing tests' records are."""
        return JSONResponse({"enabled": review_r3 is not None, **(review_r3 or {})})

    async def with_review_r4(_request):
        """What the batch R4 closing tests' records are."""
        return JSONResponse({"enabled": review_r4 is not None, **(review_r4 or {})})

    capture_count = 0

    async def capture_fixture(request):
        """A private folder for the capture journey; files get fixed names, never paths supplied by the browser."""
        nonlocal capture_count
        if capture_folder is None:
            return JSONResponse({"enabled": False}, status_code=404)
        if request.method == "GET":
            return JSONResponse({"label": "Capture folder"})
        try:
            data = await request.json()
        except ValueError:
            return JSONResponse({"detail": "a note is required"}, status_code=400)
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str) or not text.strip():
            return JSONResponse({"detail": "a note is required"}, status_code=400)
        capture_count += 1
        (capture_folder / f"capture-{capture_count}.txt").write_text(text, encoding="utf-8")
        capture_text["text"] = text
        return JSONResponse({"written": True}, status_code=201)

    outer = Starlette(
        routes=[
            Route("/__e2e/just-me", alone),
            Route("/__e2e/sides", with_sides),
            Route("/__e2e/many-sides", with_many_sides),
            Route("/__e2e/worst-case", with_worst_case),
            Route("/__e2e/worst-case-ready", worst_case_ready),
            Route("/__e2e/review-r3", with_review_r3),
            Route("/__e2e/review-r4", with_review_r4),
            Route("/__e2e/delivered", delivered),
            Route("/__e2e/reports", reports, methods=["GET", "POST"]),
            Route("/__e2e/meetings", met),
            Route("/__e2e/acts", acted),
            Route("/__e2e/capture", capture_fixture, methods=["GET", "POST"]),
            Route("/__e2e/now", server_now),
            Route("/__e2e/release", release_run, methods=["POST"]),
            Route("/__e2e/request-burst", request_burst, methods=["POST"]),
            Route("/__e2e/cases", case_list),
            Route("/__e2e/ledger", ledger),
            Route("/__e2e/closed-by-assistant", closed_by_assistant, methods=["POST"]),
            Route("/__e2e/standing", standing),
            Route("/__e2e/round-trip", export_round_trip),
            Route("/__e2e/backup-targets", backup_targets, methods=["POST"]),
            Mount("/", app=app),
        ],
        lifespan=_lifespan(app),
    )
    if args.worst_case:
        prefix = "" if args.base_path == "/" else args.base_path.rstrip("/")
        sign_in_in_background(f"http://127.0.0.1:{args.port}{prefix}", TOKEN, worst_outcome)
    uvicorn.run(outer, host="127.0.0.1", port=args.port, log_level="warning", timeout_keep_alive=KEEP_ALIVE)


def _lifespan(app):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_outer):
        async with app.router.lifespan_context(app):
            yield

    return lifespan


if __name__ == "__main__":
    main()
