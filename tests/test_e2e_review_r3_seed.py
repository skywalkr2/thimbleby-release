"""The seed of batch R3's closing browser tests (`tests/e2e_review_r3.py`) makes what the reviewer's states had: a note
of several sentences, items that share a word, entries of today past and to come, a person with a to-do already sent,
and the same promise three times over. Names and texts are made up; nothing here reads a real service."""

from __future__ import annotations

from engine.storage import Store
from engine.workspace import init_workspace
from tests.e2e_just_me import the_person
from tests.e2e_review_r3 import SWATCH_TEXTS, seed_review_r3


def test_the_seed_makes_the_long_and_the_many_the_closing_tests_read(tmp_path):
    ws = init_workspace(tmp_path / "ws", git=False, you=the_person())
    cfg = ws.config(env={})
    store = Store(ws.db_path)
    try:
        # The seed puts one to-do on a side's project: any two project ids will do for the test.
        with store.transaction() as tx:
            from engine.storage import WriteContext

            ctx = WriteContext(actor="pm", trust="trusted", op="test")
            sides = [tx.create("project", {"name": f"Side {n}"}, ctx).id for n in (1, 2)]
        seeded = seed_review_r3(ws, store, cfg, sides)
        view = store.read()
        assert len(view.get("note", seeded["note"]).data["text"].split(".")) >= 3
        assert view.get("action", seeded["sent_item"]).data["told"]
        assert not view.get("action", seeded["unsent_item"]).data.get("told")
        texts = [a.data["text"] for a in view.list("action")]
        assert all(text in texts for text in SWATCH_TEXTS)
        assert texts.count("Send the revised budget.") == 3
        assert view.get("source", seeded["source"]).data["trust"] == "untrusted"
    finally:
        store.close()
