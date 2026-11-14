"""The person's standing yes for reminders (design 6.12).

A standing yes lets the engine approve one narrow kind of act without a click on each: a reminder that goes only to the
person themselves, on the one account they chose (a message to their own address, or an event with an alarm on that
account's own calendar), rendered from the core's reminder template at the version they saw. (A reminder in the app's
own calendar is local data, no act, and needs none.)
Everything it may cover is checked here, in `approval_problem`, which the applier's `act-approval` invariant calls: not
in the code that asks. Anything the checks don't find exactly as the yes recorded it is refused, and the act waits for
the person's own yes like any other.

Only the person's own `standing_yes.give` and `standing_yes.end` change it; no rule, input, assistant or add-on can.
The yes goes stale, and stops approving, when the template's version, the account's acting switch, the person's own
address, the person themselves or the account's channel changes."""

from __future__ import annotations

from typing import Any

from engine import act_accounts, notice_content, notice_template, reminder_content, reminder_template
from engine.ops import ActDraftOp, StandingYesEndOp, StandingYesGiveOp
from engine.storage import StoreError, WriteContext
from engine.storage.store import Tx

#: The reasons a standing yes goes stale, as codes the screens word.
STALE = ("template", "acting", "address", "person", "channel")


def _number(record_id: str) -> int:
    return int(record_id.rpartition("-")[2])


#: The form of the standing yes for notices by mail (design 7.19); the others (mail, calendar) are for reminders.
NOTICE = "notice"


def active(view: Any, form: str | None = None) -> Any | None:
    """The standing yes that stands now (not ended), the latest when there are several; None when there is none. With no
    `form` it is the one for reminders; with `form="notice"`, the one for notices. Each kind stands on its own."""
    found = [
        y
        for y in view.list("standing_yes")
        if not y.data.get("ended_at") and (y.data["form"] == NOTICE) == (form == NOTICE)
    ]
    return max(found, key=lambda y: _number(y.id)) if found else None


def stale_reasons(store: Any, cfg: Any, view: Any, people: Any, yes: Any) -> list[str]:
    """What changed since the person said yes, as codes (`STALE`): the reminder template's version, acting turned off
    for the account, the person's own address (mail), who the person is, or the account's channel no longer carrying
    that form. Empty while it all still holds."""
    data = yes.data
    why: list[str] = []
    notice = data["form"] == NOTICE
    template = notice_template if notice else reminder_template
    if data["template"]["version"] != template.version(reminder_content.root_of(store)):
        why.append("template")
    if not act_accounts.acting_on(cfg, data["account"]):
        why.append("acting")
    if data["form"] == "mail" and reminder_content.own_address(view, data["person"]) != (data.get("address") or ""):
        why.append("address")
    if notice and (data.get("address") or "") not in notice_content.own_addresses(view, data["person"]):
        why.append("address")
    if people.pm != data["person"]:
        why.append("person")
    if (
        reminder_content.channel_for(store.plugins, data["account"], "mail" if notice else data["form"])
        != data["channel"]
    ):
        why.append("channel")
    return why


def _same_instant(a: Any, b: Any) -> bool:
    try:
        return reminder_content.instant(a) == reminder_content.instant(b)
    except (TypeError, ValueError):
        return False


