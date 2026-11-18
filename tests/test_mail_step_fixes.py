"""The Mail step's fixes from the first real test (S-0636, S-0637, S-0638, plugin API 0.3.102): the full read answers
every open mail source of an account (inbox and sent mail), a count the service only estimated says so, a look that
takes in far fewer than its count says so, `Poll.capped` ends a first read's window, and a signed-out account's
sources count for neither the Mail step nor the first reading's wait. The AI is the stub."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import yaml
from fastapi.testclient import TestClient

from engine import setup, source_intake
from engine.config import load_config
from engine.config.schema import Price
from engine.storage import Store
from engine.watch import refresh
from tests.test_first_sign_in import KEPT_WHERE, from_person
from tests.test_look_back_addons import _manifest
from tests.test_today_panels_jobs import workspace

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
TOKEN = "mail-step-token"
ACCOUNT = "person@example.com"

# The fixture reader, with a count that can be an estimate or claim more than the reader gives, and a poll that can say
# its first read was capped (by the field, or by the earlier state key).
_FIELDS = (
    '    log: str = ""\n    estimate: bool = False\n    claimed: int = 0\n'
    "    capped: bool = False\n    state_capped: bool = False"
)
_POLL = (
    '    state = {"capped": True} if settings.state_capped else {}\n'
    "    return Poll([build(i) for i in settings.items], state, capped=settings.capped)"
)
_COUNT = (
    "    n = settings.claimed or len(within(settings, since, before))\n"
    "    return OlderCount(min(n, limit), True) if settings.estimate else min(n, limit)"
)
PLUGIN = (
    KEPT_WHERE.replace(
        "from engine.plugin_api import MessageDetails,", "from engine.plugin_api import OlderCount, MessageDetails,"
    )
    .replace('    log: str = ""', _FIELDS)
    .replace("    return Poll([build(i) for i in settings.items], {})", _POLL)
    .replace("    return min(len(within(settings, since, before)), limit)", _COUNT)
)
assert PLUGIN.count("OlderCount") == 2 and "state_capped" in PLUGIN and "claimed" in PLUGIN


def make(tmp_path, now=NOW, **extra):
    """One account of the add-on, three sources: its inbox, its sent mail and a second inbox of another account."""
    ws, cfg, store = workspace(tmp_path, PLUGIN)
    store.close()
    (ws.root / "plugins" / "p18" / "plugin.yaml").write_text(yaml.safe_dump(_manifest()))
    first = [from_person(f"a{i}", 0, 1 + i, now=now) for i in range(3)]
    older = [
        from_person("o20", 0, 20, now=now),
        from_person("o21", 1, 21, where="deleted", now=now),
        from_person("o22", 0, 22, where="archived", now=now),
    ]
    sent = [from_person(f"s{i}", 2, 1 + i, now=now) for i in range(2)]
    sent_older = [from_person("so25", 2, 25, now=now), from_person("so26", 2, 26, now=now)]
    sources = [
        {
            "id": "m",
            "connector": "p18/inbox",
            "label": "Your inbox",
            "account": ACCOUNT,
            "settings": {"items": first, "older": older, **extra},
        },
        {
            "id": "s",
            "connector": "p18/inbox",
            "label": "Your sent mail",
            "account": ACCOUNT,
            "settings": {"items": sent, "older": sent_older},
        },
    ]
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump({"version": 1, "sources": sources, "sorting": "rules"}))
    cfg = load_config(ws.config_dir, env={})
    use = cfg.ai.tiers["routine"].use
    cfg.ai.prices[use] = Price(input_per_million=50.0, output_per_million=50.0)
    cfg.ai.budgets.confirm_above_usd = 0.10
    cfg.ai.budgets.first_go = False
    store = Store(ws.db_path, cfg=cfg)
    assert store.plugins.active("p18"), store.plugins.status["p18"].reason
    return ws, cfg, store


def test_the_full_read_is_offered_and_answered_for_every_mail_source_of_the_account_sent_mail_included(tmp_path):
    ws, cfg, store = make(tmp_path, datetime.now(UTC))
    store.close()
    from api.app import create_app

    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        for source in ("m", "s"):
            assert client.post(f"/api/watch/{source}/read").status_code == 200
        shown = {s["id"]: s for s in client.get("/api/watch").json()}
        assert shown["m"]["full_read_open"] and shown["s"]["full_read_open"], "the sent mail is asked too"
        took = {}
        for source in ("m", "s"):
            answered = client.post(f"/api/watch/{source}/full-read", json={"days": 30})
            assert answered.status_code == 200
            took[source] = answered.json()["taken"]
        assert took == {"m": 3, "s": 2}, "each source reads its own older mail"
        after = {s["id"]: s for s in client.get("/api/watch").json()}
        assert not after["m"]["full_read_open"] and not after["s"]["full_read_open"]


def test_a_source_read_for_the_first_time_after_the_answer_takes_the_accounts_answer_and_not_now_stays_not_now(
    tmp_path,
):
    ws, cfg, store = make(tmp_path, datetime.now(UTC))
    store.close()
    from api.app import create_app

    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        # The inbox is read and answered before the sent mail has had its first read (H4-06).
        assert client.post("/api/watch/m/read").status_code == 200
        assert client.post("/api/watch/m/full-read", json={"days": 30}).status_code == 200
        assert client.post("/api/watch/s/read").status_code == 200
        shown = {x["id"]: x for x in client.get("/api/watch").json()}
        assert not shown["s"]["full_read_open"], (
            "the account's one answer covers the sent mail, which asks nothing again"
        )
        sent = [x for x in client.get("/api/watch").json() if x["id"] == "s"][0]
        assert sent["items"] == 2 + 2, "its older mail was taken in without a second press"


def test_a_count_the_service_only_estimated_says_so_and_an_exact_one_does_not(tmp_path):
    for estimate in (True, False):
        ws, cfg, store = make(tmp_path / str(estimate), estimate=estimate)
        try:
            refresh(ws, store, cfg, "m", NOW)
            options = source_intake.full_read_options(ws, store, cfg, "m", NOW)
            assert [o.estimate for o in options if o.count] == [estimate] * len([o for o in options if o.count])
            assert source_intake.look_back_preview(ws, store, cfg, "m", 20, NOW, exact=True).estimate is estimate
        finally:
            store.close()


def test_an_estimate_reaches_the_screen_through_the_routes(tmp_path):
    ws, cfg, store = make(tmp_path, datetime.now(UTC), estimate=True)
    store.close()
    from api.app import create_app

    app = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        client.post("/api/watch/m/read")
        shown = client.get("/api/watch/m/full-read").json()
        assert [o["estimate"] for o in shown["options"] if o["count"]] == [True, True]
        assert (
            client.get("/api/watch/m/look-back", params={"days": cfg.watch.look_back_choices[0]}).json()["estimate"]
            is True
        )


def test_a_look_that_takes_in_far_fewer_than_its_count_says_so_and_a_fair_one_does_not(tmp_path):
    # The service says about 201 and gives 3: well under a third.
    ws, cfg, store = make(tmp_path / "few", estimate=True, claimed=201)
    try:
        refresh(ws, store, cfg, "m", NOW)
        done = source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        assert (done.short, done.expected, done.expected_estimate, done.gave) == (True, 201, True, 3)
    finally:
        store.close()
    # An exact count that the reading matches is never called short.
    ws, cfg, store = make(tmp_path / "fair")
    try:
        refresh(ws, store, cfg, "m", NOW)
        done = source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW)
        assert (done.short, done.expected, done.gave) == (False, 3, 3)
    finally:
        store.close()
    # Exactly a third is not short: 3 given of 9.
    ws, cfg, store = make(tmp_path / "third", claimed=9)
    try:
        refresh(ws, store, cfg, "m", NOW)
        assert source_intake.answer_full_read(ws, store, cfg, "m", 30, NOW).short is False
    finally:
        store.close()


@pytest.mark.parametrize("how", ["field", "state"])
def test_a_capped_first_read_looks_back_only_as_far_as_its_oldest_message(tmp_path, how):
    # The field is how a connector says it; the earlier state key still works. Neither: the whole window was looked at.
    extra = {"capped": True} if how == "field" else {"state_capped": True}
    ws, cfg, store = make(tmp_path / how, **extra)
    try:
        refresh(ws, store, cfg, "m", NOW)
        window = (NOW - timedelta(days=cfg.watch.sources[0].first_run_days)).date()
        capped = source_intake.back_to_of(store.read(), "m")
        assert capped == max(window, (NOW - timedelta(days=3)).date())
    finally:
        store.close()
    ws, cfg, store = make(tmp_path / "plain")
    try:
        refresh(ws, store, cfg, "m", NOW)
        window = (NOW - timedelta(days=cfg.watch.sources[0].first_run_days)).date()
        assert source_intake.back_to_of(store.read(), "m") == window
    finally:
        store.close()


def test_a_signed_out_or_expired_accounts_sources_count_for_neither_the_mail_step_nor_the_readings_wait(
    tmp_path, monkeypatch
):
    ws, cfg, store = make(tmp_path)
    try:
        from engine import sign_in_sources

        monkeypatch.setattr("engine.ai.smoke.ai_state", lambda *a, **k: ("ok", None))
        for source in ("m", "s"):
            refresh(ws, store, cfg, source, NOW)
        said = {"p18/inbox": "mail"}
        assert [s.id for s in setup.read_sources(ws, cfg, store, said)] == ["m", "s"]

        def out(only, state="signed_out"):
            return lambda _ws, _store, source, refused=False: state if source.id in only else "signed_in"

        # One source's account signed out: the wait counts the other only.
        monkeypatch.setattr(sign_in_sources, "account_state", out({"m"}))
        assert [s.id for s in setup.read_sources(ws, cfg, store, said)] == ["s"]
        found = setup.steps(ws, cfg, store)
        assert {s.id: s.done for s in found}["mail"] is True
        assert setup.reading(ws, cfg, store, found, NOW).sources == 1
        # Every source signed out: Mail is not done, there is no wait, and People is by hand.
        monkeypatch.setattr(sign_in_sources, "account_state", out({"m", "s"}))
        found = setup.steps(ws, cfg, store)
        assert {s.id: s.done for s in found}["mail"] is False
        assert setup.reading(ws, cfg, store, found, NOW).state == "none"
        assert setup.people_by_hand(found) is True
        # An expired sign-in isn't read until the person signs in again either: the same as signed out.
        monkeypatch.setattr(sign_in_sources, "account_state", out({"m", "s"}, "expired"))
        found = setup.steps(ws, cfg, store)
        assert {s.id: s.done for s in found}["mail"] is False
        assert setup.reading(ws, cfg, store, found, NOW).state == "none"
    finally:
        store.close()
