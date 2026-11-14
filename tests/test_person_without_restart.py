"""Once setup names the person, every screen knows them without a restart, even when a setting that waits for a restart
was saved in the same setup."""

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine.storage import WriteContext
from engine.workspace import init_workspace

TOKEN = "test-token-value"
_CTX = WriteContext(actor="pm", trust="trusted", op="test.person")


def _fresh(tmp_path):
    ws = init_workspace(tmp_path / "fresh", git=False)
    cfg = ws.config(env={}, flags={"server.base_path": "/", "storage.backups.automatic": False})
    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    return app, TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def _switch_on_an_add_on(client) -> None:
    """A setup step saves a setting that is not live: the add-ons switched on."""
    fingerprint = client.get("/api/settings").json()["fingerprint"]
    body = {"changes": {"workspace.plugins.enabled": ["example"]}, "reset": [], "fingerprint": fingerprint}
    saved = client.post("/api/settings", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["needs_restart"] is True


@pytest.mark.parametrize("add_on_first", [True, False])
def test_the_person_named_in_setup_is_known_at_once_though_another_setting_waits_for_a_restart(tmp_path, add_on_first):
    app, client = _fresh(tmp_path)
    with client:
        if add_on_first:
            _switch_on_an_add_on(client)
        me = client.post("/api/me", json={"full_name": "Someone Plain"}).json()["person"]
        if not add_on_first:
            _switch_on_an_add_on(client)
        store = app.state.worker.store
        with store.transaction() as tx:
            other = tx.create("person", {"full_name": "Pat Other"}, _CTX).id
            todo = tx.create("action", {"text": "Send the proofs", "owners": [{"person": other}]}, _CTX).id
        assert client.get("/api/runtime-config").json()["pm"] == me
        people = {p["id"]: p for p in client.get("/api/people").json()}
        assert people[me]["is_pm"] is True and people[other]["is_pm"] is False
        done = client.post(f"/api/actions/{todo}/status", json={"status": "done"})
        assert done.status_code == 200, done.text
        assert store.read().get("action", todo).data["reported_by"] == me
