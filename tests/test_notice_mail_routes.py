"""The card for mail to yourself (design 7.19): pick lists of accounts that can send mail and of the person's own
addresses, a standing yes the person gives and ends with Undo, and "Send me a test" through the same path as a notice.
Built on the setup tests' workspace; every address is on example.com."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from api.app import create_app
from engine.channels import FakeChannel
from engine.config import load_config
from engine.storage import WriteContext
from tests.test_setup import make

OWN = "own.person@example.com"
SECOND = "second.own@example.com"
_TEST = WriteContext(actor="engine", trust="trusted", op="test.notice-routes")


def build(tmp_path, *, acting=True):
    ws, cfg, store = make(tmp_path)
    watch = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
    watch["sources"] = [{"id": "work-mail", "connector": "mailbox", "label": "Work mail", "settings": {}}]
    watch["acting"] = ["mailbox:work-mail"] if acting else []
    (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump(watch))
    ui = yaml.safe_load((ws.config_dir / "ui.yaml").read_text())
    ui["notifications"]["enabled"] = True
    (ws.config_dir / "ui.yaml").write_text(yaml.safe_dump(ui))
    cfg = load_config(ws.config_dir, env={})
    store.close()
    app = create_app(ws, cfg, "t", start_worker=False)
    fake = FakeChannel(accounts=("mailbox",))
    app.state.store.plugins.core_channels["fake"] = fake.registration()
    pm = cfg.workspace.user.person
    with app.state.store.transaction() as tx:
        found = tx.get("person", pm)
        tx.update("person", pm, {"how_to_reach": {"email": [OWN, SECOND]}}, _TEST, read_version=found.version)
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer t"
    return c, app.state.store, fake, cfg


def test_the_card_offers_the_accounts_that_can_send_mail_and_the_persons_own_addresses_and_the_exact_notice(tmp_path):
    c, store, fake, cfg = build(tmp_path)
    card = c.get("/api/notifications/mail").json()
    assert [a["id"] for a in card["accounts"]] == ["mailbox:work-mail"]
    assert card["addresses"] == [OWN, SECOND] and card["standing"] is None
    assert card["titles_level"] == "none" and card["titles"] is None  # a count only until titles are allowed
    assert "waiting for you" in card["count"]["subject"] and card["test"]["subject"].startswith("A test from")
    assert c.get("/api/notifications").json()["mail_ready"] is True


def test_no_account_that_can_act_means_no_choice_and_mail_is_not_ready(tmp_path):
    c, *_ = build(tmp_path, acting=False)
    assert c.get("/api/notifications/mail").json()["accounts"] == []
    assert c.get("/api/notifications").json()["mail_ready"] is False


def test_the_yes_is_given_replaced_and_ended_with_undo_and_refused_in_plain_words(tmp_path):
    c, store, fake, cfg = build(tmp_path)
    version = c.get("/api/notifications/mail").json()["template_version"]
    body = {"account": "mailbox:work-mail", "address": OWN, "template_version": version}
    given = c.post("/api/notifications/mail/yes", json=body)
    assert given.status_code == 200, given.text
    standing = c.get("/api/notifications/mail").json()["standing"]
    assert standing["address"] == OWN and standing["stale"] == []
    # a new choice replaces it in one change; an address that isn't theirs is refused and changes nothing
    refused = c.post("/api/notifications/mail/yes", json={**body, "address": "someone.else@example.com"})
    assert refused.status_code == 409 and "addresses on your own record" in refused.json()["detail"]
    assert c.get("/api/notifications/mail").json()["standing"]["address"] == OWN
    assert c.post("/api/notifications/mail/yes", json={**body, "address": SECOND}).status_code == 200
    assert c.get("/api/notifications/mail").json()["standing"]["address"] == SECOND
    stale = c.post("/api/notifications/mail/yes", json={**body, "template_version": "0123456789abcdef"})
    assert stale.status_code == 409 and "look at it again" in stale.json()["detail"]
    ended = c.post("/api/notifications/mail/end")
    assert ended.status_code == 200 and c.get("/api/notifications/mail").json()["standing"] is None
    undone = c.post(f"/api/changesets/{ended.json()['changeset']}/undo", json={})
    assert undone.status_code == 200, undone.text
    assert c.get("/api/notifications/mail").json()["standing"]["address"] == SECOND
    assert c.post("/api/notifications/mail/end").status_code == 200
    assert c.post("/api/notifications/mail/end").status_code == 409  # nothing left to end


def test_send_me_a_test_sends_one_notice_to_the_chosen_address_and_says_when_it_could_not(tmp_path):
    c, store, fake, cfg = build(tmp_path)
    nothing = c.post("/api/notifications/mail/test").json()
    assert nothing["ok"] is False and "Choose where notices go" in nothing["problem"]
    version = c.get("/api/notifications/mail").json()["template_version"]
    body = {"account": "mailbox:work-mail", "address": SECOND, "template_version": version}
    assert c.post("/api/notifications/mail/yes", json=body).status_code == 200
    sent = c.post("/api/notifications/mail/test").json()
    assert sent["ok"] is True and sent["act"]
    (delivered,) = fake.delivered
    assert [r.address for r in delivered[0].recipients] == [SECOND]
    fake.mode = "fail"
    failed = c.post("/api/notifications/mail/test").json()
    assert failed["ok"] is False and "Waiting to go out" in failed["problem"]
