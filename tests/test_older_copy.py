"""A source that serves an older copy is never news (S-0685): the newest copy seen is kept, an older one is never
compared, stored or filed, and the screen says so."""

from __future__ import annotations

from datetime import timedelta

import yaml

from engine.config import load_config
from engine.storage import Store
from engine.watch import refresh
from tests.test_watch import NOW, make

V3 = [{"key": "a", "title": "Plan", "text": "Version three\nLunch at noon."}]
V2 = [{"key": "a", "title": "Plan", "text": "Version two\nLunch at one."}]


def read_as(ws, store, items, made, at):
    store.close()
    current = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
    current["sources"] = [
        {
            "id": "s",
            "connector": "fake",
            "label": "Board",
            "first_run": "all",
            "settings": {"items": items, "generated_at": made.isoformat()},
        }
    ]
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump(current))
    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    return store, refresh(ws, store, cfg, "s", at), cfg


def test_v3_then_v2_then_v3_files_one_change_and_says_the_older_copy_was_not_compared(tmp_path):
    ws, cfg, store = make(tmp_path, [])
    try:
        t3, t2 = NOW - timedelta(hours=1), NOW - timedelta(hours=5)
        store, first, cfg = read_as(ws, store, V3, t3, NOW)
        store, older, cfg = read_as(ws, store, V2, t2, NOW + timedelta(hours=1))
        store, again, cfg = read_as(ws, store, V3, t3, NOW + timedelta(hours=2))
        assert len(first.new) == 1
        assert (older.new, older.changed, older.removed) == ([], [], [])
        assert older.note == "The source served an older copy; nothing compared."
        assert (again.new, again.changed, again.removed) == ([], [], [])
        assert len(store.read().list("request")) == 1
        runs = store.read().find("watch_run", {"source": "s"})
        assert [bool(r.data.get("older_copy")) for r in runs] == [False, True, False]
    finally:
        store.close()
