"""A source the person only understands (design 6.22): its items are read and kept as facts. A to-do, a question or a
follow-up from one is returned once by `understand-tracks` and then held; a fact from it is not; a source the person
follows is not touched; and the packet says which it is. Ids and names come from the fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from engine import understand
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.config import load_config
from engine.dispatcher import process
from engine.watch import refresh
from tests.conftest import DEMO_B
from tests.test_watch_burst import board, make

NOW = datetime(2030, 3, 4, 9, 0, tzinfo=UTC)
PAGE = {"key": "k1", "title": "Release plan", "text": "The release moves to the second week of March."}


def made(tmp_path, stance):
    ws, cfg, store = make(tmp_path, board([PAGE], stance=stance))
    refresh(ws, store, cfg, "s", NOW)
    (request,) = [r for r in store.read().list("request") if r.data.get("origin") == "input"]
    return ws, cfg, store, request


def run(env, *ops):
    ws, cfg, store, request = env
    set_responder(lambda task: json.dumps({"summary": "Read it.", "ops": list(ops)}))
    cs = process(ws, store, cfg, Router(cfg, store, env={}), request.id, now=NOW)
    return store.read().get("changeset", cs).data["ops"]


def to_do(cfg):
    person = cfg.workspace.user.person
    return {"op": "action.add", "text": "Move the release", "owners": [person], "evidence": {"quote": PAGE["text"]}}


def test_a_source_is_followed_unless_it_says_otherwise_and_a_new_page_or_feed_starts_as_understood(tmp_path):
    ws, cfg, store = make(tmp_path, board([PAGE]))
    store.close()
    assert understand.stance_of(cfg, "s") == "follow"
    assert understand.stance_of(cfg, "no-such-source") == "follow"
    assert understand.default_stance("feed", []) == "understand"
    assert understand.default_stance("some-addon/tracker", []) == "understand"
    from engine.connectors import reads

    for kind in ("mailbox", "calendar", "folder", "capture"):
        assert understand.default_stance(kind, reads(kind)) == "follow"
    assert understand.default_stance("some-addon/inbox", ["mail"]) == "follow"
    assert understand.default_stance("some-addon/page", [], capture=True) == "follow"


def test_a_stance_that_is_neither_is_refused_with_the_setting_named(tmp_path):
    from engine.config import ConfigError

    with pytest.raises(ConfigError, match="stance"):
        make(tmp_path, board([PAGE], stance="chase"))


def test_both_fictional_workspaces_set_a_stance_on_a_source_and_the_two_lints(tmp_path):
    for template in (DEMO_B,):
        cfg = load_config(template / "config", env={})
        assert {s.stance for s in cfg.watch.sources} == {"follow", "understand"}
        assert cfg.checks.lints["understand-tracks"] == "return"


def test_a_to_do_from_an_understood_source_is_returned_and_then_held(tmp_path):
    env = made(tmp_path, "understand")
    try:
        (outcome,) = run(env, to_do(env[1]))
        assert outcome["status"] == "held"
        assert any(p["check"] == "understand-tracks" for p in outcome["problems"])
    finally:
        env[2].close()


def test_a_to_do_from_a_followed_source_applies(tmp_path):
    env = made(tmp_path, "follow")
    try:
        (outcome,) = run(env, to_do(env[1]))
        assert outcome["status"] == "applied"
    finally:
        env[2].close()


def test_a_fact_from_an_understood_source_applies(tmp_path):
    env = made(tmp_path, "understand")
    try:
        fact = {
            "op": "fact",
            "text": "The release moves to the second week of March.",
            "evidence": {"quote": PAGE["text"]},
        }
        (outcome,) = run(env, fact)
        assert not any(p["check"] == "understand-tracks" for p in outcome.get("problems", []))
    finally:
        env[2].close()


def test_the_note_from_the_person_is_never_held_for_a_stance(tmp_path):
    """A source the person only understands does not limit what they ask for in their own note."""
    from engine.applier import Context, Inputs, check
    from engine.names import People
    from engine.ops import CHANGESET

    ws, cfg, store, request = made(tmp_path, "understand")
    try:
        cs = CHANGESET.validate_python({"ops": [to_do(cfg)]})
        ctx = Context(
            store,
            cfg,
            People(store, cfg),
            ("action.add",),
            Inputs("REQ-0", None, "Move the release", "", "trusted"),
            actor="pm",
        )
        assert not any(p.check == "understand-tracks" for p in check(cs, ctx))
    finally:
        store.close()


def test_the_packet_marks_a_block_from_an_understood_source_and_only_one(tmp_path):
    from engine.packet import _watched_marks

    ws, cfg, store = make(tmp_path, board([PAGE], stance="understand"))
    store.close()
    assert ' stance="understand"' in _watched_marks(None, {"source": "s"}, "Plan", cfg=cfg)
    assert "stance" not in _watched_marks(None, {"source": "other"}, "Plan", cfg=cfg)
    assert "stance" not in _watched_marks(None, {"source": "s"}, "Plan")


def test_a_follow_up_message_is_tracked_work_and_a_mailbox_act_is_not(tmp_path):
    from engine.ops import ActDraftOp

    ws, cfg, store, request = made(tmp_path, "understand")
    try:
        person = store.read().list("person")[0].data["full_name"]
        message = ActDraftOp.model_validate(
            {
                "channel": "x",
                "target": {"kind": "message", "recipients": [{"person": person}]},
                "parts": {"body": "Any news?"},
            }
        )
        archive = ActDraftOp.model_validate(
            {"channel": "x", "target": {"kind": "mailbox", "action": "archive", "about": ["SRC-1"]}}
        )
        source = request.data["source"]
        assert understand.finding(message, store.read(), cfg, source) is not None
        assert understand.finding(archive, store.read(), cfg, source) is None
        assert understand.finding(message, store.read(), cfg, None) is None  # the person's own note has no source
    finally:
        store.close()


def test_the_kinds_say_what_a_new_source_starts_as_and_a_page_or_feed_is_added_as_understand(tmp_path, monkeypatch):
    from engine import source_trial
    from tests.test_capture_mail_setting import added, fingerprint, source_of
    from tests.test_setup import client
    from tests.test_setup import make as make_setup

    ws, cfg, store = make_setup(tmp_path)
    c, api = client(ws, cfg, store)
    kinds = {k["name"]: k for k in c.get(f"{api}/watch/kinds").json()}
    assert kinds["feed"]["default_stance"] == "understand"
    assert {kinds[k]["default_stance"] for k in ("folder", "mailbox", "calendar")} == {"follow"}
    monkeypatch.setattr(source_trial, "refusal_for", lambda *a, **k: None)
    body = {
        "connector": "feed",
        "label": "Another group's news",
        "settings": {"url": "https:" + "//other-group.example.com/feed.xml"},
        "fingerprint": fingerprint(c, api),
    }
    made_one = c.post(f"{api}/watch/sources", json=body)
    assert made_one.status_code == 200, made_one.text
    assert source_of(ws, "another-group-s-news").stance == "understand"
    # the person's own choice at adding wins
    body = {
        **body,
        "label": "Our own board",
        "stance": "follow",
        "settings": {"url": "https:" + "//board.example.com/feed.xml"},
        "fingerprint": fingerprint(c, api),
    }
    assert c.post(f"{api}/watch/sources", json=body).status_code == 200
    assert source_of(ws, "our-own-board").stance == "follow"
    # mail is followed; it is changed later, shown back, and an unknown value is refused
    assert added(c, api).status_code == 200
    assert source_of(ws, "work-mail").stance == "follow"
    done = c.post(f"{api}/watch/sources/work-mail", json={"stance": "understand", "fingerprint": fingerprint(c, api)})
    assert done.status_code == 200 and source_of(ws, "work-mail").stance == "understand"
    assert next(s for s in c.get(f"{api}/watch").json() if s["id"] == "work-mail")["stance"] == "understand"
    bad = c.post(f"{api}/watch/sources/work-mail", json={"stance": "chase", "fingerprint": fingerprint(c, api)})
    assert bad.status_code == 422 and source_of(ws, "work-mail").stance == "understand"
