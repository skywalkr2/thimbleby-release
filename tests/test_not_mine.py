"""Not mine to track (design 6.22): the person's own change on one to-do or question from a watched source. It and the
source's other open items are dropped with the person's words in one change, the source becomes one only understood,
the read-back says how many went with it, and one Undo puts everything back. Nothing is dropped for another source or
for work already finished, and a refusal changes nothing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.config import load_config
from engine.storage import StoreError, WriteContext
from engine.watch import refresh
from tests.test_watch_burst import board, make

NOW = datetime(2030, 3, 4, 9, 0, tzinfo=UTC)
TOKEN = "not-mine-token"
_TEST = WriteContext(actor="pm", trust="trusted", op="test.not-mine")


@pytest.fixture
def env(tmp_path):
    other = {
        **board([{"key": "o1", "title": "Other page", "text": "Another page entirely."}]),
        "id": "t",
        "label": "Elsewhere",
    }
    ws, cfg, store = make(
        tmp_path,
        board(
            [{"key": "a", "title": "Plan A", "text": "A words."}, {"key": "b", "title": "Plan B", "text": "B words."}]
        ),
    )
    import yaml

    (ws.config_dir / "watch.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sources": [
                    board(
                        [
                            {"key": "a", "title": "Plan A", "text": "A words."},
                            {"key": "b", "title": "Plan B", "text": "B words."},
                        ]
                    ),
                    other,
                ],
            }
        )
    )
    cfg = load_config(ws.config_dir, env={})
    refresh(ws, store, cfg, "s", NOW)
    refresh(ws, store, cfg, "t", NOW)
    sources = {}
    for record in store.read().list("source"):
        watched = record.data.get("watched")
        if watched:
            sources.setdefault(watched["source"], []).append(record.id)
    person = cfg.workspace.user.person
    with store.transaction() as tx:
        made = {
            "mine": tx.create(
                "action", {"text": "Chase plan A", "owners": [{"person": person}], "source": sources["s"][0]}, _TEST
            ).id,
            "same": tx.create(
                "action", {"text": "Chase plan B", "owners": [{"person": person}], "source": sources["s"][1]}, _TEST
            ).id,
            "ask": tx.create(
                "question", {"title": "When is plan B?", "to": person, "source": sources["s"][1]}, _TEST
            ).id,
            "else": tx.create(
                "action",
                {"text": "Chase the other page", "owners": [{"person": person}], "source": sources["t"][0]},
                _TEST,
            ).id,
            "done": tx.create(
                "action",
                {
                    "text": "Finished from plan A",
                    "owners": [{"person": person}],
                    "source": sources["s"][0],
                    "status": "done",
                },
                _TEST,
            ).id,
            "own": tx.create("action", {"text": "Something I typed", "owners": [{"person": person}]}, _TEST).id,
        }
    yield ws, cfg, store, made
    store.close()


def status(store, kind, record_id):
    return store.read().get(kind, record_id).data["status"]


def stance(ws, source_id):
    return next(s for s in load_config(ws.config_dir, env={}).watch.sources if s.id == source_id).stance


def test_it_drops_the_item_and_the_sources_other_open_items_and_only_those_and_sets_the_source_to_understand(env):
    from engine import not_mine

    ws, cfg, store, made = env
    done = not_mine.apply(ws, store, cfg, "action", made["mine"], env={})
    assert (status(store, "action", made["mine"]), status(store, "action", made["same"])) == ("dropped", "dropped")
    assert status(store, "question", made["ask"]) == "dropped"
    assert status(store, "action", made["else"]) == "open"  # another source's item stays
    assert status(store, "action", made["done"]) == "done"  # finished work stays finished
    assert status(store, "action", made["own"]) == "open"  # the person's own item stays
    assert store.read().get("action", made["same"]).data["dropped_reason"] == "Not mine to track"
    assert (done.others, done.before, done.source) == (2, "follow", "s")
    assert done.read_back == "Dropped this and 2 more from Tracker. It is now only read to understand."
    assert stance(ws, "s") == "understand" and stance(ws, "t") == "follow"
    cs = store.read().get("changeset", done.changeset)
    assert cs.data["status"] == "applied" and len(cs.data["ops"]) == 3


def test_the_persons_own_words_are_the_reason_and_each_drop_records_its_signal(env):
    from engine import not_mine

    ws, cfg, store, made = env
    not_mine.apply(ws, store, cfg, "question", made["ask"], "Their team's plan, not mine.", env={})
    assert store.read().get("action", made["mine"]).data["dropped_reason"] == "Their team's plan, not mine."
    signals = [s for s in store.read().list("signal") if s.data["kind"] == "dropped"]
    refs = {r for s in signals for r in s.data["refs"]}
    assert {made["mine"], made["same"], made["ask"]} <= refs
    assert all(s.data["note"] == "Their team's plan, not mine." for s in signals)


def test_one_undo_puts_back_every_drop_and_the_sources_earlier_stance(env):
    from engine import not_mine

    ws, cfg, store, made = env
    done = not_mine.apply(ws, store, cfg, "action", made["mine"], env={})
    fresh = load_config(ws.config_dir, env={})
    assert not_mine.undo_it(ws, store, fresh, done.changeset, done.source, done.before, env={}) == 3
    assert [status(store, k, made[n]) for k, n in (("action", "mine"), ("action", "same"), ("question", "ask"))] == [
        "open"
    ] * 3
    assert stance(ws, "s") == "follow"


def test_a_source_already_understood_stays_so_and_undo_keeps_it(env):
    from engine import not_mine

    ws, cfg, store, made = env
    first = not_mine.apply(ws, store, cfg, "action", made["mine"], env={})
    not_mine.undo_it(ws, store, load_config(ws.config_dir, env={}), first.changeset, first.source, "understand", env={})
    assert stance(ws, "s") == "understand"
    # asked again of an item of a source that is now understood, the answer says it was already so
    again = not_mine.apply(ws, store, load_config(ws.config_dir, env={}), "action", made["mine"], env={})
    assert again.before == "understand" and stance(ws, "s") == "understand"


@pytest.mark.parametrize("which", ["own", "done", "missing"])
def test_an_item_that_is_not_open_or_not_from_a_source_is_refused_and_nothing_changes(env, which):
    from engine import not_mine

    ws, cfg, store, made = env
    item = "ACT-9999" if which == "missing" else made[which]
    with pytest.raises(StoreError):
        not_mine.apply(ws, store, cfg, "action", item, env={})
    assert status(store, "action", made["mine"]) == "open" and stance(ws, "s") == "follow"


def test_a_source_no_longer_listed_is_refused(env):
    from engine import not_mine

    ws, cfg, store, made = env
    (ws.config_dir / "watch.yaml").write_text("version: 1\nsources: []\n")
    with pytest.raises(StoreError, match="watches"):
        not_mine.apply(ws, store, load_config(ws.config_dir, env={}), "action", made["mine"], env={})
    assert status(store, "action", made["mine"]) == "open"


def test_the_routes_do_it_and_undo_it(env, tmp_path):
    ws, cfg, store, made = env
    app = create_app(ws, load_config(ws.config_dir, env={}), TOKEN, ui_dist=tmp_path / "none")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        done = client.post(f"/api/not-mine/action/{made['mine']}", json={})
        assert done.status_code == 200, done.text
        body = done.json()
        assert body["others"] == 2 and body["stance"] == "follow" and body["source_label"] == "Tracker"
        assert "2 more from Tracker" in body["read_back"]
        undone = client.post(
            "/api/not-mine/undo",
            json={"changeset": body["changeset"], "source": body["source"], "stance": body["stance"]},
        )
        assert undone.json() == {"restored": 3}
        assert client.post(f"/api/not-mine/action/{made['done']}", json={}).status_code == 409
        assert client.post("/api/not-mine/person/PER-1", json={}).status_code == 404


def test_a_row_from_a_watched_source_names_it_and_one_the_person_typed_does_not(env):
    from engine.origin import origins

    ws, cfg, store, made = env
    view = store.read()
    found = origins(view, "action", [made["mine"], made["else"], made["own"]])
    assert found[made["mine"]]["watch"] == "s" and found[made["else"]]["watch"] == "t"
    assert found[made["own"]] is None
    asked = origins(view, "question", [made["ask"]])
    assert asked[made["ask"]]["watch"] == "s"