def _reminder_problem(
    store: Any,
    cfg: Any,
    view: Any,
    data: Any,
    *,
    form: str,
    account: str,
    channel: str,
    person: str,
    address: str | None,
    template: dict[str, str] | None,
) -> str | None:
    """Why this act is not exactly the reminder the engine would draft for its to-do: the one rule both the draft and
    the standing yes use. None when it is."""
    action = view.get("action", data["reminder"]) if data.get("reminder") else None
    if action is None:
        return "the to-do this reminds the person of isn't there"
    if action.data.get("status") != "open" or not action.data.get("remind_at"):
        return "the to-do this reminds the person of has no reminder waiting"
    if not _same_instant(action.data["remind_at"], data.get("reminder_at")):
        return "the to-do's reminder time is different now"
    try:
        exp = reminder_content.expected(
            store,
            cfg,
            view,
            action,
            data["reminder_at"],
            form=form,
            account=account,
            channel=channel,
            person=person,
            address=address,
        )
    except reminder_template.TemplateError as err:
        return str(err)
    if data["channel"] != exp.channel or not act_accounts.same(data.get("account") or "", exp.account):
        return "it doesn't go through the channel and account the reminder was set up for"
    stored = data.get("template") or {}
    if stored != exp.template or (template is not None and template != exp.template):
        return "it isn't made from the reminder template at the version in force"
    if data.get("in_reply_to") or data.get("sources"):
        return "a reminder draws on nothing but its own to-do"
    target = data["target"]
    wanted = exp.target
    if target["kind"] != wanted["kind"] or (target.get("action") or "") != wanted["action"]:
        return "it doesn't do what a reminder does"
    if target.get("about") or target.get("folder") or target.get("label") or target.get("when"):
        return "it is about something other than the reminder"
    if target.get("answer") or target.get("proposed_start") or target.get("proposed_end"):
        return "it is about something other than the reminder"
    if form == "mail":
        got = target.get("recipients") or []
        want = wanted["recipients"][0]
        if len(got) != 1:
            return "a reminder goes to the person alone"
        r = got[0]
        if (
            r.get("person") != want["person"]
            or r.get("role") != "to"
            or (r.get("kind") or "") != want["kind"]
            or str(r.get("address", "")).strip().lower() != str(want["address"]).strip().lower()
            or r.get("from_text")
            or r.get("called_out")
        ):
            return "a reminder goes only to the person's own address"
        if any(target.get(k) for k in ("calendar", "start", "end", "title")) or target.get("alarm_minutes") is not None:
            return "a reminder mail has no event fields"
    else:
        if target.get("recipients"):
            return "a reminder event has no attendees"
        if target.get("calendar") != wanted["calendar"] or target.get("title") != wanted["title"]:
            return "a reminder event goes on the account's own calendar with the reminder's title"
        if not _same_instant(target.get("start"), wanted["start"]) or not _same_instant(
            target.get("end"), wanted["end"]
        ):
            return "a reminder event is at the reminder time"
        if target.get("alarm_minutes") != wanted["alarm_minutes"]:
            return "a reminder event has its alarm at the reminder time"
    if dict(data.get("parts") or {}) != exp.parts:
        return "its words are not the reminder template rendered for this to-do"
    return None


def _notice_problem(
    store: Any,
    cfg: Any,
    view: Any,
    data: Any,
    *,
    account: str,
    channel: str,
    person: str,
    address: str,
    template: dict[str, str] | None,
) -> str | None:
    """Why this act is not exactly the notice the engine would draft: the one rule both the draft and the standing yes
    use. It names what it was drafted from, shows titles only at a level the person allowed (never restricted), and is
    the notice template rendered for that, to the one address, with nothing else about it. None when it is."""
    found = data.get("notice")
    if not found:
        return "a notice names what it was drafted from"
    titles = [dict(t) for t in found.get("titles") or []]
    if found.get("test") and (titles or found.get("count")):
        return "the test says nothing about what waits"
    for title in titles:
        if not notice_content.title_allowed(cfg, title["level"]):
            return "a title is in it that the person didn't allow for its data level"
    try:
        exp = notice_content.expected(
            store,
            cfg,
            account=account,
            channel=channel,
            person=person,
            address=address,
            count=int(found["count"]),
            titles=titles,
            test=bool(found.get("test")),
        )
    except notice_template.TemplateError as err:
        return str(err)
    if data["channel"] != exp.channel or not act_accounts.same(data.get("account") or "", exp.account):
        return "it doesn't go through the channel and account the notice was set up for"
    stored = data.get("template") or {}
    if stored != exp.template or (template is not None and template != exp.template):
        return "it isn't made from the notice template at the version in force"
    if data.get("in_reply_to") or data.get("sources") or data.get("reminder"):
        return "a notice draws on nothing but what waits"
    target = data["target"]
    if target["kind"] != "message" or (target.get("action") or "") != "send":
        return "it doesn't do what a notice does"
    for key in ("about", "folder", "label", "when", "calendar", "start", "end", "title", "answer"):
        if target.get(key):
            return "it is about something other than the notice"
    if target.get("alarm_minutes") is not None or target.get("proposed_start") or target.get("proposed_end"):
        return "it is about something other than the notice"
    got = target.get("recipients") or []
    if len(got) != 1:
        return "a notice goes to the person alone"
    r = got[0]
    if (
        r.get("person") != person
        or r.get("role") != "to"
        or (r.get("kind") or "") != notice_content.ADDRESS_KIND
        or str(r.get("address", "")).strip().lower() != address.strip().lower()
        or r.get("from_text")
        or r.get("called_out")
    ):
        return "a notice goes only to the address the person chose"
    if dict(data.get("parts") or {}) != exp.parts:
        return "its words are not the notice template rendered for what waits"
    return None


