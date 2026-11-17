"""Forgetting a person reaches everything that holds them (design 5.2, 12.4; S-0443 part 2, S-0271): their mail and the
files kept from it, the records that quote or mention them, the knowledge log and the private evaluation cases, with
the search test as the bar: nothing in the workspace names them afterward."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

import pytest

from engine import texts
from engine.applier import apply_as_person
from engine.files import add_file, blob_path
from engine.forget_reach import (
    FORGOTTEN_ADDRESS,
    FORGOTTEN_NUMBER,
    FORGOTTEN_QUOTE,
    Identifiers,
    plan_of,
    scrub,
)
from engine.people_forget import FORGOTTEN_NAME, forget_person
from engine.storage import Store, WriteContext
from engine.storage.export import export_data
from tests.test_handover import set_folder, write

NAME = "Marlowe Quillfeather"
FIRST = "Marly"
ALIAS = "The ropewalker"
EMAIL = "marlowe.quillfeather@example.com"
PHONE = "+1 555 010 4477"
PHONE_AS_WRITTEN = "(555) 010-4477"
OTHER_ADDRESS = "ropewalk-office@example.com"
IDENTIFIERS = [NAME, FIRST, ALIAS, EMAIL, "010 4477", "010-4477"]
QUOTE = f"{NAME} wrote: the tide chart is on shelf three"
MAIL = f"From: {NAME} <{EMAIL}>\nSubject: Tide chart\n\nIt is on shelf three. Call {FIRST} on {PHONE}.\n"
_NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
_W = WriteContext(actor="pm", trust="trusted", op="seed")
_AI = WriteContext(actor="assistant", trust="untrusted", op="seed#0")


@pytest.fixture
def env(workspace):
    cfg = workspace.config(env={})
    store = Store(workspace.db_path, cfg=cfg)
    yield workspace, cfg, store
    store.close()


def _text_file(ws, text):
    digest = hashlib.sha256(text.encode()).hexdigest()
    ws.sources_dir.mkdir(exist_ok=True)
    (ws.sources_dir / f"{digest}.txt").write_text(text, encoding="utf-8")
    return digest


def _seed(ws, cfg, store):
    """A person who sent mail, has a file kept from it, is quoted in a fact and a lesson, has a routing entry and a
    style note, appears in an evaluation case and the knowledge log, owns a to-do and attends an event. Returns the
    ids."""
    ids = {}
    with store.transaction() as tx:
        person = tx.create(
            "person",
            {
                "full_name": NAME,
                "first_name": FIRST,
                "aliases": [ALIAS],
                "how_to_reach": {"email": [EMAIL], "phone": [PHONE]},
            },
            _W,
        )
        ids["person"] = person.id
        digest = _text_file(ws, MAIL)
        snap = tx.create(
            "snapshot",
            {
                "source": "inbox",
                "key": "m1",
                "title": f"Tide chart from {NAME}",
                "content_hash": digest,
                "author": f"{NAME} <{EMAIL}>",
                "seen_at": _NOW.isoformat(),
                "message": {"sender": f"{NAME} <{EMAIL}>", "received": _NOW.isoformat(), "participants": [EMAIL]},
            },
            _W,
        )
        ids["snapshot"] = snap.id
        source = tx.create(
            "source",
            {
                "received_at": _NOW.isoformat(),
                "kind": "mail",
                "title": f"Tide chart from {NAME}",
                "content_hash": digest,
                "trust": "untrusted",
                "author": NAME,
                "watched": {"source": "inbox", "key": "m1", "change": "new"},
            },
            _W,
        )
        ids["source"] = source.id
        request = tx.create(
            "request",
            {
                "task": "extract",
                "origin": "input",
                "source": source.id,
                "state": "done",
                "note": f"Added a to-do for {NAME}",
                "waiting": f"Waiting for {FIRST}",
                "created_at": _NOW.isoformat(),
            },
            _W,
        )
        ids["request"] = request.id
        action = tx.create(
            "action",
            {
                "text": f"Send {NAME} the tide chart",
                "owners": [{"person": person.id}],
                "notes": f"Phone {PHONE_AS_WRITTEN} or write to {EMAIL.upper()}",
                "evidence": {"source": source.id, "quote": QUOTE},
            },
            _AI,
        )
        ids["action"] = action.id
        changeset = tx.create(
            "changeset",
            {
                "request": request.id,
                "summary": f"Added a to-do about {NAME}",
                "topic": f"Mail from {FIRST}",
                "status": "applied",
                "trust": "untrusted",
                "created_at": _NOW.isoformat(),
                "ops": [
                    {
                        "op": {"op": "action.add", "text": f"Send {NAME} the tide chart", "evidence": {"quote": QUOTE}},
                        "status": "applied",
                        "records": [{"kind": "action", "id": action.id}],
                    }
                ],
            },
            _W,
        )
        ids["changeset"] = changeset.id
        tx.create(
            "run",
            {
                "request": request.id,
                "task": "extract",
                "provider": "p",
                "model": "m",
                "tier": "t",
                "outcome": "ok",
                "started_at": _NOW.isoformat(),
                "knowledge": {"given": ["LESSON-1"], "searches": [{"words": "tide chart", "kinds": ["facts"]}]},
            },
            _W,
        )
        ids["run_other"] = tx.create(
            "run",
            {
                "task": "answer",
                "provider": "p",
                "model": "m",
                "tier": "t",
                "outcome": "ok",
                "started_at": _NOW.isoformat(),
                "knowledge": {"searches": [{"words": f"what does {FIRST} know", "kinds": ["facts"], "results": 1}]},
            },
            _W,
        ).id
        ids["fact"] = tx.create(
            "fact",
            {
                "text": f"{NAME} owns the ropewalk",
                "source": source.id,
                "evidence": {"source": source.id, "quote": QUOTE},
            },
            _AI,
        ).id
        ids["lesson"] = tx.create(
            "lesson",
            {
                "text": f"{FIRST} prefers short replies",
                "origin": "assistant",
                "learned_at": _NOW.isoformat(),
                "evidence": {"quote": f"{ALIAS} said keep it short", "source": source.id},
            },
            _AI,
        ).id
        ids["routing"] = tx.create(
            "routing_entry",
            {
                "text": f"{NAME} answers tide chart questions",
                "origin": "person",
                "learned_at": _NOW.isoformat(),
                "topic": "tide charts",
                "person": person.id,
            },
            _W,
        ).id
        ids["style"] = tx.create(
            "style_note",
            {
                "text": f"{FIRST} likes short notes",
                "origin": "person",
                "learned_at": _NOW.isoformat(),
                "audience": person.id,
                "observation": "Keep it short",
            },
            _W,
        ).id
        event = tx.create(
            "event",
            {
                "title": f"Tea with {FIRST}",
                "start": "2026-11-20T10:00",
                "attendees": [{"address": EMAIL, "name": NAME, "person": person.id}],
                "organizer": {"address": OTHER_ADDRESS, "name": "Ropewalk office"},
            },
            _W,
        )
        ids["event"] = event.id
        texts.new_version(
            store,
            tx,
            _W,
            "event",
            event.id,
            "prep",
            f"Ask {NAME} about the chart.\n\nBring a map.\n",
            source="edit",
            by="person",
            accept=True,
        )
        ids["question"] = tx.create(
            "question",
            {"to": person.id, "title": "Where is the tide chart?", "text": "Where?", "status": "answered"}
            | {"answer": f"Shelf three, says {FIRST}"},
            _W,
        ).id
        # A ledger evidence quote that names them, on a record whose current words are clean.
        ids["quoted"] = tx.create(
            "fact",
            {
                "text": "The tide chart is on shelf three",
                "evidence": {"source": "note", "quote": "it is on shelf three"},
            },
            WriteContext(
                actor="assistant",
                trust="untrusted",
                op="seed#1",
                evidence={"source": "note", "quote": f"{NAME} said so"},
            ),
        ).id
        # An entry whose evidence quote is taken from their mail, on a record that does not name them.
        ids["cited"] = tx.create(
            "note",
            {"text": "The chart is on shelf three"},
            WriteContext(
                actor="assistant",
                trust="untrusted",
                op="seed#2",
                evidence={"source": source.id, "quote": "It is on shelf three."},
            ),
        ).id
        gone = tx.create("note", {"text": f"Call {NAME} back"}, _W)
        tx.delete("note", gone.id, _W, read_version=gone.version)
        ids["note_removed"] = gone.id
        ids["note"] = tx.create("note", {"text": f"{FIRST}'s tea order is on the fridge"}, _W).id
    # A record whose current words are clean but whose earlier value named them.
    with store.transaction() as tx:
        todo = tx.create("note", {"text": f"Call {NAME}"}, _W)
        tx.update("note", todo.id, {"text": "Call the ropewalk office"}, _W, read_version=todo.version)
        ids["edited"] = todo.id
    kept = add_file(
        store,
        cfg,
        f"Chart notes from {NAME}".encode(),
        name="chart-notes.txt",
        media_type="text/plain",
        from_person=ids["person"],
        meta={"description": f"Sent by {FIRST}"},
    )
    ids["file"] = kept.id
    ids["blob"] = kept.data["sha256"]
    ids["bytes"] = blob_path(store, kept.data["sha256"])
    cases = ws.root / "evals"
    cases.mkdir(exist_ok=True)
    (cases / "private-tide-chart.yaml").write_text(
        f"id: private-tide-chart\nreceived: '2026-10-09'\ninput: |\n  From: {NAME} <{EMAIL}>\n  It is on shelf three.\n"
    )
    (cases / "starting-records.yaml").write_text(f"- kind: person\n  id: PER-9\n  fields:\n    full_name: {NAME}\n")
    return ids


def _everything_stored(ws) -> str:
    conn = sqlite3.connect(ws.db_path)
    try:
        rows = conn.execute("SELECT * FROM ledger").fetchall() + conn.execute("SELECT * FROM records").fetchall()
    finally:
        conn.close()
    return json.dumps(rows, ensure_ascii=False).replace("\\\\", "\\")


def _folders(ws) -> str:
    """The texts of the export, the saved texts, the long texts, the stored bytes and the evaluation cases."""
    found = []
    for folder in ("data", "sources", "texts", "files", "evals"):
        base = ws.root / folder
        found += [p.read_bytes().decode("utf-8", "replace") for p in sorted(base.rglob("*")) if p.is_file()]
    return "\n".join(found)


def _named(text: str) -> list[str]:
    low = text.lower()
    return [value for value in IDENTIFIERS if value.lower() in low]


def _forget(ws, cfg, store, ids):
    version = store.read().get("person", ids["person"]).version
    return forget_person(ws, store, cfg, ids["person"], read_version=version, summary="Forgot a person")


def test_nothing_in_the_workspace_names_the_person_after_the_forget(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    export_data(store, ws.data_dir)
    assert _named(_everything_stored(ws)) and _named(_folders(ws)), "the seed holds them everywhere before"
    before = store.read()
    assert any(NAME in json.dumps(r["evidence"]) for r in before.ledger(kind="fact", record_id=ids["quoted"]))
    assert any(NAME in json.dumps(r["before"]) for r in before.ledger(kind="note", record_id=ids["edited"]))
    assert ids["bytes"].is_file() and (ws.sources_dir / f"{hashlib.sha256(MAIL.encode()).hexdigest()}.txt").is_file()

    _forget(ws, cfg, store, ids)

    assert _named(_everything_stored(ws)) == []
    assert _named(_folders(ws)) == []
    assert not any(p.is_file() for p in ws.sources_dir.rglob("*") if "shelf three" in p.read_text("utf-8", "replace"))
    assert not ids["bytes"].exists(), "the bytes of the file kept from their mail are gone"
    assert not (ws.root / "evals" / "private-tide-chart.yaml").exists()
    # The two cases a scan of current values misses: an evidence quote in the ledger, and a record whose current words
    # are clean but whose earlier value named them.
    assert store.read().get("note", ids["edited"]).data["text"] == "Call the ropewalk office"
    quoted = [r["evidence"] for r in store.read().ledger(kind="fact", record_id=ids["quoted"]) if r["evidence"]]
    assert quoted and all(e["quote"] == FORGOTTEN_QUOTE for e in quoted)
    # What is theirs to keep stays, with the marker where they were.
    view = store.read()
    assert view.get("action", ids["action"]).data["text"] == f"Send {FORGOTTEN_NAME} the tide chart"
    assert view.get("person", ids["person"]).data["full_name"] == FORGOTTEN_NAME
    assert view.get("event", ids["event"]).data["attendees"][0]["person"] == ids["person"]
    assert view.get("event", ids["event"]).data["organizer"]["address"] == OTHER_ADDRESS


def test_r1_their_mail_is_purged_as_a_set_aside_deletion_is(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    digest = hashlib.sha256(MAIL.encode()).hexdigest()
    plan = plan_of(store.read(), ids["person"], ws.root)
    assert plan.snapshots == [ids["snapshot"]] and plan.sources == {ids["source"]}
    assert plan.requests == {ids["request"]} and plan.files == [ids["file"]]

    _forget(ws, cfg, store, ids)

    view = store.read()
    snap = view.get("snapshot", ids["snapshot"]).data
    assert snap["deleted"] and snap["title"] == "" and snap["content_hash"] == "" and snap["author"] is None
    assert snap["message"]["sender"] is None and snap["key"] == "m1", "a marker stays so the next read hands nothing in"
    src = view.get("source", ids["source"]).data
    assert src["content_hash"] == "" and src["author"] is None and src["watched"] is None
    request = view.get("request", ids["request"]).data
    assert request["note"] is None and request["waiting"] == "Forgotten with the person"
    assert not (ws.sources_dir / f"{digest}.txt").exists()
    kept = view.get("file", ids["file"], include_deleted=True)
    assert kept.deleted and kept.data["sha256"] == "" and kept.data["name"] == ""
    assert view.get("question", ids["question"]).data["answer"] == "Answer forgotten"
    for entry in view.ledger(kind="snapshot", record_id=ids["snapshot"]):
        assert (
            entry["before"] in (None, "null")
            and entry["after"] in (None, "null")
            or entry["field"]
            not in (
                "title",
                "author",
                "message",
            )
        )


def test_r1_mail_from_someone_else_keeps_its_text_even_when_it_mentions_them(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    text = f"From: Someone Else <else@example.com>\n\nPlease ask {NAME} about the chart.\n"
    digest = _text_file(ws, text)
    with store.transaction() as tx:
        other = tx.create(
            "source",
            {
                "received_at": _NOW.isoformat(),
                "kind": "mail",
                "title": "Chart",
                "content_hash": digest,
                "trust": "untrusted",
                "author": "Someone Else <else@example.com>",
            },
            _W,
        )
    _forget(ws, cfg, store, ids)
    assert store.read().get("source", other.id).data["content_hash"] == digest
    assert (ws.sources_dir / f"{digest}.txt").exists(), "their name in another sender's mail is not their mail"


def test_r2_records_that_exist_only_for_them_are_removed_with_their_earlier_values_given_up(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    _forget(ws, cfg, store, ids)
    view = store.read()
    for key in ("routing", "style"):
        assert view.get(*({"routing": "routing_entry", "style": "style_note"}[key], ids[key])) is None
    removed = view.get("routing_entry", ids["routing"], include_deleted=True)
    assert removed.deleted and removed.data["text"] == "Forgotten with the person"
    assert _named(_everything_stored(ws)) == []


def test_r3_their_words_in_other_records_become_markers_and_references_by_id_stay(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    _forget(ws, cfg, store, ids)
    view = store.read()
    action = view.get("action", ids["action"]).data
    assert action["notes"] == f"Phone {FORGOTTEN_NUMBER} or write to {FORGOTTEN_ADDRESS}"
    assert action["evidence"] == {"source": ids["source"], "quote": FORGOTTEN_QUOTE}
    fact = view.get("fact", ids["fact"]).data
    assert fact["text"] == f"{FORGOTTEN_NAME} owns the ropewalk" and fact["evidence"]["quote"] == FORGOTTEN_QUOTE
    lesson = view.get("lesson", ids["lesson"]).data
    assert lesson["text"] == f"{FORGOTTEN_NAME} prefers short replies"
    assert lesson["evidence"]["quote"] == FORGOTTEN_QUOTE and lesson["evidence"]["source"] == ids["source"]
    changeset = view.get("changeset", ids["changeset"]).data
    assert FORGOTTEN_QUOTE in json.dumps(changeset["ops"]) and NAME not in json.dumps(changeset)
    assert view.get("note", ids["note"]).data["text"] == f"{FORGOTTEN_NAME}'s tea order is on the fridge"
    removed = view.get("note", ids["note_removed"], include_deleted=True)
    assert removed.deleted and removed.data["text"] == f"Call {FORGOTTEN_NAME} back"
    assert view.get("question", ids["question"]).data["to"] == ids["person"]


def test_r3_a_quote_from_someone_elses_mail_is_kept(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    with store.transaction() as tx:
        other = tx.create(
            "source",
            {
                "received_at": _NOW.isoformat(),
                "kind": "mail",
                "title": "Else",
                "content_hash": "",
                "trust": "untrusted",
            },
            _W,
        )
        kept = tx.create(
            "fact",
            {"text": "The chart is on shelf three", "evidence": {"source": other.id, "quote": "on shelf three"}},
            _W,
        )
    _forget(ws, cfg, store, ids)
    assert store.read().get("fact", kept.id).data["evidence"]["quote"] == "on shelf three"


def test_r3_the_long_text_of_a_record_is_rewritten_with_its_hash_and_the_old_file_goes(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    view = store.read()
    old = view.get("event", ids["event"]).data["prep"]
    old_path = texts.text_path(store, old)
    assert old_path.is_file()
    _forget(ws, cfg, store, ids)
    view = store.read()
    new = view.get("event", ids["event"]).data["prep"]
    assert new != old and not old_path.exists()
    assert texts.read_text(store, new) == f"Ask {FORGOTTEN_NAME} about the chart.\n\nBring a map.\n"
    version = texts.current(view, "event", ids["event"], "prep")
    assert version.data["sha256"] == new and version.data["words"] == texts.words(texts.read_text(store, new))
    assert [s["kind"] for s in version.data["authorship"]] == ["person"]


def test_r4_the_knowledge_log_of_their_mail_goes_and_searches_naming_them_are_scrubbed(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    _forget(ws, cfg, store, ids)
    view = store.read()
    from_their_mail = [r for r in view.list("run") if r.data.get("request") == ids["request"]]
    assert from_their_mail and all(r.data["knowledge"] is None for r in from_their_mail)
    other = view.get("run", ids["run_other"]).data["knowledge"]
    assert other["searches"][0]["words"] == f"what does {FORGOTTEN_NAME} know"


def test_r4_private_evaluation_cases_are_removed_and_shared_starting_files_are_cleaned(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    other_case = ws.root / "evals" / "unrelated.yaml"
    other_case.write_text("id: unrelated\nreceived: '2026-10-09'\ninput: Nothing about anyone\n")
    _forget(ws, cfg, store, ids)
    assert not (ws.root / "evals" / "private-tide-chart.yaml").exists()
    assert other_case.exists()
    assert (ws.root / "evals" / "starting-records.yaml").read_text() == (
        f"- kind: person\n  id: PER-9\n  fields:\n    full_name: {FORGOTTEN_NAME}\n"
    )


def test_a_file_that_something_else_refers_to_refuses_the_whole_forget(env, monkeypatch):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    monkeypatch.setattr(type(store.plugins), "_referrers", lambda self, view: lambda kind, rid: [("x", "X-1")])
    with pytest.raises(Exception, match="still referred to"):
        _forget(ws, cfg, store, ids)
    assert store.read().get("person", ids["person"]).data["full_name"] == NAME, "a refused forget changes nothing"
    assert _named(_everything_stored(ws))


def test_undo_of_an_earlier_change_to_an_r3_record_keeps_the_marker(env):
    from engine.applier import undo as undo_changeset

    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    version = store.read().get("note", ids["note"]).version
    cs = apply_as_person(
        store,
        cfg,
        [
            {
                "op": "record.edit",
                "record": {"kind": "note", "id": ids["note"]},
                "fields": {"text": f"{FIRST}'s tea order is on the shelf"},
                "read_version": version,
            }
        ],
        "Edited a note",
    )
    _forget(ws, cfg, store, ids)
    report = undo_changeset(store, cs)
    assert report.restored == [] and "forgotten, not restored" in report.skipped[0]["reason"]
    assert store.read().get("note", ids["note"]).data["text"] == f"{FORGOTTEN_NAME}'s tea order is on the shelf"
    assert _named(_everything_stored(ws)) == []


def test_undo_with_no_forget_in_the_history_restores_as_before(env):
    from engine.applier import undo as undo_changeset

    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    before = store.read().get("note", ids["note"])
    cs = apply_as_person(
        store,
        cfg,
        [
            {
                "op": "record.edit",
                "record": {"kind": "note", "id": ids["note"]},
                "fields": {"text": "The tea order is on the shelf"},
                "read_version": before.version,
            }
        ],
        "Edited a note",
    )
    report = undo_changeset(store, cs)
    assert report.skipped == [] and report.restored
    assert store.read().get("note", ids["note"]).data["text"] == before.data["text"]


def test_the_forget_lists_what_it_gave_up_with_ids_and_field_names_only(env):
    from engine.forget_reach import REACH_FIELD

    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    _forget(ws, cfg, store, ids)
    rows = [r for r in store.read().ledger(kind="person", record_id=ids["person"]) if r["field"] == REACH_FIELD]
    assert len(rows) == 1 and rows[0]["op"].startswith("person.forget")
    listed = {tuple(item) for item in rows[0]["after"]}
    assert ("note", ids["edited"], "text") in listed, "a record whose current words are clean is listed"
    assert ("note", ids["note"], "text") in listed and ("routing_entry", ids["routing"], "text") in listed
    assert ("source", ids["source"], "quoted from") in listed
    assert ("fact", ids["quoted"], "evidence") in listed or any(
        k == "fact" and r == ids["quoted"] for k, r, _ in listed
    )
    assert _named(json.dumps(rows[0]["after"])) == []
    assert all(len(item) == 3 and all(isinstance(part, str) for part in item) for item in rows[0]["after"])


def test_a_ledger_quote_taken_from_their_mail_is_blanked_wherever_it_is(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    _forget(ws, cfg, store, ids)
    rows = store.read().ledger(kind="note", record_id=ids["cited"])
    assert rows and all(
        r["evidence"]["quote"] == FORGOTTEN_QUOTE and r["evidence"]["source"] == ids["source"] for r in rows
    )
    assert store.read().get("note", ids["cited"]).data["text"] == "The chart is on shelf three", "its words stay"


def test_the_earlier_values_of_a_record_with_clean_words_are_given_up(env):
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    _forget(ws, cfg, store, ids)
    rows = store.read().ledger(kind="note", record_id=ids["edited"])
    text_rows = [r for r in rows if r["field"] == "text"]
    assert text_rows and all(r["before"] in (None, "null") or "ropewalk" in json.dumps(r["before"]) for r in text_rows)
    assert not any(NAME in json.dumps(r) for r in rows)


def test_undo_of_an_earlier_change_to_a_record_listed_only_by_its_history_is_refused(env):
    from engine.applier import undo as undo_changeset

    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    version = store.read().get("note", ids["edited"]).version
    cs = apply_as_person(
        store,
        cfg,
        [
            {
                "op": "record.edit",
                "record": {"kind": "note", "id": ids["edited"]},
                "fields": {"text": "Call the ropewalk office today"},
                "read_version": version,
            }
        ],
        "Edited a note",
    )
    _forget(ws, cfg, store, ids)
    report = undo_changeset(store, cs)
    assert report.restored == [] and "forgotten, not restored" in report.skipped[0]["reason"]
    assert store.read().get("note", ids["edited"]).data["text"] == "Call the ropewalk office today"


def test_an_add_ons_short_text_fields_are_reached_and_its_long_texts_are_not(tmp_path):
    from tests.test_file_kind_levels import workspace

    ws, cfg, store = workspace(tmp_path)
    try:
        with store.transaction() as tx:
            person = tx.create("person", {"full_name": NAME, "first_name": FIRST}, _W)
            chapter = tx.create("p14/chapter", {"title": f"A letter to {NAME}"}, _W)
        _forget(ws, cfg, store, {"person": person.id})
        assert store.read().get("p14/chapter", chapter.id).data["title"] == f"A letter to {FORGOTTEN_NAME}"
        rows = store.read().ledger(kind="p14/chapter", record_id=chapter.id)
        assert not any(NAME in json.dumps(r) for r in rows)
    finally:
        store.close()


def test_a_forget_on_one_computer_reaches_r1_r2_and_r3_records_on_the_other_with_no_divergence(tmp_path):
    from engine.handover import _folder_ledger, _local_ledger, compare, open_workspace, release
    from engine.workspace import init_workspace
    from tests.conftest import DEMO_B

    folder = tmp_path / "synced"
    folder.mkdir()
    a = init_workspace(tmp_path / "a", template=DEMO_B, git=False)
    b = init_workspace(tmp_path / "b", git=False, personal=False)
    cfg_a, cfg_b = set_folder(a, folder), set_folder(b, folder)
    open_workspace(a, cfg_a)
    store = Store(a.db_path, cfg=cfg_a)
    ids = _seed(a, cfg_a, store)
    store.close()
    write(a, cfg_a)
    release(a, cfg_a)
    assert open_workspace(b, cfg_b).action == "loaded"
    assert _named(_everything_stored(b)), "the second computer holds them before the forget"
    texts_b = list((b.root / "texts").rglob("*.txt")) + list(b.sources_dir.rglob("*.txt"))
    assert texts_b, "the second computer holds their texts too"
    release(b, cfg_b)
    (b.root / "evals").mkdir(exist_ok=True)
    (b.root / "evals" / "private-here.yaml").write_text(
        f"id: private-here\nreceived: '2026-10-09'\ninput: Note from {NAME}\n"
    )
    (b.root / "evals" / "unrelated.yaml").write_text("id: unrelated\nreceived: '2026-10-09'\ninput: Nothing\n")

    assert open_workspace(a, cfg_a).action in ("same", "newer_here")
    store = Store(a.db_path, cfg=cfg_a)
    try:
        _forget(a, cfg_a, store, ids)
    finally:
        store.close()
    write(a, cfg_a)
    release(a, cfg_a)

    opened = open_workspace(b, cfg_b)
    assert opened.action == "loaded"
    assert _named(repr(_local_ledger(b))) == [] and _named(_everything_stored(b)) == []
    assert not (b.root / "evals" / "private-here.yaml").exists(), "the loading computer removes its own cases (R4)"
    assert (b.root / "evals" / "unrelated.yaml").exists()
    assert compare(_local_ledger(b), _folder_ledger(folder)) == "same"
    assert compare(_local_ledger(b), _local_ledger(a)) == "same"
    store = Store(b.db_path, cfg=cfg_b)
    try:
        view = store.read()
        assert view.get("note", ids["note"]).data["text"] == f"{FORGOTTEN_NAME}'s tea order is on the fridge"  # R3
        assert view.get("routing_entry", ids["routing"]) is None  # R2
        assert view.get("snapshot", ids["snapshot"]).data["deleted"]  # R1
    finally:
        store.close()
    assert not [p for p in b.sources_dir.rglob("*.txt") if NAME in p.read_text("utf-8")]
    assert not [p for p in (b.root / "texts").rglob("*.txt") if NAME in p.read_text("utf-8")]


def test_identifiers_replace_each_form_a_person_is_named_in():
    ids = Identifiers(
        {
            "full_name": NAME,
            "first_name": FIRST,
            "aliases": [ALIAS],
            "how_to_reach": {"email": [EMAIL], "phone": [PHONE]},
        }
    )
    said = ids.say(f"{NAME.upper()} <{EMAIL.upper()}> or {FIRST}, the ropewalker, on 555-010-4477 or (555) 010 4477.")
    assert NAME.upper() not in said and EMAIL.upper() not in said and "4477" not in said and FIRST not in said
    assert FORGOTTEN_NAME in said and FORGOTTEN_ADDRESS in said
    assert ids.say("Marlyn and marlowe quillfeathers are other people") == (
        "Marlyn and marlowe quillfeathers are other people"
    )
    will = Identifiers({"full_name": "Will Hart", "first_name": "Will"})
    assert will.say("I will ask Will, will WILL Hart agree? Ask will hart.") == (
        f"I will ask {FORGOTTEN_NAME}, will {FORGOTTEN_NAME} agree? Ask {FORGOTTEN_NAME}."
    )
    assert scrub({"quote": "x", "source": "SRC-1"}, ids, sources=frozenset({"SRC-1"})) == {
        "quote": FORGOTTEN_QUOTE,
        "source": "SRC-1",
    }
    assert scrub({"quote": "x", "source": "SRC-2"}, ids, sources=frozenset({"SRC-1"}))["quote"] == "x"


def test_a_kept_header_that_names_them_is_erased_with_their_mail_and_one_that_does_not_stays(env):
    """A year of headers kept at a first sign-in (`mail_header`) is reached like a snapshot: one from them or sent to
    them goes whole, with its earlier values given up; one between other people stays."""
    ws, cfg, store = env
    ids = _seed(ws, cfg, store)
    with store.transaction() as tx:
        base = {"source": "inbox", "title": "", "seen_at": _NOW.isoformat()}
        mine = tx.create(
            "mail_header",
            {**base, "key": "h1", "title": f"Note for {NAME}", "message": {"sender": f"{NAME} <{EMAIL}>"}},
            _W,
        )
        to_me = tx.create(
            "mail_header",
            {**base, "key": "h2", "message": {"sender": f"Other <{OTHER_ADDRESS}>", "participants": [EMAIL]}},
            _W,
        )
        other = tx.create(
            "mail_header",
            {**base, "key": "h3", "message": {"sender": f"Other <{OTHER_ADDRESS}>", "participants": [OTHER_ADDRESS]}},
            _W,
        )
    assert {mine.id, to_me.id} <= set(plan_of(store.read(), ids["person"], ws.root).headers)
    assert other.id not in plan_of(store.read(), ids["person"], ws.root).headers
    _forget(ws, cfg, store, ids)
    view = store.read()
    assert view.get("mail_header", mine.id) is None and view.get("mail_header", to_me.id) is None
    assert view.get("mail_header", other.id) is not None
    assert not any(NAME in json.dumps(r) or EMAIL in json.dumps(r) for r in view.ledger(kind="mail_header"))
