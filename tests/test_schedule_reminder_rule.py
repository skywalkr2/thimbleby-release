"""A kept rule can put a reminder on the schedule for mail it matches (S-0680): the reading adds one dated entry in the
app's own calendar, quoting the mail, and no to-do. The entry is local data (applied at once, shown on the Schedule,
taken back by Undo), and the case in the evaluation set holds the reading to it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.applier import undo
from engine.workspace import init_workspace
from tests.conftest import DEMO_A
from tests.e2e_just_me import the_person
from tests.test_evaluate_harness import run_edited
from tests.test_knowledge_records import apply, source
from tests.test_views import TOKEN, Env

CASE = "rule-puts-autopay-notice-on-the-schedule"
MAIL = "Your payment will be taken automatically from your checking account on October 21. Nothing to do."
QUOTE = "taken automatically from your checking account on October 21"


@pytest.fixture
def env(tmp_path):
    ws = init_workspace(tmp_path / "ws", git=False, you=the_person())
    cfg = ws.config(env={"COCKPIT__WORKSPACE__USER__TIMEZONE": "UTC"}, flags={"storage.backups.automatic": False})
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield Env(client, app.state.store, cfg, app)


def reminder_from_mail(env):
    sid = source(env.store, content_hash="1" * 64)
    op = {"op": "event.add", "title": "Pay Provider", "start": "2026-10-21", "evidence": {"quote": QUOTE}}
    return apply(env.store, env.cfg, [op], origin="input", trust="untrusted", source_id=sid, raw=MAIL)


def titles_on(env, day):
    days = env.client.get("/api/schedule", params={"from": day, "days": 1}).json()["days"]
    return [e["title"] for d in days for e in [*d["all_day"], *d["timed"]]]


def test_a_reminder_from_a_mail_is_applied_at_once_and_shows_on_the_schedule(env):
    _, statuses = reminder_from_mail(env)
    assert statuses == ["applied"]
    assert "Pay Provider" in titles_on(env, "2026-10-21")


def test_undo_takes_the_reminder_off_the_schedule(env):
    cs, _ = reminder_from_mail(env)
    undo(env.store, cs)
    assert "Pay Provider" not in titles_on(env, "2026-10-21")


def test_the_case_passes_with_an_entry_and_no_to_do(monkeypatch):
    assert run_edited(monkeypatch, DEMO_A, CASE).passed


def test_the_case_fails_when_the_reading_makes_a_to_do_or_no_entry(monkeypatch):
    todo = {
        "summary": "x",
        "ops": [
            {
                "op": "action.add",
                "text": "Pay Acme Pay",
                "owners": [],
                "evidence": {"quote": QUOTE},
            }
        ],
    }
    assert not run_edited(monkeypatch, DEMO_A, CASE, stub_answer=todo).passed
    assert not run_edited(monkeypatch, DEMO_A, CASE, stub_answer={"summary": "x", "ops": []}).passed