def approval_problem(store: Any, cfg: Any, view: Any, people: Any, act: Any, yes_id: str | None) -> str | None:
    """Why the engine may not approve this act under the standing yes: it must stand and not be stale, and the act must
    be a reminder the engine made, through the yes's channel and account, to the person's own address as the yes
    recorded it (mail) or the account's own calendar with no attendee (event), from the template at the yes's version,
    with exactly the template's words and alarm. A standing yes for notices covers only a notice the engine made, to
    the one address the person chose, with exactly the notice template's words. None when every one of these holds."""
    yes = view.get("standing_yes", yes_id) if yes_id else None
    if yes is None:
        return "there is no such standing yes"
    if yes.data.get("ended_at"):
        return "that standing yes has ended"
    if stale := stale_reasons(store, cfg, view, people, yes):
        return "the standing yes is stale (" + ", ".join(stale) + "): look at reminders again"
    if act is None:
        return "there is no such act"
    data = act.data
    y = yes.data
    if y["form"] == NOTICE:
        if data.get("made_by") != "notices" or not data.get("notice"):
            return "this standing yes covers only a notice the engine made"
        return _notice_problem(
            store,
            cfg,
            view,
            data,
            account=y["account"],
            channel=y["channel"],
            person=y["person"],
            address=y.get("address") or "",
            template=dict(y["template"]),
        )
    if data.get("made_by") != "reminders" or not data.get("reminder"):
        return "a standing yes covers only a reminder the engine made"
    return _reminder_problem(
        store,
        cfg,
        view,
        data,
        form=y["form"],
        account=y["account"],
        channel=y["channel"],
        person=y["person"],
        address=y.get("address"),
        template=dict(y["template"]),
    )


def draft_problem(store: Any, cfg: Any, view: Any, people: Any, actor: str, op: ActDraftOp) -> str | None:
    """Why a draft that carries `reminder` (or any draft the engine's reminders make) is refused: only the engine's own
    reminders draft one, and it must be exactly the reminder for a to-do whose reminder is due, on the account the
    person set reminders up for. None for an ordinary draft, and for a reminder draft that holds."""
    if op.reminder is None and op.notice is None and actor != "reminders":
        return None
    if op.reminder is not None and op.notice is not None:
        return "a draft is a reminder or a notice, never both"
    if actor != "reminders":
        return "only the engine's own reminders and notices draft those acts"
    if op.reminder is None and op.notice is None:
        return "the engine's reminders and notices draft only their own acts"
    if op.notice is not None:
        return _notice_draft_problem(store, cfg, view, people, op)
    where = cfg.steward.reminders
    if where.where not in reminder_content.FORMS or not where.where_account:
        return "reminders aren't set up to go to an account"
    person = people.pm
    if person is None:
        return "there is no person to remind"
    account = where.where_account
    if not act_accounts.acting_on(cfg, account):
        return "acting is off for the account reminders go through"
    channel = reminder_content.channel_for(store.plugins, account, where.where)
    if channel is None:
        return "that account can't carry a reminder in that form"
    address = reminder_content.own_address(view, person) if where.where == "mail" else None
    if where.where == "mail" and not address:
        return "there is no address of the person's own to send to"
    stand = {
        "reminder": op.reminder.action,
        "reminder_at": op.reminder.at,
        "channel": op.channel,
        "account": (op.account or ""),
        "template": op.template.model_dump(mode="json") if op.template else None,
        "sources": list(op.sources),
        "in_reply_to": op.in_reply_to,
        "parts": dict(op.parts),
        "target": _resolved_target(op, person, address),
    }
    return _reminder_problem(
        store,
        cfg,
        view,
        stand,
        form=where.where,
        account=account,
        channel=channel,
        person=person,
        address=address,
        template=None,
    )


def _notice_draft_problem(store: Any, cfg: Any, view: Any, people: Any, op: ActDraftOp) -> str | None:
    """Why a notice draft is refused: there must be a standing yes for notices that stands, and the draft must be
    exactly the notice for the account and address it names, which the person chose."""
    yes = active(view, NOTICE)
    if yes is None:
        return "no standing yes for notices stands"
    if stale := stale_reasons(store, cfg, view, people, yes):
        return "the standing yes for notices is stale (" + ", ".join(stale) + ")"
    person = people.pm
    if person is None or person != yes.data["person"]:
        return "there is no person to send the notice to"
    address = yes.data.get("address") or ""
    stand = {
        "notice": op.notice.model_dump(mode="json") if op.notice else None,
        "reminder": None,
        "channel": op.channel,
        "account": (op.account or ""),
        "template": op.template.model_dump(mode="json") if op.template else None,
        "sources": list(op.sources),
        "in_reply_to": op.in_reply_to,
        "parts": dict(op.parts),
        "target": _resolved_target(op, person, address),
    }
    return _notice_problem(
        store,
        cfg,
        view,
        stand,
        account=yes.data["account"],
        channel=yes.data["channel"],
        person=person,
        address=address,
        template=None,
    )


