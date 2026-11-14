"""Notices that reach the person by mail while the app isn't open (design 7.19): the engine drafts one act for each
notice, to one of the person's own addresses, and keeps them true.

When the person has chosen an account and one of their own addresses (a standing yes of the form `notice`), a notice
comes up as it does for the other targets (`engine/notifications.py`): when an item enters Today's Decide group that the
person has not been told about, one notice says how many wait, nothing goes in quiet hours, and what came up then goes
out once when they end. The notice is one act (`made_by: notices`) to that one address, worded by the core's notice
template (`engine/notice_content.py` works out the exact act); titles are in it only for items the person allowed
titles for. While the standing yes stands and matches, the engine approves the act and the publisher sends it. All of
that is decided by the applier's invariants (`act-reminder` for the draft, `act-approval` for the approval), never here.
"Send me a test" is the same path with the test's own words. What was told is kept in the workspace's private folder,
so a restart never repeats a notice."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from engine import acts, notice_content, notice_template, notifications, standing_yes
from engine.applier import apply_for_reminders
from engine.config import Config
from engine.names import People
from engine.publisher import Publisher
from engine.state_file import write_whole
from engine.storage import Store, StoreError

log = logging.getLogger(__name__)

STATE_FILE = "notified_mail.json"


class NoticeActs:
    """One pass over Today's Decide group and the notice acts. `now` is passed in, so tests never wait."""

    def __init__(
        self, ws: Any, store: Store, cfg: Config, *, now: Callable[[], datetime] | None = None, publisher: Any = None
    ):
        self.ws, self.store, self.cfg = ws, store, cfg
        self.now = now or (lambda: datetime.now(UTC))
        self.publisher = publisher or Publisher(store, cfg, now=self.now)
        #: What was refused and isn't tried again until it changes.
        self._tried: set[tuple[Any, ...]] = set()

    # ---- what is set up ----------------------------------------------------------------------------------------------

    def yes(self) -> Any | None:
        """The person's standing yes for notices, when one stands and is not stale; None otherwise."""
        view = self.store.read()
        found = standing_yes.active(view, standing_yes.NOTICE)
        if found is None:
            return None
        if standing_yes.stale_reasons(self.store, self.cfg, view, People(self.store, self.cfg), found):
            return None
        return found

    def enabled(self) -> bool:
        """Whether notices are on and a standing yes for them stands."""
        return bool(self.cfg.ui.notifications.enabled) and self.yes() is not None

    # ---- what was told -----------------------------------------------------------------------------------------------

    def _state(self) -> dict[str, Any]:
        try:
            data = json.loads((self.ws.private_dir / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        write_whole(self.ws.private_dir / STATE_FILE, json.dumps(data, indent=2) + "\n")

    # ---- the pass ----------------------------------------------------------------------------------------------------

    def sweep(self, handover: tuple[str, str] | None = None, stuck: str | None = None) -> bool:
        """Draft the notice that is due, approve it under the standing yes and send what it approved. Returns whether
        anything changed."""
        changed = False
        if self.enabled():
            changed = self.draft(handover, stuck)
            changed = self.approve() or changed
        return self.send() or changed

    def _notice_acts(self) -> list[Any]:
        return [a for a in self.store.read().list("act") if a.data.get("notice")]

    def draft(self, handover: tuple[str, str] | None = None, stuck: str | None = None) -> bool:
        """Draft one notice when an item has come into the Decide group that the person has not been told about. Not
        in quiet hours; what came up then goes out once when they end."""
        from engine.today_queue import queue

        now = self.now()
        state = self._state()
        lines = [line for line in queue(self.ws, self.store, self.cfg, now, handover=handover, stuck=stuck)]
        decide = [line for line in lines if line.group == "decide"]
        keys = [line.key for line in decide]
        for plugin, line in self.store.plugins.today():
            if line.group == "decide":
                keys.append(f"plugin:{plugin}:{line.id}")
        told = [k for k in state.get("told", []) if k in keys]
        if not keys:
            if state.get("told"):
                self._save({**state, "told": []})
            return False
        if all(k in told for k in keys):
            if told != state.get("told"):
                self._save({**state, "told": told})
            return False
        if notifications.quiet_now(self.cfg, now):
            return False
        yes = self.yes()
        person = People(self.store, self.cfg).pm
        if yes is None or person is None or ("draft", tuple(keys)) in self._tried:
            return False
        view = self.store.read()
        titles = notice_content.titles_for(view, self.cfg, decide)
        try:
            self._draft_act(yes, person, count=len(keys), titles=titles, test=False)
        except (StoreError, notice_template.TemplateError) as err:
            self._tried.add(("draft", tuple(keys)))
            log.warning("Couldn't draft the notice: %s", err)
            return False
        self._save({**state, "told": keys, "sent_at": now.isoformat()})
        return True

    def _draft_act(self, yes: Any, person: str, *, count: int, titles: list[dict[str, str]], test: bool) -> str:
        data = yes.data
        exp = notice_content.expected(
            self.store,
            self.cfg,
            account=data["account"],
            channel=data["channel"],
            person=person,
            address=data["address"],
            count=count,
            titles=titles,
            test=test,
        )
        return apply_for_reminders(
            self.store,
            self.cfg,
            {
                "op": "act.draft",
                "channel": exp.channel,
                "target": exp.draft_target(),
                "parts": exp.parts,
                "template": exp.template,
                "account": exp.account,
                "notice": {"count": count, "titles": titles, "test": test},
            },
            "A notice drafted",
        )

    def approve(self) -> bool:
        """Approve, under the standing yes, each notice draft that matches it. A draft that doesn't stays for the
        person's own yes."""
        yes = self.yes()
        if yes is None:
            return False
        changed = False
        for found in self._notice_acts():
            if found.data["status"] != "draft" or ("approve", found.id, found.version, yes.id) in self._tried:
                continue
            view = self.store.read()
            try:
                apply_for_reminders(
                    self.store,
                    self.cfg,
                    {
                        "op": "act.approve",
                        "id": found.id,
                        "fingerprint": acts.current_fingerprint(view, self.store.plugins, found.data)[0],
                        "by_standing": yes.id,
                    },
                    "A notice approved under your standing yes",
                    standing=True,
                )
                changed = True
            except StoreError as err:
                self._tried.add(("approve", found.id, found.version, yes.id))
                log.info("The notice act %s waits for the person's own yes: %s", found.id, err)
        return changed

    def send(self) -> bool:
        """Send each notice act the standing yes approved. The publisher recomputes what the yes covered first."""
        changed = False
        for found in self._notice_acts():
            approval = found.data.get("approved") or {}
            if found.data["status"] != "approved" or not approval.get("standing_yes"):
                continue
            try:
                self.publisher.send(found.id)
                changed = True
            except StoreError as err:
                log.warning("Couldn't send the notice act %s: %s", found.id, err)
        return changed

    # ---- Send me a test ----------------------------------------------------------------------------------------------

    def send_test(self) -> str:
        """The test the person asked for, through the same path as a notice: drafted, approved under the yes and sent.
        Works with notices off, so it can be tried first. Returns the act's id. Raises `StoreError` in plain words when
        there is no standing yes, it is stale, or the act can't be drafted or approved."""
        view = self.store.read()
        people = People(self.store, self.cfg)
        found = standing_yes.active(view, standing_yes.NOTICE)
        if found is None:
            raise StoreError("Choose where notices go by mail first, and say yes to it.")
        if stale := standing_yes.stale_reasons(self.store, self.cfg, view, people, found):
            raise StoreError("That choice is out of date (" + ", ".join(stale) + "). Choose it again.")
        if people.pm is None:
            raise StoreError("There is no person to send the test to.")
        cs = self._draft_act(found, people.pm, count=0, titles=[], test=True)
        act_id = next(
            r["id"]
            for o in self.store.read().get("changeset", cs).data["ops"]
            for r in o.get("records") or []
            if r["kind"] == "act"
        )
        self._tried.discard(("approve", act_id))
        drafted = self.store.read().get("act", act_id)
        apply_for_reminders(
            self.store,
            self.cfg,
            {
                "op": "act.approve",
                "id": act_id,
                "fingerprint": acts.current_fingerprint(self.store.read(), self.store.plugins, drafted.data)[0],
                "by_standing": found.id,
            },
            "A test notice approved under your standing yes",
            standing=True,
        )
        self.publisher.send(act_id)
        return act_id
