"""The routes for what a provider charged (S-0654): the side-by-side per day, Not now for the gap, listing the
organization's keys to pick from, and adding the billing key (one small read first; a refused key saves nothing; the key
is kept on this computer and never returned). A stubbed transport stands in for the service."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from api.app import create_app
from engine.ai import cost_report
from engine.ai.adapters import ADAPTERS
from engine.config import load_config
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

FIXTURES = Path(__file__).parent / "fixtures" / "ai"
NATIVE = yaml.safe_load((FIXTURES / "catalog-claims.yaml").read_text("utf-8"))["native_adapter"]
REPORT = json.loads((FIXTURES / "cost-report.json").read_text("utf-8"))
MODULE = importlib.import_module(ADAPTERS[NATIVE["adapter"]].__module__)
RUN = WriteContext("engine", "trusted", "test")
ACCOUNT = "acct"
# The app's own clock in these tests is the real one, so every date is relative to it.
TODAY = datetime.now(UTC).date()
SETTLED = TODAY - timedelta(days=10)


class Service:
    """Plays the service back: a key list and a report, or a refusal."""

    def __init__(self, refuse=False):
        self.refuse, self.seen = refuse, []

    def handler(self, request):
        self.seen.append(request)
        if self.refuse:
            return httpx.Response(401, json={"error": {"type": "authentication_error"}})
        if request.url.path.endswith("api_keys"):
            return httpx.Response(200, json=REPORT["keys"])
        return httpx.Response(
            200,
            json={
                "data": [{"starting_at": f"{SETTLED}T00:00:00Z", "cost": {"amount": "500", "currency": "USD"}}],
                "has_more": False,
            },
        )

    def factory(self, name, settings, secret, billing=None):
        return ADAPTERS[name](settings, secret, billing_secret=billing, transport=httpx.MockTransport(self.handler))


@pytest.fixture
def started(tmp_path, monkeypatch):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    path = ws.config_dir / "ai.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["providers"][ACCOUNT] = {
        "adapter": NATIVE["adapter"],
        "base_url": f"https://{MODULE.REPORT_HOST}",
        "models": {"default": "m"},
    }
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    cfg = ws.config(env={})
    Store(ws.db_path, cfg=cfg).close()
    client = TestClient(create_app(ws, cfg, "t", start_worker=False))
    client.headers["Authorization"] = "Bearer t"
    service = Service()
    monkeypatch.setattr("engine.ai.adapters.make_adapter", service.factory)
    monkeypatch.setattr("engine.ai.cost_report.make_adapter", service.factory)
    return ws, client, service


def api(client, ws):
    return load_config(ws.config_dir, env={}).server.base_path.rstrip("/") + "/api"


def fingerprint(client, ws):
    return client.get(f"{api(client, ws)}/settings").json()["fingerprint"]


def account(client, ws):
    return next(a for a in client.get(f"{api(client, ws)}/ai/accounts").json() if a["name"] == ACCOUNT)


def add_key(client, ws, **body):
    return client.post(
        f"{api(client, ws)}/ai/accounts/{ACCOUNT}/billing", json={"fingerprint": fingerprint(client, ws), **body}
    )


def test_a_native_account_offers_the_report_off_and_a_plain_account_does_not(started):
    ws, client, _ = started
    mine = account(client, ws)
    assert (mine["cost_report_offered"], mine["billing_key_state"], mine["cost_report_hours"]) == (True, "none", 0)
    assert mine["billing_key_id"] is None
    other = next(a for a in client.get(f"{api(client, ws)}/ai/accounts").json() if a["adapter"] == "stub")
    assert other["cost_report_offered"] is False


def test_the_organizations_keys_are_listed_to_pick_from_with_a_key_not_yet_saved(started):
    ws, client, service = started
    found = client.post(f"{api(client, ws)}/ai/accounts/{ACCOUNT}/billing-keys", json={"key": "admin"}).json()
    assert [(k["id"], k["name"], k["hint"]) for k in found["keys"]] == [
        ("apikey_example_one", "Example runs", "sk-example-...abcd"),
        ("apikey_example_three", "Example tests", "sk-example-...mnop"),
    ]
    assert found["problem"] is None and account(client, ws)["billing_key_state"] == "none"  # nothing saved
    none = client.post(f"{api(client, ws)}/ai/accounts/{ACCOUNT}/billing-keys", json={}).json()
    assert none["keys"] == [] and none["problem"]  # no key anywhere: said, no request made
    assert len(service.seen) == 1


def test_a_refused_billing_key_is_said_at_once_and_nothing_is_saved(started):
    ws, client, service = started
    service.refuse = True
    before = fingerprint(client, ws)
    done = add_key(client, ws, key="admin", hours=4)
    assert done.status_code == 400 and done.json()["detail"] == cost_report.PROBLEMS["auth"]
    assert fingerprint(client, ws) == before
    assert account(client, ws)["billing_key_state"] == "none"
    assert not list((ws.private_dir / "keys").glob("*billing*"))  # the pasted key was never kept


def test_a_good_billing_key_is_kept_on_this_computer_with_the_key_and_hours(started):
    ws, client, service = started
    done = add_key(client, ws, key="admin-secret-value", key_id="apikey_example_one", hours=4)
    assert done.status_code == 200 and len(service.seen) == 1
    mine = account(client, ws)
    assert (mine["billing_key_state"], mine["billing_key_id"], mine["cost_report_hours"]) == (
        "saved",
        "apikey_example_one",
        4,
    )
    assert "admin-secret-value" not in json.dumps(client.get(f"{api(client, ws)}/ai/accounts").json())
    assert "admin-secret-value" not in json.dumps(client.get(f"{api(client, ws)}/settings").json())
    stored = load_config(ws.config_dir, env={}).ai.providers[ACCOUNT]
    assert stored.billing_auth.startswith("file:") and "admin-secret-value" not in stored.billing_auth
    kept = next(Path(stored.billing_auth.removeprefix("file:")).parent.glob("*billing*"))
    assert kept.read_text().strip() == "admin-secret-value" and kept.stat().st_mode & 0o077 == 0
    assert service.seen[0].headers["x-api-key"] == "admin-secret-value"
    assert service.seen[0].url.params["api_key_ids[]"] == "apikey_example_one"  # the check used the picked key


def test_hours_without_a_billing_key_are_refused_and_zero_turns_it_off(started):
    ws, client, service = started
    refused = add_key(client, ws, hours=4)
    assert refused.status_code == 400 and "billing key" in refused.json()["detail"] and not service.seen
    add_key(client, ws, key="admin", hours=4)
    off = add_key(client, ws, hours=0)
    assert off.status_code == 200
    mine = account(client, ws)
    assert mine["cost_report_hours"] == 0 and mine["billing_key_state"] == "saved"  # the key stays, the reading stops


def test_the_side_by_side_and_not_now_through_the_routes(started):
    ws, client, _ = started
    add_key(client, ws, key="admin", key_id="apikey_example_one", hours=4)
    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    with store.transaction() as tx:
        tx.create(
            "run",
            {
                "task": "notes",
                "provider": ACCOUNT,
                "model": "m",
                "tier": "routine",
                "outcome": "ok",
                "started_at": datetime.combine(SETTLED, datetime.min.time(), tzinfo=UTC).replace(hour=9).isoformat(),
                "cost_usd": 1.0,
            },
            RUN,
        )
    cost_report.run(
        ws,
        store,
        cfg,
        {},
        now=datetime.now(UTC),
        factory=lambda n, s, k, b=None: ADAPTERS[n](
            s, k, billing_secret=b, transport=httpx.MockTransport(Service().handler)
        ),
    )
    store.close()
    client.app.state.worker.apply_live()
    costs = client.get(f"{api(client, ws)}/ai/costs").json()
    (mine,) = costs["accounts"]
    assert mine["name"] == ACCOUNT and mine["scope"] == "key" and not mine["partial"] and mine["failing"] is None
    day = next(d for d in mine["days"] if d["day"] == SETTLED.isoformat())
    assert day["reported"] and day["amount"] == 5.0 and day["app_usd"] == 1.0 and day["by_task"] == {"notes": 1.0}
    assert day["gap"] is True
    line = next(x for x in client.get(f"{api(client, ws)}/today/queue").json() if x["kind"] == "cost_gap")
    assert (line["account"], line["count"], line["provider_usd"], line["app_usd"]) == (ACCOUNT, 1, 5.0, 1.0)
    assert client.post(f"{api(client, ws)}/ai/costs/{ACCOUNT}/not-now").status_code == 200
    assert not [x for x in client.get(f"{api(client, ws)}/today/queue").json() if x["kind"] == "cost_gap"]
    assert client.post(f"{api(client, ws)}/ai/costs/nobody/not-now").status_code == 404


def test_an_account_whose_report_is_off_is_not_in_the_side_by_side(started):
    ws, client, _ = started
    assert client.get(f"{api(client, ws)}/ai/costs").json() == {"accounts": []}


def test_removing_the_account_drops_what_was_kept_for_it(started):
    ws, client, _ = started
    add_key(client, ws, key="admin", hours=4)
    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    cost_report.run(
        ws,
        store,
        cfg,
        {},
        now=datetime.now(UTC),
        factory=lambda n, s, k, b=None: ADAPTERS[n](
            s, k, billing_secret=b, transport=httpx.MockTransport(Service().handler)
        ),
    )
    assert ACCOUNT in cost_report.read(store)["accounts"]
    store.close()
    removed = client.post(
        f"{api(client, ws)}/ai/accounts/{ACCOUNT}/remove", json={"fingerprint": fingerprint(client, ws)}
    )
    assert removed.status_code == 200
    store = Store(ws.db_path, cfg=cfg)
    assert ACCOUNT not in cost_report.read(store)["accounts"]
    store.close()
