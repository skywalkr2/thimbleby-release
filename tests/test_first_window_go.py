"""Connecting a source is the go for its first window (H5-44): whatever the estimate, and whether or not a price is
known, the window starts at once and the worker sorts its mail; no Today line asks to start the reading."""

from __future__ import annotations

from tests.test_source_intake import NOW, item, mail, make, queue, read, requests_of


def test_a_first_window_above_the_amount_starts_without_a_press_and_makes_no_go_line(tmp_path):
    ws, cfg, store = make(tmp_path, [mail("new", 2), mail("mid", 10), item("page")], confirm=0.0)
    try:
        read((ws, cfg, store))
        taken = requests_of(store, intake="m")
        assert taken and {(r.data["state"], r.data["approval"]) for r in taken} == {("queued", "granted")}
        assert not [x for x in queue(ws, store, cfg, NOW) if x.kind == "intake_go"]
    finally:
        store.close()


def test_a_first_window_with_no_price_starts_by_itself_too(tmp_path):
    ws, cfg, store = make(tmp_path, [mail("new", 2), item("page")], price=None)
    try:
        read((ws, cfg, store))
        taken = requests_of(store, intake="m")
        assert taken and {r.data["state"] for r in taken} == {"queued"}
        assert not [x for x in queue(ws, store, cfg, NOW) if x.kind == "intake_go"]
    finally:
        store.close()
