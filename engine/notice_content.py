"""What a notice by mail says and where it goes (design 7.19): the one place that works out the exact notice act, so the
engine that drafts it and the invariant that lets the person's standing yes approve it read the same answer.

A notice act goes only to one of the person's own addresses, from a mail-capable account they chose, and says
exactly the core's notice template rendered: a count, and the titles of items only when the person allowed titles for
the item's data level (`ui.notifications.mail_titles_level`; restricted items never). Everything here reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine import notice_template, reminder_content
from engine.contacts import reach_lists

#: The kind of way of reaching a person the notice goes to.
ADDRESS_KIND = reminder_content.ADDRESS_KIND
LEVELS = reminder_content.LEVELS
#: The levels a title may be shown at: never restricted.
SHOWN = ("open", "internal")


def own_addresses(view: Any, person: str | None) -> list[str]:
    """The person's own email addresses as their record holds them now, lowercased, in order."""
    found = view.get("person", person) if person else None
    values = reach_lists(found.data.get("how_to_reach") if found is not None else None).get(ADDRESS_KIND, [])
    return [v.lower() for v in values]


def level_of(view: Any, question: Any) -> str:
    """The data level of a question's words: that of the saved input it came from, else internal."""
    source = view.get("source", question.data["source"]) if question.data.get("source") else None
    level = (source.data.get("sensitivity") if source is not None else None) or "internal"
    return level if level in LEVELS else "internal"


def title_allowed(cfg: Any, level: str) -> bool:
    """Whether an item at this level may have its title in a notice: titles are allowed up to the configured level, and
    a restricted item's never."""
    allowed = cfg.ui.notifications.mail_titles_level
    return allowed in SHOWN and level in SHOWN and LEVELS.index(level) <= LEVELS.index(allowed)


def titles_for(view: Any, cfg: Any, lines: list[Any]) -> list[dict[str, str]]:
    """The titles a notice may show for the lines of Today's Decide group: only a question's, and only at a level the
    person allowed. Empty for a count only."""
    found = []
    for line in lines:
        asked = getattr(line, "question", None) if getattr(line, "kind", None) in ("question", "decision") else None
        question = view.get("question", asked) if asked else None
        if question is None or not str(question.data.get("title") or "").strip():
            continue
        level = level_of(view, question)
        if title_allowed(cfg, level):
            found.append({"text": " ".join(str(question.data["title"]).split()), "level": level})
    return found


@dataclass(frozen=True)
class Expected:
    """The exact notice act for a count and titles on one account to one address: what it is drafted as, and what the
    standing yes checks the act against."""

    channel: str
    account: str
    template: dict[str, str]
    target: dict[str, Any]
    parts: dict[str, str]

    def draft_target(self) -> dict[str, Any]:
        return {key: value for key, value in self.target.items() if value not in (None, [])}


def expected(
    store: Any,
    cfg: Any,
    *,
    account: str,
    channel: str,
    person: str,
    address: str,
    count: int,
    titles: list[dict[str, str]],
    test: bool,
) -> Expected:
    """The notice act for `count` waiting items (and these titles), or the test, to `address`. Raises
    `notice_template.TemplateError` when the template can't be read."""
    from engine import notifications

    root = reminder_content.root_of(store)
    form = "test" if test else "titles" if titles else "count"
    message = notifications.test_message(cfg) if test else notifications.message_for(cfg, count)
    rendered = notice_template.render(
        root, form=form, message=message, app=cfg.workspace.name, titles=[t["text"] for t in titles]
    )
    return Expected(
        channel,
        account,
        {"name": notice_template.NAME, "version": notice_template.version(root)},
        {
            "kind": "message",
            "action": "send",
            "recipients": [{"person": person, "address": address, "kind": ADDRESS_KIND, "role": "to"}],
        },
        {"subject": rendered.subject, "body": rendered.body},
    )
