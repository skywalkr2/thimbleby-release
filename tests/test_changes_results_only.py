"""What changed lists results and what needs the person (design 7.3): work in progress and the assistant's own jobs are
not rows, and the menu count follows the same rule."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.storage import WriteContext
from engine.workspace import init_workspace
from tests.e2e_just_me import the_person
from tests.test_knowledge_records import source

TOKEN = "results-only-token"
_CTX = WriteContext(actor="engine", trust="trusted", op="test.results_only")
NOW = "2026-11-02T12:00:00Z"


@pytest.fixture
def served(tmp_path):
    ws = init_workspace(tmp_path / "ws", git=False, you=the_person())
    cfg = ws.config(env={}, flags={"storage.backups.automatic": False})
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, app.state.store


def _request(store, **fields) -> str:
    with store.transaction() as tx:
        return tx.create("request", {"created_at": NOW, "state": "done", **fields}, _CTX).id


def _ids(client) -> set[str]:
    return {row["id"] for row in client.get("/api/changes").json()}


def test_queued_and_running_inputs_are_not_rows_but_a_stopped_one_is(served):
    client, store = served
    queued = _request(store, task="extract", origin="input", state="queued", source=source(store))
    running = _request(store, task="extract", origin="input", state="running", source=source(store))
    stopped = _request(store, task="extract", origin="input", state="needs_you", source=source(store))
    shown = _ids(client)
    assert queued not in shown and running not in shown
    assert stopped in shown


def test_the_assistants_own_jobs_are_not_rows_even_when_finished(served):
    client, store = served
    learning = _request(store, task="learn-correction", origin="schedule", state="queued")
    learned = _request(store, task="learn-correction", origin="schedule", state="done")
    reading = _request(store, task="area-read", origin="schedule", state="done")
    stuck = _request(store, task="learn-correction", origin="schedule", state="needs_you")
    shown = _ids(client)
    assert not ({learning, learned, reading} & shown)
    assert stuck in shown, "an own job that needs the person stays"


def test_the_status_says_whether_any_kind_of_record_has_stages(served):
    client, store = served
    assert client.get("/api/status").json()["has_stages"] is False, "the core defines no staged record types"
    from engine.config.schema import TypeStages

    store.plugins.stages.types["demo/kind"] = TypeStages.model_validate(
        [{"id": "one", "label": "One"}, {"id": "two", "label": "Two"}]
    )
    assert client.get("/api/status").json()["has_stages"] is True
