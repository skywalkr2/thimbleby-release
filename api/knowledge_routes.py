"""API routes for what the assistant learned (design 6.22): the entries, and the person's own acts on them. Keep makes a
proposal active with the person as its author, Discard keeps it with the reason, Retire ends an active entry. Each acts
at once, with Undo through the change it makes, and records a signal (6.20)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from api.schemas import (
    Applied,
    CatchUpStarted,
    CatchUpView,
    KnowledgeDiscard,
    KnowledgeGuesses,
    KnowledgeKeep,
    KnowledgeNarrow,
    KnowledgeTermAdd,
    KnowledgeView,
    LearnedLine,
    LearnedTodayView,
    LearnedView,
    Ok,
    OverlapView,
    PersonOfferView,
    ProposalsView,
    ProposalView,
    ReadVersion,
    RuleReviewPutOff,
    RuleReviewRule,
    RuleReviewView,
    RuleView,
)
from engine import catch_up, contact_tally, knowledge, knowledge_use, person_look, proposals
from engine import learned as card_learning
from engine.applier import apply_as_person
from engine.config import Config
from engine.dispatcher import SAY_WHO_FIRST, signal
from engine.origin import origins
from engine.records import Rule, Scope
from engine.references import join_scope
from engine.rule_review import due, review, take_back_not_now
from engine.storage import Store, StoreError
from engine.storage.store import CONFLICT_WORDS
from engine.today import local_day, zone
from engine.worker import Events, Worker

#: The reason kept on an entry the person said was wrong.
WRONG_REASON = "Said to be wrong"
Kind = Literal["lesson", "glossary_entry", "routing_entry", "style_note"]
Status = Literal["proposed", "active", "discarded", "expired", "retired"]


def _use(uses: dict[str, knowledge_use.Use], entry_id: str) -> dict[str, Any]:
    found = uses.get(entry_id, knowledge_use.Use())
    return {"used": found.used, "given": found.given, "last_used": found.last_used}


def _view(
    stored: Any,
    origin: dict[str, Any] | None,
    uses: dict[str, knowledge_use.Use],
    messages: int = 0,
    asks: bool = False,
) -> KnowledgeView:
    data = dict(stored.data)
    own = {name: data.get(name) for names in knowledge.OWN_FIELDS.values() for name in names}
    return KnowledgeView(
        id=stored.id,
        kind=stored.kind,
        version=stored.version,
        text=data["text"],
        status=data["status"],
        learned_from=data["origin"],
        pack=data.get("pack"),
        trust=data["trust"],
        learned_at=data["learned_at"],
        kept_by=data.get("kept_by"),
        kept_at=data.get("kept_at"),
        discard_reason=data.get("discard_reason"),
        applies_to=data["applies_to"],
        evidence=data.get("evidence"),
        origin=origin,
        activated=data.get("activated"),
        messages=messages,
        asks=asks,
        **_use(uses, stored.id),
        **{
            name: value
            for name, value in own.items()
            if name in knowledge.OWN_FIELDS[stored.kind] and (value is not None or name == "negative")
        },
    )


def _standing(view: Any, stored: Any) -> tuple[int, bool]:
    """How many different messages an entry was seen in, and whether a proposed entry is a question for the person."""
    data = stored.data
    asks = data["status"] == "proposed" and proposals.needs_answer(
        proposals.Proposal(stored.kind, stored, proposals.tag_of(view, stored.kind, stored))
    )
    return proposals.corroboration(view, data), asks


def _rule(stored: Any, origin: dict[str, Any] | None, uses: dict[str, knowledge_use.Use]) -> RuleView:
    data = dict(stored.data)
    return RuleView(
        id=stored.id,
        version=stored.version,
        name=data["name"],
        text=data.get("text") or "",
        status=data["status"],
        learned_from=data["origin"],
        trust=data.get("trust", "trusted"),
        learned_at=data.get("learned_at"),
        kept_by=data.get("kept_by"),
        kept_at=data.get("kept_at"),
        discard_reason=data.get("discard_reason"),
        applies_to=Scope.model_validate(data.get("applies_to") or {}),
        constrains=list(data.get("constrains") or []),
        enforced=bool(data.get("check")),
        evidence=data.get("evidence"),
        origin=origin,
        **_use(uses, stored.id),
    )


def _proposal(
    view: Any,
    found: proposals.Proposal,
    origin: dict[str, Any] | None,
    batch: str,
    settings: Any,
) -> ProposalView:
    stored = found.stored
    data = dict(stored.data)
    own = {name: data.get(name) for name in knowledge.OWN_FIELDS.get(found.kind, ())}
    learned = data.get("learned_at")
    expires = (
        proposals.at_of(learned) + timedelta(days=settings.proposals_expire_days)
        if found.came_from == proposals.FROM_INPUT and learned
        else None
    )
    twin = proposals.duplicate_of(view, found.kind, data, own_id=stored.id)
    return ProposalView(
        id=stored.id,
        kind=found.kind,
        version=stored.version,
        text=data["text"],
        name=data.get("name") if found.kind == "rule" else None,
        status=data["status"],
        learned_from=data["origin"],
        pack=data.get("pack"),
        trust=data.get("trust", "trusted"),
        learned_at=learned,
        kept_by=data.get("kept_by"),
        kept_at=data.get("kept_at"),
        discard_reason=data.get("discard_reason"),
        applies_to=data["applies_to"],
        evidence=data.get("evidence"),
        more_evidence=data.get("more_evidence") or [],
        origin=origin,
        came_from=found.came_from,
        batch=batch,
        just_this_time_before=proposals.just_this_time_before(view, found.kind, data, own_id=stored.id),
        overlaps_with=(
            OverlapView(id=twin.id, kind=found.kind, text=twin.data["text"], status=twin.data["status"])
            if twin is not None
            else None
        ),
        expires_at=expires,
        from_changeset=card_learning.changeset_of_entry(view, stored),
        activated=data.get("activated"),
        messages=proposals.corroboration(view, data),
        asks=True,
        **{name: value for name, value in own.items() if value is not None or name == "negative"},
    )


def build_knowledge_router(cfg: Config, store: Store, events: Events, worker: Worker) -> APIRouter:
    r = APIRouter(prefix="/api")

    def entry(entry_id: str, read_version: int, *, rules: bool = True) -> Any:
        kind = knowledge.kind_of(entry_id) or ("rule" if rules and entry_id.startswith(f"{Rule.prefix}-") else None)
        found = store.read().get(kind, entry_id) if kind else None
        if found is None:
            raise HTTPException(status_code=404, detail=f"{entry_id} doesn't exist")
        if found.version != read_version:
            raise HTTPException(status_code=409, detail=CONFLICT_WORDS)
        return found

    def act(found: Any, op: dict[str, Any], summary: str, kind: str) -> Applied:
        try:
            changeset = apply_as_person(store, cfg, [op], summary)
        except (StoreError, ValueError) as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        signal(store, kind, [found.id])
        events.changed()
        return Applied(changeset=changeset)

    def edit(found: Any, fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "op": "record.edit",
            "record": {"kind": found.kind, "id": found.id},
            "fields": fields,
            "read_version": found.version,
        }

    @r.get("/knowledge")
    def entries(kind: Kind | None = None, status: Status | None = None) -> list[KnowledgeView]:
        """What the assistant learned, newest first, with where each piece came from; filter by kind and by status."""
        view = store.read()
        uses = knowledge_use.use_of(view)
        found = []
        for name in [kind] if kind else knowledge.KINDS:
            links = origins(view, name, [s.id for s in view.list(name)])
            found += [(s, links.get(s.id)) for s in view.list(name) if status is None or s.data["status"] == status]
        found.sort(key=lambda pair: (pair[0].data["learned_at"], pair[0].id), reverse=True)
        return [_view(stored, link, uses, *_standing(view, stored)) for stored, link in found]

    @r.get("/knowledge/rules")
    def rules(status: Status | None = None) -> list[RuleView]:
        """The standing rules, newest first, each with where it came from, what it applies to and constrains, and how
        much the runs used it; filter by status."""
        view = store.read()
        uses = knowledge_use.use_of(view)
        found = [s for s in view.list("rule") if status is None or s.data["status"] == status]
        found.sort(key=lambda s: (str(s.data.get("learned_at") or ""), s.id), reverse=True)
        links = origins(view, "rule", [s.id for s in found])
        return [_rule(stored, links.get(stored.id), uses) for stored in found]

    @r.post("/knowledge/{entry_id}/keep")
    def keep(entry_id: str, body: KnowledgeKeep) -> Applied:
        """Keep a proposed entry: it becomes active, and the person is its author, with the wording or target they
        changed here. Undo puts it back to proposed."""
        found = entry(entry_id, body.read_version)
        person = cfg.workspace.user.person
        if person is None:
            raise HTTPException(status_code=409, detail=SAY_WHO_FIRST)
        try:
            fields = knowledge.keep_fields(
                found,
                person,
                store.clock(),
                text=body.text,
                applies_to=join_scope(
                    store.read(), body.applies_to.model_dump(mode="json", by_alias=True), store.plugins.references()
                )
                if body.applies_to is not None
                else None,
            )
        except StoreError as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        return act(found, edit(found, fields), "Kept what was learned", "kept")

    @r.post("/knowledge/terms")
    def add_term(body: KnowledgeTermAdd) -> Applied:
        """Add a word of the person's own with its meaning: an active glossary entry in their words, with Undo."""
        term = " ".join(body.term.split())
        meaning = " ".join(body.meaning.split())
        if not term or not meaning:
            raise HTTPException(status_code=422, detail="A word needs its meaning.")
        op = {
            "op": "glossary.add",
            "text": f"{term}: {meaning}",
            "term": term,
            "meaning": meaning,
            "confidence": "confirmed",
        }
        try:
            changeset = apply_as_person(store, cfg, [op], "Added a word to the glossary")
        except (StoreError, ValueError) as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        events.changed()
        return Applied(changeset=changeset)

    @r.post("/knowledge/{entry_id}/discard")
    def discard(entry_id: str, body: KnowledgeDiscard) -> Applied:
        """Discard a proposed entry. It is kept, with the reason if one is given. Undo puts it back to proposed."""
        found = entry(entry_id, body.read_version)
        try:
            fields = knowledge.discard_fields(found, body.reason)
        except StoreError as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        return act(found, edit(found, fields), "Discarded what was learned", "discarded")

    @r.get("/knowledge/{entry_id}/guesses")
    def guesses(entry_id: str) -> KnowledgeGuesses:
        """How many open to-dos still carry a guess this entry made, for "Take back its guesses" beside its discard."""
        with store.read_scope():
            return KnowledgeGuesses(entry=entry_id, count=len(knowledge.guessed_by(store.read(), entry_id)))

    @r.post("/knowledge/{entry_id}/take-back-guesses")
    def take_back_guesses(entry_id: str) -> Applied:
        """Take back every guess the entry made at once: each open to-do it marked gets the owners it would have had
        and loses the mark, as one change with one Undo. It teaches nothing new: discarding the entry already did."""
        with store.read_scope():
            marked = knowledge.guessed_by(store.read(), entry_id)
        if not marked:
            raise HTTPException(status_code=409, detail="there are no guesses of this entry to take back")
        ops = [{"op": "action.owners", "id": a.id, "owners": a.data["by_kind"]["owners_before"]} for a in marked]
        try:
            done = apply_as_person(
                store, cfg, ops, "Took back what was guessed", all_or_nothing=True, corrections=False
            )
        except (StoreError, ValueError) as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        events.changed()
        return Applied(changeset=done)

    @r.post("/knowledge/{entry_id}/reuse")
    def reuse(entry_id: str, body: ReadVersion) -> Applied:
        """Bring a retired or set-aside entry or standing rule back into use, as the person's own Keep. Undo puts it
        back as it was."""
        found = entry(entry_id, body.read_version, rules=True)
        person = cfg.workspace.user.person
        if person is None:
            raise HTTPException(status_code=409, detail=SAY_WHO_FIRST)
        try:
            fields = knowledge.reuse_fields(found, person, store.clock())
        except StoreError as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        return act(found, edit(found, fields), "Brought back what was learned", "kept")

    @r.post("/knowledge/{entry_id}/retire")
    def retire(entry_id: str, body: ReadVersion) -> Applied:
        """Retire an active entry or standing rule: it stops guiding runs and stays on record, with the same `retired`
        signal for both. Undo makes it active again."""
        found = entry(entry_id, body.read_version, rules=True)
        op = "rule.retire" if found.kind == "rule" else "knowledge.retire"
        return act(found, {"op": op, "id": found.id}, "Retired what was learned", "retired")

    def views(view: Any, found: list[proposals.Proposal], batch: str) -> list[ProposalView]:
        links = {kind: origins(view, kind, [p.stored.id for p in found if p.kind == kind]) for kind in proposals.KINDS}
        return [_proposal(view, p, links[p.kind].get(p.stored.id), batch, cfg.dispatch.knowledge) for p in found]

    def person_offers() -> list[PersonOfferView]:
        view = store.read()
        served = {c.address: c.sides for c in contact_tally.tally(store, cfg)}
        out = []
        for o in person_look.waiting_offers(store):
            names = [str(p.data["name"]) for s in served.get(o.data["address"], ()) if (p := view.get("project", s))]
            out.append(
                PersonOfferView(
                    id=o.id,
                    version=o.version,
                    name=o.data["name"],
                    address=o.data["address"],
                    why=o.data["why"],
                    relation=o.data.get("relation"),
                    sides=names,
                    count=o.data["from_them"] + o.data["to_them"],
                )
            )
        return out

    @r.post("/knowledge/people/{offer_id}/keep")
    def keep_person(offer_id: str) -> Applied:
        """Keep someone the assistant offered: they are added to the people on file with the relation the offer gave and
        the sides of the accounts their mail came from, and the offer is settled, in one change that Undo takes back."""
        try:
            changeset = person_look.keep(store, cfg, offer_id)
        except (StoreError, ValueError) as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        events.changed()
        return Applied(changeset=changeset)

    @r.post("/knowledge/people/{offer_id}/not-this-one")
    def leave_person_out(offer_id: str) -> Applied:
        """ "Not this one": the offer is left out, never made again, and a signal records it; Undo puts it back."""
        changeset = person_look.dismiss(store, cfg, offer_id)
        if changeset is None:
            raise HTTPException(status_code=409, detail="That offer no longer stands.")
        events.changed()
        return Applied(changeset=changeset)

    @r.get("/knowledge/proposals")
    def waiting_proposals() -> ProposalsView:
        """What the assistant learned that waits for the person, oldest first, each tagged by where it came from
        (an input or one of the person's corrections) with its evidence and what it applies to. The catch-up list is
        separate."""
        view = store.read()
        listed = catch_up.proposal_ids(view, catch_up.load(store))
        found = [
            p
            for p in proposals.proposals(view, alike=cfg.dispatch.knowledge.discard_similarity)
            if p.stored.id not in listed
        ]
        origins_count: dict[str, int] = {}
        for p in found:
            origins_count[p.came_from] = origins_count.get(p.came_from, 0) + 1
        return ProposalsView(
            people=person_offers(),
            proposals=views(view, found, "daily"),
            origins=origins_count,
            expired=proposals.expired_since(view, proposals.last_reviewed(view)),
            tentative=len(proposals.tentative(view, alike=cfg.dispatch.knowledge.discard_similarity)),
        )

    @r.get("/knowledge/learned-today")
    def learned_today() -> LearnedTodayView:
        """What the assistant learned on its own today: entries made active with no Keep, from the person's typed words,
        a correction or agreeing messages, newest first, with what each means and how many messages it was seen in."""
        view = store.read()
        uses = knowledge_use.use_of(view)
        today = local_day(worker.now(), zone(cfg))
        found = []
        for name in knowledge.KINDS:
            for s in view.list(name):
                kept = s.data.get("kept_at")
                if (
                    s.data["status"] == "active"
                    and s.data.get("activated")
                    and kept
                    and local_day(proposals.at_of(kept), zone(cfg)) == today
                ):
                    found.append(s)
        found.sort(key=lambda s: (str(s.data["kept_at"]), s.id), reverse=True)
        out = []
        for s in found:
            links = origins(view, s.kind, [s.id])
            out.append(_view(s, links.get(s.id), uses, proposals.corroboration(view, s.data)))
        return LearnedTodayView(count=len(out), items=out)

    @r.post("/knowledge/{entry_id}/wrong")
    def wrong(entry_id: str, body: ReadVersion) -> Applied:
        """ "That's wrong" on something the assistant uses: it stops at once, is kept as set aside with that reason so a
        close suggestion is not made again, and a `discarded` signal records the correction. Undo makes it active
        again. A standing rule is retired the way Stop using does it."""
        found = entry(entry_id, body.read_version, rules=True)
        if found.data["status"] != "active":
            raise HTTPException(status_code=409, detail="That isn't in use.")
        if found.kind == "rule":
            return act(found, {"op": "rule.retire", "id": found.id}, "Said what was learned is wrong", "retired")
        fields = {"status": "discarded", "discard_reason": WRONG_REASON}
        return act(found, edit(found, fields), "Said what was learned is wrong", "discarded")

    @r.get("/knowledge/learned")
    def learned_lines() -> LearnedView:
        """What the assistant is learning or has learned from each correction that has something to show, for the line
        under that correction's card: still being learned (with why it waits), a proposal to keep, or the person's own
        words already kept, with the change that undoes them. What the catch-up list holds is left out."""
        view = store.read()
        hidden = catch_up.proposal_ids(view, catch_up.load(store))
        out: list[LearnedLine] = []
        for line in card_learning.lines(view, hidden=hidden):
            signal_data = view.get("signal", line.signal).data
            proposal = None
            if line.entry is not None:
                kind = line.kind or ""
                found = proposals.Proposal(kind, line.entry, proposals.tag_of(view, kind, line.entry))
                proposal = views(view, [found], "daily")[0]
            out.append(
                LearnedLine(
                    signal=line.signal,
                    kind=signal_data["kind"],
                    changeset=signal_data.get("changeset"),
                    refs=list(signal_data.get("refs") or []),
                    state=line.state,
                    waiting=line.waiting,
                    proposal=proposal,
                    undo=line.undo,
                )
            )
        return LearnedView(lines=out)

    @r.get("/knowledge/catch-up")
    def catch_up_list() -> CatchUpView:
        """What the assistant learned from corrections made before it could learn from them: one list, the most
        repeated kinds of correction first, cut at the configured number."""
        view = store.read()
        state = catch_up.load(store)
        listed = catch_up.proposal_ids(view, state)
        found = [
            p
            for p in proposals.proposals(view, alike=cfg.dispatch.knowledge.discard_similarity)
            if p.stored.id in listed
        ]
        return CatchUpView(
            proposals=views(view, found, "catch_up"),
            made_at=state.made_at if state is not None else None,
            waiting=len(catch_up.waiting(view, state)),
            left_out=state.left_out if state is not None else 0,
            most=cfg.dispatch.knowledge.catch_up_max,
        )

    @r.post("/knowledge/catch-up/go")
    def catch_up_go() -> CatchUpStarted:
        """The person's go for the learning runs held for the catch-up list: every one starts, and the list fills as
        they finish."""
        started = catch_up.grant_go(store)
        if started:
            worker.poke()
            events.changed()
        return CatchUpStarted(started=started)

    @r.post("/knowledge/{entry_id}/just-this-time")
    def just_this_time(entry_id: str, body: ReadVersion) -> Applied:
        """Set a proposal aside as right for this case but not a pattern: it is discarded with that as its reason,
        a `just_this_time` signal is recorded, and the same correction proposed again is shown with how many times
        this was said before. Undo puts it back to proposed."""
        found = entry(entry_id, body.read_version)
        try:
            fields = knowledge.just_this_time_fields(found)
        except StoreError as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        return act(found, edit(found, fields), "Set aside what was learned, just this time", "just_this_time")

    @r.get("/knowledge/rules/review")
    def rule_review() -> RuleReviewView:
        """The standing rules to look over: active rules given to runs over the review window and never shown to apply,
        most present first, with the size of what every run is sent and how many rules the latest run had moved out of
        it. A rule a code check enforces is never in the list."""
        view = store.read()
        now = worker.now()
        settings = cfg.dispatch.knowledge
        found = review(view, settings, now)
        return RuleReviewView(
            days=found.days,
            flagged=[
                RuleReviewRule(
                    id=f.id,
                    version=f.version,
                    name=f.name,
                    text=f.text,
                    applies_to=Scope.model_validate(f.applies_to),
                    present=f.present,
                    applied=f.applied,
                )
                for f in found.flagged
            ],
            stable_chars=found.stable_chars,
            stable_budget=found.stable_budget,
            moved=found.moved,
            due=due(view, settings, now, found),
        )

    @r.post("/knowledge/rules/review/not-now")
    def rule_review_not_now() -> RuleReviewPutOff:
        """ "Not now" on the rules review line: the line leaves Today for `knowledge.rule_review_every_days`, as it does
        when the person keeps, narrows or retires a rule, so the person never has to decide something to make it go
        away. It records a `not_now` signal naming the rules flagged, and changes no rule."""
        now = worker.now()
        settings = cfg.dispatch.knowledge
        flagged = review(store.read(), settings, now).flagged
        made = signal(store, "not_now", [f.id for f in flagged], now=now)
        events.changed()
        return RuleReviewPutOff(until=now + timedelta(days=settings.rule_review_every_days), signal=made)

    @r.post("/knowledge/rules/review/not-now/{signal_id}/undo")
    def rule_review_not_now_undo(signal_id: str) -> Ok:
        """Undo "Not now": the line is back on Today at once."""
        if not take_back_not_now(store, signal_id):
            raise HTTPException(status_code=404, detail='There is no "not now" to take back.')
        events.changed()
        return Ok(ok=signal_id)

    @r.post("/knowledge/{entry_id}/keep-rule")
    def keep_rule(entry_id: str, body: ReadVersion) -> Applied:
        """Keep a standing rule as it is in the review: the clock for its next review starts now. Undo puts the old
        clock back."""
        found = entry(entry_id, body.read_version, rules=True)
        if found.kind != "rule" or found.data["status"] != "active":
            raise HTTPException(status_code=409, detail=f"{entry_id} isn't an active rule")
        return act(found, edit(found, {"reviewed_at": store.clock()}), "Kept a standing rule", "kept")

    @r.post("/knowledge/{entry_id}/narrow")
    def narrow(entry_id: str, body: KnowledgeNarrow) -> Applied:
        """Narrow what an active rule or entry applies to. It is the person's own change of its scope, so Undo puts the
        old scope back."""
        found = entry(entry_id, body.read_version, rules=True)
        if found.data["status"] != "active":
            raise HTTPException(status_code=409, detail=f"{entry_id} isn't active")
        scope = body.applies_to.model_dump(mode="json", by_alias=True)
        return act(found, edit(found, {"applies_to": scope}), "Narrowed what was learned", "narrowed")

    return r
