"""API routes for notices that something needs the person (design 7.19): what they are set to, what the open screen
shows a browser notice for, and "Send me a test". A notice goes to the person only and carries a count; the address
for it is saved by the secret routes, which keep it as a reference."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from api.schemas import (
    Applied,
    NoticeAppView,
    NoticeMailAccountView,
    NoticeMailTestResult,
    NoticeMailTextView,
    NoticeMailView,
    NoticeMailYesIn,
    NoticeMailYesView,
    NotificationsView,
    NotifyTestIn,
    NotifyTestResult,
    NotifyWaiting,
    NotifyWebhookView,
)
from engine import (
    act_accounts,
    notice_apps,
    notice_content,
    notice_template,
    notifications,
    reminder_content,
    setup,
    standing_yes,
)
from engine.applier import apply_as_person
from engine.config import Config, ConfigError, load_config
from engine.names import People
from engine.notice_acts import NoticeActs
from engine.storage import Store, StoreError
from engine.worker import Events, Worker
from engine.workspace import Workspace


def build_notification_router(ws: Workspace, cfg: Config, store: Store, events: Events, worker: Worker) -> APIRouter:
    r = APIRouter(prefix="/api")

    def current() -> Config:
        """The settings as the files hold them now; the running app may have started with older ones."""
        try:
            return load_config(ws.config_dir, env=dict(os.environ))
        except ConfigError:
            return cfg

    def mail_accounts(now: Config) -> list[NoticeMailAccountView]:
        """The accounts a notice can go through: acting is on for them and their channel can send a message."""
        return [
            NoticeMailAccountView(id=a.id, label=a.label)
            for a in act_accounts.known(store, now)
            if a.acting and reminder_content.channel_for(store.plugins, a.id, "mail") is not None
        ]

    @r.get("/notifications")
    def notifications_view() -> NotificationsView:
        """What the notices are set to now, and why the last note to the address didn't arrive when it didn't."""
        now = current()
        n = now.ui.notifications
        where, name = setup.secret_where(ws, n.webhook)
        return NotificationsView(
            enabled=n.enabled,
            browser=n.browser,
            webhook=NotifyWebhookView(where=where, name=name),
            app=notice_apps.chosen(now).id,
            apps=[NoticeAppView(id=a.id, name=a.name, where=a.where) for a in notice_apps.offered(now)],
            quiet_now=notifications.quiet_now(now, worker.now()),
            mail_ready=bool(mail_accounts(now))
            and bool(notice_content.own_addresses(store.read(), People(store, now).pm)),
            problem=notifications.last_problem(ws),
        )

    @r.get("/notifications/waiting")
    def notifications_waiting() -> NotifyWaiting:
        """What the open screen shows a browser notice for. Empty while notices or the browser target are off."""
        now = current()
        n = now.ui.notifications
        if not (n.enabled and n.browser):
            return NotifyWaiting(browser=False, keys=[], message="")
        found = notifications.waiting(
            ws, store, now, worker.now(), handover=worker.handover_state(), stuck=worker.stuck_since_text()
        )
        return NotifyWaiting(
            browser=not notifications.quiet_now(now, worker.now()), keys=found.keys, message=found.message
        )

    @r.post("/notifications/test")
    def notifications_test(body: NotifyTestIn) -> NotifyTestResult:
        """ "Send me a test": the webhook gets the test note now (even with notices off, so it can be checked first);
        for the browser the answer carries the words, which the open screen shows itself."""
        now = current()
        words = notifications.test_message(now)
        if body.target == "browser":
            return NotifyTestResult(ok=True, message=words)
        sent = notifications.send_test(ws, now, env=dict(os.environ))
        return NotifyTestResult(ok=sent.ok, message=words, problem=sent.problem)

    def guard(fn):
        try:
            return fn()
        except (StoreError, ValueError, KeyError) as err:
            raise HTTPException(status_code=409, detail=str(err)) from None

    @r.get("/notifications/mail")
    def mail_card() -> NoticeMailView:
        """The card for mail to yourself: the accounts that can send mail and the person's own addresses to pick from,
        the standing yes if one stands (and whether it is stale), and the exact notice as it would go."""
        now = current()
        view = store.read()
        people = People(store, now)
        root = reminder_content.root_of(store)
        yes = standing_yes.active(view, standing_yes.NOTICE)
        standing = None
        if yes is not None:
            standing = NoticeMailYesView(
                id=yes.id,
                account=yes.data["account"],
                account_label=act_accounts.label_of(store, now, yes.data["account"]),
                address=yes.data["address"],
                given_at=yes.data["given_at"],
                template_version=yes.data["template"]["version"],
                stale=standing_yes.stale_reasons(store, now, view, people, yes),
            )
        n = now.ui.notifications
        shown = notice_template.render(
            root, form="count", message=notifications.message_for(now, 2), app=now.workspace.name
        )
        sample = ["An example of a decision waiting for you"]
        titled = (
            notice_template.render(
                root, form="titles", message=notifications.message_for(now, 2), app=now.workspace.name, titles=sample
            )
            if n.mail_titles_level != "none"
            else None
        )
        test = notice_template.render(
            root, form="test", message=notifications.test_message(now), app=now.workspace.name
        )
        return NoticeMailView(
            accounts=mail_accounts(now),
            addresses=notice_content.own_addresses(view, people.pm),
            standing=standing,
            template_version=notice_template.version(root),
            titles_level=n.mail_titles_level,
            count=NoticeMailTextView(subject=shown.subject, body=shown.body),
            titles=NoticeMailTextView(subject=titled.subject, body=titled.body) if titled else None,
            test=NoticeMailTextView(subject=test.subject, body=test.body),
        )

    @r.post("/notifications/mail/yes")
    def mail_yes(body: NoticeMailYesIn) -> Applied:
        """The person's yes to notices by mail on this account and this one of their own addresses: ends the one that
        stands, if any, and gives this one, as one change with Undo. Refused in plain words when the address isn't
        theirs, the account can't send mail or the notice changed since they looked."""
        ops = []
        if (stands := standing_yes.active(store.read(), standing_yes.NOTICE)) is not None:
            ops.append({"op": "standing_yes.end", "id": stands.id})
        ops.append(
            {
                "op": "standing_yes.give",
                "account": body.account,
                "form": "notice",
                "address": body.address,
                "template_version": body.template_version,
            }
        )
        cs_id = guard(
            lambda: apply_as_person(store, current(), ops, "Said yes to notices by mail", all_or_nothing=True)
        )
        events.changed()
        return Applied(changeset=cs_id)

    @r.post("/notifications/mail/end")
    def mail_end() -> Applied:
        """End the standing yes for notices by mail, with Undo."""
        stands = standing_yes.active(store.read(), standing_yes.NOTICE)
        if stands is None:
            raise HTTPException(status_code=409, detail="nothing to end")
        op = {"op": "standing_yes.end", "id": stands.id}
        cs_id = guard(lambda: apply_as_person(store, current(), [op], "Ended notices by mail"))
        events.changed()
        return Applied(changeset=cs_id)

    @r.post("/notifications/mail/test")
    def mail_test() -> NoticeMailTestResult:
        """ "Send me a test" for mail: the test notice goes through the same path as a real one (drafted, approved
        under the standing yes, sent), even with notices off, so it can be tried first."""
        try:
            act_id = NoticeActs(ws, store, current(), now=worker.now).send_test()
        except StoreError as err:
            return NoticeMailTestResult(ok=False, problem=str(err))
        events.changed()
        status = store.read().get("act", act_id).data["status"]
        if status != "sent":
            return NoticeMailTestResult(
                ok=False,
                act=act_id,
                problem="The test could not be sent. It is in Waiting to go out, where you can try it again.",
            )
        return NoticeMailTestResult(ok=True, act=act_id)

    return r
