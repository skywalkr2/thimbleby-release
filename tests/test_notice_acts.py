"""Notices by mail to the person (design 7.19): a standing yes of the form `notice` lets the engine approve a notice act
only when it is, in every respect, the notice the engine drafts for the person themselves: to the one own address the
person chose, through their chosen account, exactly the notice template's words, titles only at a level the person
allowed. Anything else waits for the person's own yes like any act. Built on the publisher tests' workspace; names and
addresses come from the fixtures and every address is on example.com."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from engine import notice_acts, notice_content, notice_template, reminder_content, standing_yes
from engine.applier import apply_as_person, apply_for_reminders
from engine.channels import FakeChannel
from engine.config.schema import WatchSource
from engine.names import People
from engine.storage import StoreError, WriteContext
from tests.test_publisher import Env

_ENGINE = WriteContext(actor="engine", trust="trusted", op="test.notice-acts")
MAILBOX = "work-mail"
ACCOUNT = f"mailbox:{MAILBOX}"
OWN = "own.person@example.com"
SECOND_OWN = "second.own@example.com"


class Notices:
    def __init__(self, env: Env):
        self.env = env
        self.pass_ = notice_acts.NoticeActs(env.ws, env.store, env.cfg, now=env.clock, publisher=env.publisher)

    @property
    def root(self):
        return reminder_content.root_of(self.env.store)

    def version(self) -> str:
        return notice_template.version(self.root)

    def give(self, account: str = ACCOUNT, address: str = OWN, version: str | None = None) -> str:
        op = {
            "op": "standing_yes.give",
            "account": account,
            "form": "notice",
            "address": address,
            "template_version": version or self.version(),
        }
        cs = apply_as_person(self.env.store, self.env.cfg, [op], "Said yes to notices by mail")
        return self.env.store.read().get("changeset", cs).data["ops"][0]["records"][0]["id"]

    def waiting(self, title: str = "Ship the run now?", **more: Any) -> str:
        data = {"to": self.env.pm, "title": title, "kind": "decision", "status": "open", **more}
        with self.env.store.transaction() as tx:
            return tx.create("question", data, _ENGINE).id

    def told_the_rest(self) -> int:
        """The fictional workspace already has things waiting: the first pass tells them, and its notice is set aside
        so a test counts only what it adds. Returns how many wait."""
        self.pass_.sweep()
        found = self.acts()
        return found[-1].data["notice"]["count"] if found else 0

    def acts(self) -> list[Any]:
        return [a for a in self.env.store.read().list("act") if a.data.get("notice")]

    def act(self, act_id: str) -> dict:
        return self.env.act(act_id)

    def edit(self, act_id: str, **fields: Any) -> None:
        with self.env.store.transaction() as tx:
            found = tx.get("act", act_id)
            tx.update("act", act_id, fields, _ENGINE, read_version=found.version)

    def draft_op(self, **notice: Any) -> dict:
        yes = standing_yes.active(self.env.store.read(), standing_yes.NOTICE)
        exp = notice_content.expected(
            self.env.store,
            self.env.cfg,
            account=yes.data["account"],
            channel=yes.data["channel"],
            person=self.env.pm,
            address=yes.data["address"],
            count=notice.get("count", 1),
            titles=notice.get("titles", []),
            test=notice.get("test", False),
        )
        return {
            "op": "act.draft",
            "channel": exp.channel,
            "target": exp.draft_target(),
            "parts": exp.parts,
            "template": exp.template,
            "account": exp.account,
            "notice": {"count": 1, "titles": [], "test": False, **notice},
        }

    def draft(self, **notice: Any) -> str:
        cs = apply_for_reminders(self.env.store, self.env.cfg, self.draft_op(**notice), "A notice drafted")
        return self.env.store.read().get("changeset", cs).data["ops"][0]["records"][0]["id"]

    def approve(self, act_id: str, yes_id: str) -> str:
        op = {"op": "act.approve", "id": act_id, "fingerprint": self.env.fingerprint(act_id), "by_standing": yes_id}
        return apply_for_reminders(self.env.store, self.env.cfg, op, "Approved under a standing yes", standing=True)


@pytest.fixture
def notices(tmp_path, demo):
    env = Env(tmp_path, demo)
    env.use(FakeChannel(accounts=("mailbox",)))
    env.cfg.watch.sources.append(WatchSource(id=MAILBOX, connector="mailbox", label="Work mail"))
    env.cfg.watch.acting.append(ACCOUNT)
    env.cfg.ui.notifications.enabled = True
    env.set_address(env.pm, [OWN, SECOND_OWN])
    # the fixture clock is inside the notices' quiet hours by default; a midday clock is outside them
    env.clock.at = datetime(2030, 3, 4, 12, 0, tzinfo=UTC)
    found = Notices(env)
    yield found
    env.close()


# ---- giving and ending the yes ---------------------------------------------------------------------------------------


def test_the_yes_records_the_account_one_own_address_and_the_template_it_saw(notices):
    yes = notices.give(address=SECOND_OWN.upper())
    data = notices.env.store.read().get("standing_yes", yes).data
    assert (data["form"], data["account"], data["address"]) == ("notice", ACCOUNT, SECOND_OWN)
    assert data["template"] == {"name": "notice", "version": notices.version()}
    assert standing_yes.active(notices.env.store.read(), standing_yes.NOTICE).id == yes
    assert standing_yes.active(notices.env.store.read()) is None  # it is not the yes for reminders


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"address": "someone.else@example.com"}, "addresses on your own record"),
        ({"version": "0123456789abcdef"}, "look at it again"),
        ({"account": "mailbox:home-mail"}, "assistant can act on"),
    ],
)
def test_a_yes_for_an_address_that_isnt_theirs_a_changed_template_or_an_unknown_account_is_refused(
    notices, kwargs, why
):
    with pytest.raises(StoreError, match=why):
        notices.give(**kwargs)
    assert notices.env.store.read().list("standing_yes") == []


def test_an_account_acting_isnt_turned_on_for_is_refused(notices):
    notices.env.cfg.watch.acting.clear()
    with pytest.raises(StoreError, match="Let the assistant act"):
        notices.give()


def test_a_second_yes_for_notices_is_refused_but_one_for_reminders_stands_beside_it(notices):
    notices.give()
    with pytest.raises(StoreError, match="notices already stands"):
        notices.give()
    from engine import reminder_template

    reminder = {
        "op": "standing_yes.give",
        "account": ACCOUNT,
        "form": "mail",
        "template_version": reminder_template.version(notices.root),
    }
    apply_as_person(notices.env.store, notices.env.cfg, [reminder], "Said yes to reminders")
    assert standing_yes.active(notices.env.store.read()).data["form"] == "mail"
    assert standing_yes.active(notices.env.store.read(), "notice").data["form"] == "notice"


def test_an_address_given_with_a_reminder_is_refused(notices):
    from engine import reminder_template

    op = {
        "op": "standing_yes.give",
        "account": ACCOUNT,
        "form": "mail",
        "template_version": reminder_template.version(notices.root),
        "address": OWN,
    }
    with pytest.raises(StoreError, match="address is for a notice"):
        apply_as_person(notices.env.store, notices.env.cfg, [op], "Said yes")


# ---- what the yes approves -------------------------------------------------------------------------------------------


def test_the_notice_the_engine_drafts_is_approved_and_sent_under_the_yes(notices):
    yes = notices.give()
    act_id = notices.draft(count=2)
    data = notices.act(act_id)
    assert data["made_by"] == "notices" and data["notice"]["count"] == 2
    assert data["parts"]["subject"] == "2 decisions waiting for you"
    assert [r["address"] for r in data["target"]["recipients"]] == [OWN]
    notices.approve(act_id, yes)
    assert notices.act(act_id)["approved"]["standing_yes"] == yes
    notices.env.publisher.send(act_id)
    assert notices.act(act_id)["status"] == "sent"


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"parts": {"subject": "Hello", "body": "Something else"}}, "notice template rendered"),
        ({"template": {"name": "notice", "version": "0123456789abcdef"}}, "template at the version"),
        ({"in_reply_to": "SRC-1"}, "draws on nothing"),
        ({"sources": ["SRC-1"]}, "draws on nothing"),
    ],
)
def test_a_notice_changed_in_any_respect_is_not_approved_under_the_yes(notices, change, why):
    yes = notices.give()
    act_id = notices.draft()
    notices.edit(act_id, **change)
    with pytest.raises(StoreError, match=why):
        notices.approve(act_id, yes)
    assert notices.act(act_id)["status"] == "draft"


def test_a_notice_to_another_address_or_another_person_is_not_approved(notices):
    yes = notices.give()
    to_other = notices.draft()
    target = notices.act(to_other)["target"]
    other = {**target, "recipients": [{**target["recipients"][0], "address": SECOND_OWN}]}
    notices.edit(to_other, target=other)
    with pytest.raises(StoreError, match="address the person chose"):
        notices.approve(to_other, yes)
    to_both = notices.draft()
    both = {**target, "recipients": [*target["recipients"], {**target["recipients"][0], "address": "x@example.com"}]}
    notices.edit(to_both, target=both)
    with pytest.raises(StoreError, match="to the person alone"):
        notices.approve(to_both, yes)
    other_person = notices.draft()
    notices.edit(
        other_person,
        target={**target, "recipients": [{**target["recipients"][0], "person": notices.env.ana, "address": OWN}]},
    )
    with pytest.raises(StoreError, match="address the person chose"):
        notices.approve(other_person, yes)


def test_a_title_is_in_a_notice_only_at_a_level_the_person_allowed_and_never_restricted(notices):
    yes = notices.give()
    shown = [{"text": "Ship the run now?", "level": "internal"}]
    # titles are off by default: a notice with one is refused even though the template could render it
    with pytest.raises(StoreError, match="didn't allow"):
        notices.draft(count=1, titles=shown)
    notices.env.cfg.ui.notifications.mail_titles_level = "internal"
    act_id = notices.draft(count=1, titles=shown)
    assert "Ship the run now?" in notices.act(act_id)["parts"]["body"]
    notices.approve(act_id, yes)
    # the person turns titles off after the draft was made: the approval no longer holds
    second = notices.draft(count=1, titles=shown)
    notices.env.cfg.ui.notifications.mail_titles_level = "none"
    with pytest.raises(StoreError, match="didn't allow"):
        notices.approve(second, yes)
    assert notice_content.title_allowed(notices.env.cfg, "restricted") is False
    notices.env.cfg.ui.notifications.mail_titles_level = "open"
    assert notice_content.title_allowed(notices.env.cfg, "internal") is False


def test_an_act_that_is_not_a_notice_is_never_approved_under_the_notices_yes(notices):
    yes = notices.give()
    ordinary = notices.env.draft(to=[notices.env.pm], account=ACCOUNT)
    with pytest.raises(StoreError, match="only a notice the engine made"):
        notices.approve(ordinary, yes)


def test_a_yes_for_notices_never_approves_a_reminder_and_the_reminder_yes_never_approves_a_notice(notices):
    from engine import reminder_template
    from tests.test_standing_yes import Reminders

    notice_yes = notices.give()
    reminders = Reminders(notices.env, "mail")
    reminders.env.cfg.steward.reminders.where = "mail"
    reminders.env.cfg.steward.reminders.where_account = ACCOUNT
    reminder_yes = reminders.give()
    _, reminder_act = reminders.draft_one()
    with pytest.raises(StoreError, match="only a notice the engine made"):
        notices.approve(reminder_act, notice_yes)
    notice_act = notices.draft()
    with pytest.raises(StoreError, match="only a reminder the engine made"):
        notices.approve(notice_act, reminder_yes)
    assert reminder_template.NAME != notice_template.NAME


def test_only_the_engines_own_pass_drafts_a_notice_and_only_with_a_yes_that_stands(notices):
    op = {"op": "act.draft", **{k: v for k, v in notices.env.message(to=[notices.env.pm]).items() if k != "op"}}
    # no yes yet: the engine's own draft is refused
    with pytest.raises(StoreError, match="no standing yes for notices"):
        apply_for_reminders(notices.env.store, notices.env.cfg, {**op, "notice": {"count": 1}}, "A notice drafted")
    notices.give()
    # the person drafting an act that claims to be a notice, or the assistant, is refused
    with pytest.raises(StoreError, match="only the engine"):
        apply_as_person(notices.env.store, notices.env.cfg, [notices.draft_op()], "Drafted")


def test_a_yes_goes_stale_when_the_address_leaves_the_record_the_account_stops_acting_or_the_words_change(notices):
    yes = notices.give(address=SECOND_OWN)

    def stale() -> list[str]:
        view = notices.env.store.read()
        return standing_yes.stale_reasons(
            notices.env.store,
            notices.env.cfg,
            view,
            People(notices.env.store, notices.env.cfg),
            view.get("standing_yes", yes),
        )

    assert stale() == []
    notices.env.set_address(notices.env.pm, OWN)
    assert stale() == ["address"]
    notices.env.set_address(notices.env.pm, [OWN, SECOND_OWN])
    assert stale() == []
    notices.env.cfg.watch.acting.clear()
    assert "acting" in stale()
    notices.env.cfg.watch.acting.append(ACCOUNT)
    (notices.env.ws.root / "templates").mkdir(exist_ok=True)
    (notices.env.ws.root / "templates" / "notice.yaml").write_text(
        notice_template.SHIPPED.read_text(encoding="utf-8").replace("Open {app}", "Please open {app}")
    )
    assert stale() == ["template"]


# ---- the pass --------------------------------------------------------------------------------------------------------


def test_a_new_item_in_the_decide_group_is_one_notice_sent_once_and_the_same_items_are_not_told_again(notices):
    notices.give()
    base = notices.told_the_rest()
    before = len(notices.acts())
    assert notices.pass_.sweep() is False and len(notices.acts()) == before  # nothing new waits
    notices.waiting()
    assert notices.pass_.sweep() is True
    found = notices.acts()[-1]
    assert len(notices.acts()) == before + 1
    assert found.data["status"] == "sent" and found.data["notice"]["count"] == base + 1
    assert "Ship the run now?" not in found.data["parts"]["body"]  # a count only by default
    assert notices.pass_.sweep() is False and len(notices.acts()) == before + 1
    # a second item makes a second notice, and the app being restarted repeats nothing
    notices.waiting("Order the proofs now?")
    again = notice_acts.NoticeActs(
        notices.env.ws, notices.env.store, notices.env.cfg, now=notices.env.clock, publisher=notices.env.publisher
    )
    assert again.sweep() is True and len(notices.acts()) == before + 2
    assert again.sweep() is False and len(notices.acts()) == before + 2


def test_nothing_is_drafted_with_notices_off_without_a_yes_or_in_quiet_hours_and_it_goes_when_they_end(notices):
    notices.waiting()
    assert notices.pass_.sweep() is False  # no yes
    notices.give()
    notices.env.cfg.ui.notifications.enabled = False
    assert notices.pass_.sweep() is False and notices.acts() == []
    notices.env.cfg.ui.notifications.enabled = True
    notices.env.clock.at = datetime(2030, 3, 4, 23, 0, tzinfo=UTC)  # inside the quiet hours
    assert notices.pass_.sweep() is False and notices.acts() == []
    notices.env.clock.at = datetime(2030, 3, 5, 8, 0, tzinfo=UTC)  # they ended
    assert notices.pass_.sweep() is True and len(notices.acts()) == 1


def test_titles_go_in_a_notice_for_items_up_to_the_allowed_level_and_restricted_ones_never(notices):
    notices.give()
    notices.told_the_rest()
    notices.env.cfg.ui.notifications.mail_titles_level = "internal"
    with notices.env.store.transaction() as tx:
        quiet = tx.create(
            "source",
            {
                "received_at": notices.env.clock().isoformat(),
                "kind": "paste",
                "title": "x",
                "content_hash": "a" * 64,
                "trust": "untrusted",
                "sensitivity": "restricted",
            },
            _ENGINE,
        ).id
    notices.waiting("An ordinary decision?")
    notices.waiting("A confidential decision?", source=quiet)
    assert notices.pass_.sweep() is True
    found = notices.acts()[-1]
    body = found.data["parts"]["body"]
    assert "An ordinary decision?" in body and "A confidential decision?" not in body
    levels = [t["level"] for t in found.data["notice"]["titles"]]
    assert "restricted" not in levels and "internal" in levels
    assert found.data["notice"]["count"] > len(levels)  # more wait than are named


def test_a_notice_the_standing_yes_does_not_cover_is_not_drafted_and_the_yes_stays_for_the_person_to_look_at(notices):
    yes = notices.give()
    notices.waiting()
    # the template's words changed after the yes: the yes is stale, so no notice is drafted at all
    (notices.env.ws.root / "templates").mkdir(exist_ok=True)
    (notices.env.ws.root / "templates" / "notice.yaml").write_text(
        notice_template.SHIPPED.read_text(encoding="utf-8").replace("Open {app}", "Please open {app}")
    )
    assert notices.pass_.sweep() is False and notices.acts() == []
    assert standing_yes.active(notices.env.store.read(), "notice").id == yes


def test_a_notice_the_channel_could_not_send_is_a_failed_act_the_person_sees_and_is_not_drafted_again(notices):
    notices.env.fake.mode = "fail"
    notices.give()
    notices.waiting()
    notices.pass_.sweep()
    before = len(notices.acts())
    assert before >= 1 and notices.acts()[-1].data["status"] == "failed"
    notices.pass_.sweep()
    assert len(notices.acts()) == before  # the same items are not drafted again


# ---- Send me a test --------------------------------------------------------------------------------------------------


def test_send_me_a_test_goes_the_same_way_with_notices_off_and_names_what_it_is(notices):
    notices.env.cfg.ui.notifications.enabled = False
    with pytest.raises(StoreError, match="Choose where notices go"):
        notices.pass_.send_test()
    notices.give()
    act_id = notices.pass_.send_test()
    data = notices.act(act_id)
    assert data["status"] == "sent" and data["made_by"] == "notices" and data["notice"]["test"] is True
    (delivered,) = notices.env.fake.delivered
    assert [r.address for r in delivered[0].recipients] == [OWN]
    assert data["parts"]["subject"].startswith("A test from")
    assert notices.env.cfg.ui.notifications.test_message in data["parts"]["body"]
    assert [r["address"] for r in data["target"]["recipients"]] == [OWN]


def test_a_test_with_a_stale_yes_is_refused_in_plain_words(notices):
    notices.give(address=SECOND_OWN)
    notices.env.set_address(notices.env.pm, OWN)
    with pytest.raises(StoreError, match="out of date"):
        notices.pass_.send_test()
    assert notices.acts() == []


# ---- a notice coming back --------------------------------------------------------------------------------------------


def test_a_notice_that_comes_back_into_a_read_inbox_is_known_by_its_message_id_and_is_nothing_new(notices):
    from engine.watch import refresh

    yes = notices.give()
    act_id = notices.draft()
    notices.approve(act_id, yes)
    notices.env.publisher.send(act_id)
    sent_id = notices.act(act_id)["service_id"]
    own = {"sender": f"A Person <{OWN}>", "received": "2030-03-04T11:59:00Z", "message_id": sent_id}
    other = {
        "sender": "Someone Else <someone@example.com>",
        "received": "2030-03-04T11:58:00Z",
        "message_id": "<x@example.com>",
    }
    notices.env.cfg.watch.sources.append(
        WatchSource(
            id="notice-inbox",
            connector="fake",
            label="Inbox",
            first_run="all",
            settings={
                "items": [
                    {"key": "own", "title": "1 decision waiting for you", "text": "Open the app.", "message": own},
                    {"key": "other", "title": "A message from someone", "text": "Hello.", "message": other},
                ]
            },
        )
    )
    result = refresh(
        notices.env.ws, notices.env.store, notices.env.cfg, "notice-inbox", datetime(2030, 3, 4, 12, 0, tzinfo=UTC)
    )
    handed = [
        notices.env.store.read()
        .get("source", notices.env.store.read().get("request", r).data["source"])
        .data["watched"]["key"]
        for r in result.new
    ]
    assert handed == ["other"]
