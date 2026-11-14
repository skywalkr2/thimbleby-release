"""The screens' side of a calendar that holds who is away (design 5.1): the source says what it holds, its row counts
the names that matched nobody, a question about which person is answered with a person and writes the days, and only a
calendar can hold who is away."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.config import load_config
from tests.test_absence import FULL, OTHER, PEOPLE, calendar, env, name, vevent  # noqa: F401

TOKEN = "absence-api-token"


@pytest.fixture
def client(env, tmp_path):  # noqa: F811
    ws, cfg, store, put = env
    app = create_app(ws, load_config(ws.config_dir, env={}), TOKEN, ui_dist=tmp_path / "none")
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, put, store


def source_of(client):
    return next(s for s in client.get("/api/watch").json() if s["id"] == "away")


def test_the_row_says_what_the_calendar_holds_and_counts_the_names_nobody_has(client):
    http, put, store = client
    assert source_of(http)["holds"] == "absence" and source_of(http)["unmatched_names"] == []
    put(calendar(vevent("a", "Quentin Zabriskie - vacation")))
    assert source_of(http)["unmatched_names"] == ["Quentin Zabriskie"]


def test_adding_the_name_as_a_person_and_reading_again_writes_their_days(client):
    http, put, store = client
    # The route reads at the real time, so the entry is a few days from today.
    first = datetime.now(UTC).date() + timedelta(days=5)
    feed = calendar(
        vevent(
            "a",
            "Quentin Zabriskie - vacation",
            start=first.strftime("%Y%m%d"),
            end=(first + timedelta(days=2)).strftime("%Y%m%d"),
        )
    )
    put(feed, datetime.now(UTC))
    made = http.post("/api/people", json={"full_name": "Quentin Zabriskie"})
    assert made.status_code == 200, made.text
    http.post("/api/watch/away/read")
    away = store.read().get("person", made.json()["id"]).data["away"]
    assert [str(p["start"]) for p in away] == [first.isoformat()]
    assert source_of(http)["unmatched_names"] == []


def test_a_question_about_which_person_takes_a_person_as_its_answer_and_writes_the_days(client):
    http, put, store = client
    put(calendar(vevent("a", f"{name(FULL)} and {name(OTHER)} vacation")))
    (question,) = [q for q in store.read().list("question") if (q.data.get("resolves") or {}).get("kind") == "away"]
    assert http.post(f"/api/questions/{question.id}/answer", json={"text": "either"}).status_code == 422
    done = http.post(f"/api/questions/{question.id}/answer", json={"person": OTHER})
    assert done.status_code == 200, done.text
    assert len(store.read().get("person", OTHER).data["away"]) == 1
    assert not store.read().get("person", FULL).data.get("away")


def test_only_a_calendar_can_hold_who_is_away(client):
    http, put, store = client
    fingerprint = http.get("/api/settings").json()["fingerprint"]
    refused = http.post(
        "/api/watch/sources",
        json={"connector": "folder", "holds": "absence", "settings": {"path": "."}, "fingerprint": fingerprint},
    )
    assert refused.status_code == 400 and "calendar" in refused.json()["detail"]
    assert PEOPLE  # the fictional people are the fixtures' own
