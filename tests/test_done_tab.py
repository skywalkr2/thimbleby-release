"""The Done tab's read (design 7.13, S-0428): the to-dos closed in the last days, newest first, each saying who
closed it and, for the assistant's own close, the words it quoted; reopening one that the assistant closed is a signal
it learns from. Names, ids and words come from the fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.open_items import done_actions
from engine.storage import WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B, fixture_records

TOKEN = "done-tab-token"
PEOPLE = fixture_records(DEMO_B, "person")
ME = PEOPLE[0]["id"]
OTHER = PEOPLE[1]["id"]
PROJECT = fixture_records(DEMO_B, "project")[0]
_PM = WriteContext(actor="pm", trust="trusted", op="test")
QUOTE = "I sent the signed sheet back on Tuesday, so that is finished."


@pytest.fixture
def api(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/", "storage.backups.automatic": False})
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, app.state.store, cfg


def make(store, text, **more) -> str:
    data = {"text": text, "owners": [{"person": ME}], "project": PROJECT["id"], **more}
    with store.transaction() as tx:
        return tx.create("action", data, _PM).id


def close(store, action_id, *, by="pm", quote=None, credit=None, days_ago=0.0, source=None, request=None) -> None:
    """Close an action as the person (a tick) or as the assistant (an `action.close` op that quoted words)."""
    assistant = by == "assistant"
    w = WriteContext(
        actor=by,
        trust="untrusted" if assistant else "trusted",
        op="action.close#0" if assistant else "review",
        changeset="CS-900" if assistant else None,
        request=request,
        evidence={"source": source, "quote": quote} if quote else None,
    )
    with store.transaction() as tx:
        cur = tx.get("action", action_id)
        tx.update(
            "action",
            action_id,
            {"status": "done", "done_by": credit or [ME], "reported_by": ME},
            w,
            read_version=cur.version,
        )
        if days_ago:
            when = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(timespec="seconds")
            tx.sql("UPDATE ledger SET at=? WHERE kind='action' AND record_id=?", (when, action_id))


def test_a_close_says_who_closed_it_and_the_assistant_gives_the_words_it_quoted(api):
    client, store, _ = api
    mine = make(store, "Pay the deposit")
    theirs = make(store, "Send the proof sheet")
    close(store, mine)
    close(store, theirs, by="assistant", quote=QUOTE)
    rows = {r["id"]: r for r in client.get("/api/open-items/done").json()["actions"]}
    assert rows[mine]["closed_by"] == "you" and rows[mine]["reason"] is None
    assert rows[theirs]["closed_by"] == "assistant" and rows[theirs]["reason"] == QUOTE


def test_the_list_is_newest_first_and_leaves_out_what_is_older_than_the_window(api):
    client, store, cfg = api
    old = make(store, "Renew the permit")
    recent = make(store, "Call the venue")
    latest = make(store, "Book the van")
    close(store, old, days_ago=cfg.ui.done_days + 2)
    close(store, recent, days_ago=3)
    close(store, latest)
    body = client.get("/api/open-items/done").json()
    ours = [r["id"] for r in body["actions"] if r["id"] in (old, recent, latest)]
    assert ours == [latest, recent]
    assert body["days"] == cfg.ui.done_days


def test_work_credited_to_somebody_else_names_them_and_an_open_or_reopened_to_do_is_not_listed(api):
    client, store, _ = api
    shared = make(store, "Return the form", owners=[{"person": OTHER}])
    open_one = make(store, "Still to do")
    close(store, shared, credit=[OTHER])
    row = next(r for r in client.get("/api/open-items/done").json()["actions"] if r["id"] == shared)
    assert row["done_by"] == [PEOPLE[1]["full_name"]] and row["closed_by"] == "you"
    assert open_one not in {r["id"] for r in client.get("/api/open-items/done").json()["actions"]}
    assert client.post(f"/api/actions/{shared}/status", json={"status": "open"}).status_code == 200
    assert shared not in {r["id"] for r in client.get("/api/open-items/done").json()["actions"]}


def test_reopening_what_the_assistant_closed_records_a_signal_and_the_persons_own_close_does_not(api):
    client, store, _ = api
    by_assistant = make(store, "Send the signed sheet")
    by_person = make(store, "Pay the deposit")
    close(store, by_assistant, by="assistant", quote=QUOTE)
    close(store, by_person)
    before = len(store.read().list("signal"))
    assert client.post(f"/api/actions/{by_person}/status", json={"status": "open"}).status_code == 200
    assert len(store.read().list("signal")) == before, "taking back your own tick is no correction of the assistant"
    assert client.post(f"/api/actions/{by_assistant}/status", json={"status": "open"}).status_code == 200
    signals = [s for s in store.read().list("signal") if s.data["kind"] == "pulled_back"]
    assert [s.data["refs"] for s in signals] == [[by_assistant]]
    assert store.read().get("action", by_assistant).data["status"] == "open"


def test_done_actions_reads_from_the_store_alone(api):
    _, store, cfg = api
    one = make(store, "Pay the deposit")
    close(store, one)
    assert [r.id for r in done_actions(store, cfg, datetime.now(UTC))][:1] == [one]


def make_input(store, kind, *, author=None, mail_kind=None, received="2026-10-13T09:30:00+00:00"):
    """An input the assistant read (a watched mail or calendar entry) and the request that read it: ids of both."""
    watched = {"source": "watch-1", "key": "k", "change": "new", "author": author}
    with store.transaction() as tx:
        src = tx.create(
            "source",
            {
                "received_at": received,
                "kind": kind,
                "title": "A message",
                "content_hash": "0" * 8,
                "trust": "untrusted",
                "watched": watched,
            },
            _PM,
        )
        req = tx.create(
            "request",
            {
                "task": "notes",
                "source": src.id,
                "origin": "input",
                "state": "done",
                "created_at": received,
                "mail_kind": mail_kind,
            },
            _PM,
        )
    return src.id, req.id


def done_row(client, action_id):
    return next(r for r in client.get("/api/open-items/done").json()["actions"] if r["id"] == action_id)


def test_a_close_from_a_reply_names_the_sender_and_the_day_the_reply_arrived(api):
    client, store, _ = api
    sender = PEOPLE[1]["full_name"]
    src, req = make_input(store, "watched:mailbox", author=f"{sender} <sender@example.com>")
    one = make(store, "Send the signed sheet")
    close(store, one, by="assistant", quote=QUOTE, source=src, request=req)
    row = done_row(client, one)
    assert (row["source_kind"], row["source_by"], row["source_day"]) == ("reply", sender, "2026-10-13")
    assert row["origin"]["source"] == src and row["reason"] == QUOTE


def test_a_close_from_a_bill_order_or_delivery_notice_names_the_kind_and_no_sender(api):
    client, store, _ = api
    src, req = make_input(store, "watched:mailbox", author="billing@example.com", mail_kind="bill")
    one = make(store, "Pay the printer")
    close(store, one, by="assistant", quote=QUOTE, source=src, request=req)
    row = done_row(client, one)
    assert (row["source_kind"], row["notice"], row["source_by"]) == ("notice", "bill", None)


def test_a_close_from_a_calendar_entry_or_a_note_says_which_and_one_with_no_input_says_nothing_more(api):
    client, store, _ = api
    src, req = make_input(store, "watched:calendar")
    meeting, noted, bare = make(store, "Book the room"), make(store, "Call the venue"), make(store, "Send the bill")
    close(store, meeting, by="assistant", quote=QUOTE, source=src, request=req)
    close(store, noted, by="assistant", quote=QUOTE, source="note")
    close(store, bare, by="assistant", quote=QUOTE)
    assert done_row(client, meeting)["source_kind"] == "calendar"
    assert done_row(client, noted)["source_kind"] == "note"
    row = done_row(client, bare)
    assert row["source_kind"] is None and row["source_day"] is None and row["origin"] is None


def test_a_close_by_the_person_carries_no_input_facts(api):
    client, store, _ = api
    one = make(store, "Pay the deposit")
    close(store, one)
    row = done_row(client, one)
    assert (row["source_kind"], row["source_by"], row["reason"]) == (None, None, None)