def _resolved_target(op: ActDraftOp, person: str, address: str | None) -> dict[str, Any]:
    """A draft's target as an act keeps it, enough for the same checks: a recipient who is a known person is stored with
    their address and way of reaching them."""
    t = op.target
    recipients = []
    for r in t.recipients:
        known = (r.person or "").strip() == person
        recipients.append(
            {
                "person": person if known else None,
                "address": (address or "") if known else (r.address or ""),
                "kind": r.kind,
                "role": r.role,
                "from_text": r.from_text,
                "called_out": r.called_out,
            }
        )
    return {
        "kind": t.kind,
        "action": t.what,
        "recipients": recipients,
        "about": list(t.about),
        "calendar": t.calendar,
        "when": t.when,
        "folder": t.folder,
        "label": t.label,
        "start": t.start,
        "end": t.end,
        "title": t.title,
        "alarm_minutes": t.alarm_minutes,
        "answer": t.answer,
        "proposed_start": t.proposed_start,
        "proposed_end": t.proposed_end,
    }


# ---- the person's two ops -------------------------------------------------------------------------------------------


def _give(tx: Tx, op: StandingYesGiveOp, ctx: Any, w: WriteContext) -> list[dict[str, Any]]:
    person = ctx.people.pm
    if person is None:
        raise StoreError("there is no person to give a standing yes as")
    if active(tx, op.form) is not None:
        raise StoreError(
            "a standing yes for notices already stands: end it first"
            if op.form == NOTICE
            else "a standing yes for reminders already stands: end it first"
        )
    if op.form != NOTICE and op.address is not None:
        raise StoreError("an address is for a notice; a reminder goes to the address on your record")
    known = act_accounts.known(ctx.store, ctx.cfg)
    if not any(act_accounts.same(a.id, op.account) for a in known):
        raise StoreError("that isn't an account the assistant can act on")
    if not act_accounts.acting_on(ctx.cfg, op.account):
        raise StoreError("turn on Let the assistant act after your yes for that account first")
    channel = reminder_content.channel_for(ctx.store.plugins, op.account, "mail" if op.form == NOTICE else op.form)
    if channel is None:
        raise StoreError(
            "that account can't send mail"
            if op.form == NOTICE
            else f"that account can't carry a reminder as {'an event' if op.form == 'calendar' else 'a message'}"
        )
    root = reminder_content.root_of(ctx.store)
    if op.form == NOTICE:
        now = notice_template.version(root)
        if op.template_version != now:
            raise StoreError("the notice changed since you looked at it; look at it again")
        address = (op.address or "").strip().lower()
        if address not in notice_content.own_addresses(tx, person):
            raise StoreError("pick one of the addresses on your own record to send notices to")
    else:
        now = reminder_template.version(root)
        if op.template_version != now:
            raise StoreError("the reminder changed since you looked at it; look at it again")
        address = reminder_content.own_address(tx, person) if op.form == "mail" else None
        if op.form == "mail" and not address:
            raise StoreError("you have no email address on file to send reminders to")
    made = tx.create(
        "standing_yes",
        {
            "person": person,
            "account": op.account,
            "channel": channel,
            "form": op.form,
            "address": address,
            "template": {"name": notice_template.NAME if op.form == NOTICE else reminder_template.NAME, "version": now},
            "given_at": ctx.store.clock(),
            "ended_at": None,
        },
        w,
    )
    return [{"kind": "standing_yes", "id": made.id}]


def _end(tx: Tx, op: StandingYesEndOp, ctx: Any, w: WriteContext) -> list[dict[str, Any]]:
    found = tx.get("standing_yes", op.id)
    if found is None:
        raise StoreError(f"standing yes {op.id} doesn't exist")
    if found.data.get("ended_at"):
        raise StoreError("that standing yes has already ended")
    tx.update("standing_yes", found.id, {"ended_at": ctx.store.clock()}, w, read_version=found.version)
    return [{"kind": "standing_yes", "id": found.id}]


def apply(tx: Tx, op: Any, ctx: Any, w: WriteContext) -> list[dict[str, Any]]:
    """Apply the person's `standing_yes.give` or `standing_yes.end` in the applier's transaction."""
    if isinstance(op, StandingYesGiveOp):
        return _give(tx, op, ctx, w)
    return _end(tx, op, ctx, w)
