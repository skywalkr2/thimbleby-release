"""Every write says what it changed (S-0424): a write's answer names the record kinds it wrote, so the screen reads
again only what shows them. Names and ids come from the fixtures."""

from __future__ import annotations

from tests.test_add_todo import TEXT, api  # noqa: F401  (the fixture)
from tests.test_corrections import pm_of


def test_a_write_names_the_kinds_it_wrote_and_a_read_names_none(api):  # noqa: F811
    client, _store, cfg = api
    made = client.post("/api/todos", json={"text": TEXT, "owners": [pm_of(cfg)]})
    assert made.status_code == 200
    assert "action" in made.headers["X-Changed-Kinds"].split(",")
    assert "X-Changed-Kinds" not in client.get("/api/open-items").headers


def test_a_write_names_where_the_ledger_stood_when_it_answered(api):  # noqa: F811
    client, store, cfg = api
    made = client.post("/api/todos", json={"text": TEXT, "owners": [pm_of(cfg)]})
    assert made.status_code == 200
    assert int(made.headers["X-Changed-Position"]) == store.read().changed_kinds(0)[0]
    assert "X-Changed-Position" not in client.get("/api/open-items").headers


def test_a_refused_write_names_nothing(api):  # noqa: F811
    client, _store, cfg = api
    refused = client.post("/api/todos", json={"text": "", "owners": [pm_of(cfg)]})
    assert refused.status_code >= 400
    assert "X-Changed-Kinds" not in refused.headers


def test_a_write_that_wrote_no_record_says_so_with_an_empty_header(api):  # noqa: F811
    client, _store, _cfg = api
    checked = client.post("/api/todos/day", json={"words": "Friday"})
    assert checked.status_code == 200
    assert checked.headers["X-Changed-Kinds"] == ""
