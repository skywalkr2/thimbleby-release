"""The knowledge section of a packet (design 6.22): what the workspace has learned, chosen for one run.

Plain functions over a snapshot of the records, with no AI. Two parts, so a provider's cached prefix holds from input
to input: `stable_section` is the same for every run of a task kind (standing rules for the whole workspace, lessons
for the task kind, the glossary while it is small) and carries no dates or counts; `per_input_section` depends on the
input (narrowed rules, lessons and glossary terms, routing, ranked facts). Scope is filtered here, never left to the
model: an entry whose scope excludes the input's projects is not in the text, and its id is returned so the run's
knowledge log can say so. Only active entries go in. An entry that came from outside content is shown as data with its
source, never as guidance.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date
from typing import Any, NamedTuple

from engine.config.schema import KnowledgeSettings
from engine.language_words import language_words, shipped
from engine.local_day import day_of
from engine.records import Scope
from engine.untrusted import neutralize, outside_block, quoted_attribute

HEADINGS = {
    "rules": "# Standing rules",
    "lessons": "# Lessons",
    "glossary": "# Glossary",
    "input_rules": "# Standing rules for this input",
    "input_lessons": "# Lessons for this input",
    "guesses": "# Learned from the user's corrections, not yet kept\n"
    "Apply these as guesses unless the input names someone else for the work.",
    "routing": "# Who answers what",
    "style": "# How to write for them",
    "input_glossary": "# Terms this input uses",
    "facts": "# Facts recorded for this input's projects",
}

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class Stable(NamedTuple):
    text: str
    ids: list[str]
    moved: list[str]  # rules moved to the per-input part because the section passed its size budget


class PerInput(NamedTuple):
    text: str
    ids: list[str]
    left_out_by_scope: list[str]
    facts_left_out: int
    facts_chars: int = 0  # how many characters of `text` are the facts section


# ---- reading the records ---------------------------------------------------------------------------------------------


def _id_key(record_id: str) -> tuple[str, int, str]:
    """Order by id the way a person reads them: LES-2 before LES-10."""
    prefix, _, number = record_id.rpartition("-")
    return prefix, int(number) if number.isdigit() else 0, record_id


def _key(stored: Any) -> tuple[str, int, str]:
    return _id_key(stored.id)


def _active(view: Any, kind: str) -> list[Any]:
    return sorted((s for s in view.list(kind) if s.data.get("status") == "active"), key=_key)


def _scope(stored: Any) -> Scope:
    return Scope.model_validate(stored.data.get("applies_to") or {})


def _covers_task(scope: Scope, task_kind: str) -> bool:
    return not scope.task_kinds or task_kind in scope.task_kinds


def _whole_workspace(scope: Scope) -> bool:
    """Nothing narrows it by project, exclusion or person (task kinds are decided by each caller)."""
    return scope.scope == "workspace" and not scope.except_ and not scope.projects and not scope.people


def _in_scope_of_projects(scope: Scope, projects: set[str], also: str | None = None) -> bool:
    """False when the scope excludes every one of the input's projects: an `except` that names one of them, or a
    `projects` scope that doesn't include them. `also` is a project the entry itself names; it must be one of them."""
    if also is not None and also not in projects:
        return False
    if scope.scope == "projects":
        return bool(set(scope.projects) & projects)
    return not (set(scope.except_) & projects)


def _head_words(name: str) -> set[str]:
    """The words of a project name worth matching as its short form: its ids, and the last word of the name (its head:
    "gala" of "Volunteer Gala"), never a word that only describes it ("office" of "Office Move")."""
    tokens = _WORD.findall(name)
    found = {t.lower() for t in tokens if any(c.isdigit() for c in t)}
    if tokens:
        found |= {_stem(part) for part in _PART.findall(tokens[-1]) if len(part) >= 4}
    return found


def _said_as_names(
    text: str, leads: set[str], not_objects: set[str], ordinary: set[str] | None = None
) -> list[tuple[set[str], set[str], set[str]]]:
    """Each place in a text where a word reads as someone's name for a thing, as its words (plurals folded) and the
    lower-case words of the capitalized words right beside it: a word right after a leading word ("the gala", "our
    exhibit"), a word written with a capital in the middle of a sentence, an id with a digit, or a word that starts a
    sentence when the next word doesn't start an object ("Exhibit planning is late" but not "Move the meeting"). An
    ordinary word on its own ("office chairs") is not one. Each place also carries the one word that must follow it
    for it to count: a sentence's first word that is also an ordinary verb or adjective (`ordinary`: "Move fast on
    the hiring", "Fair enough") counts only when the word after it is one the project's name holds; empty when
    nothing is required."""
    tokens = list(_WORD.finditer(text))
    found: list[tuple[set[str], set[str], set[str]]] = []
    ordinary = ordinary or set()

    def starts(i: int) -> bool:
        before = text[: tokens[i].start()].rstrip()
        return not before or before[-1] in ".!?:;\n\"'(" or text[tokens[i].start() - 1 : tokens[i].start()] == "\n"

    for i, token in enumerate(tokens):
        word = token.group(0)
        sentence_start = starts(i)
        after = tokens[i + 1].group(0).lower() if i + 1 < len(tokens) else ""
        previous = tokens[i - 1].group(0).lower() if i and not sentence_start else ""
        if (
            any(c.isdigit() for c in word)
            or previous in leads
            or (word[0].isupper() and not sentence_start)
            or (sentence_start and after not in leads | not_objects)
        ):
            beside: set[str] = set()
            if word[0].isupper():
                if i and not sentence_start and not starts(i - 1) and tokens[i - 1].group(0)[0].isupper():
                    beside.add(tokens[i - 1].group(0).lower())
                if i + 1 < len(tokens) and tokens[i + 1].group(0)[0].isupper() and not starts(i + 1):
                    beside.add(after)
            need = {_stem(after)} | {after} if sentence_start and word.lower() in ordinary else set()
            found.append(
                (_overlap_words(word) | ({word.lower()} if any(c.isdigit() for c in word) else set()), beside, need)
            )
    return found


def projects_named_in(view: Any, text: str, cfg: Any = None) -> list[str]:
    """The projects an input names in its own words: by name or alias as a whole phrase, or by a short form, the last
    word of the name (four letters or more) when no other project's name holds it, read as a name where it follows a
    leading word (`language.project_name_leads`: "the gala" for "Volunteer Gala"), is written with a capital in the
    middle of a sentence, or starts a sentence not followed by a word that starts an object (`language.
    short_form_object_leads`: "Gala tickets sold out"), plurals folded, case ignored. A word that only describes the
    project ("office" of "Office Move") and a capitalized word beside another capitalized word the name doesn't hold
    ("Office Depot", "Kitchen Aid") are never it. It leans toward naming: a project named by mistake sends a few lines
    of what was learned for it, and one missed makes the person repeat a correction."""
    said = " ".join((text or "").casefold().split())
    if not said:
        return []
    projects = list(view.list("project"))

    def names_of(p: Any) -> list[str]:
        return [p.data.get("name") or "", *(p.data.get("aliases") or [])]

    all_words = {p.id: _overlap_words(" ".join(names_of(p))) for p in projects}
    heads = {p.id: set().union(*(_head_words(n) for n in names_of(p))) for p in projects}

    def wording(key: str) -> set[str]:
        return {w.casefold() for w in (language_words(cfg.language, key) if cfg is not None else shipped(key)) or []}

    places = _said_as_names(
        text or "",
        wording("project_name_leads"),
        wording("short_form_object_leads"),
        wording("ordinary_sentence_start_words"),
    )
    found = []
    for project in projects:
        forms = [" ".join(n.casefold().split()) for n in names_of(project) if n.strip()]
        whole = any(re.search(rf"(?<!\w){re.escape(form)}(?!\w)", said) for form in forms)
        mine = {w for w in heads[project.id] if not any(w in all_words[q.id] for q in projects if q.id != project.id)}
        own_words = {t.lower() for n in names_of(project) for t in _WORD.findall(n)}
        if whole or any(
            words & mine and not (beside - own_words) and (not need or need & own_words)
            for words, beside, need in places
        ):
            found.append(project.id)
    return found


def with_ancestors(view: Any, projects: Iterable[str]) -> list[str]:
    """The projects and then every project above them (`Project.parent`, any depth), each once. A scope that names a
    project covers the projects below it, so scopes are matched against this list."""
    found: list[str] = []
    for project_id in projects:
        while project_id and project_id not in found:
            found.append(project_id)
            project = view.get("project", project_id)
            project_id = project.data.get("parent") if project is not None else None
    return found


def _about_these_people(scope: Scope, people: set[str]) -> bool:
    return not scope.people or bool(set(scope.people) & people)


# ---- how an entry is shown -------------------------------------------------------------------------------------------


def _marked(text: str) -> str:
    """Text that can't close the marking it sits in."""
    return neutralize(text)


def _origin_note(data: dict[str, Any]) -> str:
    if data.get("origin") != "pack":
        return ""
    return f" (pack guidance: {data['pack']})" if data.get("pack") else " (pack guidance)"


def _source_label(view: Any, data: dict[str, Any]) -> str:
    """Where an entry from outside came from: its source's title, else the source's id or the entry's origin. The
    title is itself outside text; the block's renderer makes it safe."""
    source_id = data.get("source") or (data.get("evidence") or {}).get("source")
    source = view.get("source", source_id) if source_id else None
    return str(source.data["title"] if source is not None else source_id or data.get("origin") or "outside")


def _shown(view: Any, stored: Any, line: str) -> str:
    """A line as guidance when its source is trusted, else as data with its source."""
    if stored.data.get("trust", "trusted") == "trusted":
        return line
    return outside_block(line, _source_label(view, stored.data))


def _section(view: Any, heading: str, lines: list[tuple[Any, str]]) -> str:
    """One heading, then the lines guidance gives, then each line from untrusted content on its own as data."""
    if not lines:
        return ""
    trusted = [line for stored, line in lines if stored.data.get("trust", "trusted") == "trusted"]
    data = [_shown(view, stored, line) for stored, line in lines if stored.data.get("trust", "trusted") != "trusted"]
    return "\n".join([heading, *trusted, *data])


def _rule_line(rule: Any, *, one_line: bool = False) -> str:
    data = rule.data
    lines = [line.strip() for line in data["text"].splitlines() if line.strip()]
    text = (lines[0] if one_line else " ".join(lines)) if lines else data["name"]
    pause = f" (pauses {data['pauses']} until {data['until']})" if data.get("pauses") else ""
    return f"- {rule.id}: {text}{pause}{_origin_note(data)}"


def _entry_line(stored: Any) -> str:
    line = f"- {stored.id}: {stored.data['text']}{_origin_note(stored.data)}"
    if kind := " ".join(str(stored.data.get("kind_of_work") or "").split()):
        # The item is the entry's own; an item only of its kind gets it as a guess the person sees marked.
        line += (
            f" Also for {kind}: apply it to such an item too, as a guess, and name that step in"
            f' "by_kind" ({{"op": <its index>, "entry": "{stored.id}"}}).'
        )
    return line


def _guess_line(stored: Any, view: Any = None) -> str:
    """A learned entry not yet kept, led by what it decides: for an entry that names a person and a kind of work, that
    such work is theirs ("what goes out for the gala is <name>'s work"), so the cheapest model reads it for the next
    item of that kind and not only for the one it was learned on; then the person's own words, and that whatever it
    decides is only a guess the run names."""
    kind = " ".join(str(stored.data.get("kind_of_work") or "").split())
    who = stored.data.get("person")
    found = view.get("person", who) if view is not None and who else None
    name = (found.data.get("full_name") or "").strip() if found is not None else ""
    mark = f'name each step it decides in "by_kind" ({{"op": <its index>, "entry": "{stored.id}"}})'
    if kind and name:
        return (
            f"- {stored.id}: {kind[0].upper() + kind[1:]} is {name}'s work. Not yet kept: give each to-do of that kind "
            f"to {name} ({who}) as a guess unless the input names someone else, and {mark}. Learned from: "
            f"{stored.data['text']}"
        )
    reach = f" (and for {kind})" if kind else ""
    return f"- {stored.id}: {stored.data['text']}{reach}. Not yet kept: apply it only as a guess, and {mark}."


def _term_line(stored: Any) -> str:
    return f"- {stored.data['term']}: {stored.data['meaning']}{_origin_note(stored.data)}"


# ---- the stable part -------------------------------------------------------------------------------------------------


def _stable_rule(scope: Scope, task_kind: str) -> bool:
    return _whole_workspace(scope) and scope.task_kinds in ([], [task_kind])


def _leaves_first(rule: Any, scope: Scope, task_kind: str) -> int:
    """How soon a rule leaves the always-sent part when it grows too large: rules for one task kind first, then
    workspace-wide rules from other sources, and the person's own workspace-wide rules last."""
    if scope.task_kinds == [task_kind]:
        return 0
    return 2 if rule.data.get("origin") == "person" else 1


def stable_section(view: Any, task_kind: str, settings: KnowledgeSettings) -> Stable:
    """The knowledge every run of this task kind is sent: active rules for the whole workspace, active lessons for
    the task kind, then the whole glossary while it has fewer terms than `glossary_all_below`. By id, with no dates or
    counts. A rule a stage check enforces is there as its one line only. Past `stable_budget`, rules leave one by one,
    narrowest first, and are returned in `moved` for the per-input part to carry."""
    rules = [(r, _scope(r)) for r in _active(view, "rule")]
    rules = [(r, s) for r, s in rules if _stable_rule(s, task_kind)]
    lessons = [s for s in _active(view, "lesson") if _whole_workspace(_scope(s)) and _covers_task(_scope(s), task_kind)]
    terms = [
        s
        for s in _active(view, "glossary_entry")
        if _whole_workspace(_scope(s)) and _covers_task(_scope(s), task_kind) and not s.data.get("project")
    ]
    if len(terms) >= settings.glossary_all_below:
        terms = []

    def build(kept: list[tuple[Any, Scope]]) -> str:
        rule_lines = [(r, _rule_line(r, one_line=bool(r.data.get("check")))) for r, _ in kept]
        return "\n\n".join(
            part
            for part in (
                _section(view, HEADINGS["rules"], rule_lines),
                _section(view, HEADINGS["lessons"], [(s, _entry_line(s)) for s in lessons]),
                _section(view, HEADINGS["glossary"], [(s, _term_line(s)) for s in terms]),
            )
            if part
        )

    kept = list(rules)
    text = build(kept)
    moved: list[str] = []
    # Newest first within a kind of rule, then the narrowest kind first; the sort is stable.
    order = sorted(
        sorted(rules, key=lambda pair: _key(pair[0]), reverse=True), key=lambda pair: _leaves_first(*pair, task_kind)
    )
    for pair in order:
        if len(text) <= settings.stable_budget:
            break
        kept.remove(pair)
        moved.append(pair[0].id)
        text = build(kept)
    ids = [r.id for r, _ in kept] + [s.id for s in lessons] + [s.id for s in terms]
    return Stable(text, ids, sorted(moved, key=_id_key))


def lessons_for(view: Any, task_kind: str) -> tuple[str, list[str]]:
    """Only the active lessons that cover this task kind, for a run whose packet carries no rules or glossary: the
    section's text (empty when there are none) and the ids it holds."""
    lessons = [s for s in _active(view, "lesson") if _whole_workspace(_scope(s)) and _covers_task(_scope(s), task_kind)]
    return _section(view, HEADINGS["lessons"], [(s, _entry_line(s)) for s in lessons]), [s.id for s in lessons]


def all_guidance(view: Any) -> tuple[str, list[str], list[str]]:
    """Every active rule and lesson, whatever it applies to, for work that judges the guidance itself: the text (rules
    first, then lessons, by id, with no dates or counts), the ids it holds, and the ids of the rules among them."""
    rules = _active(view, "rule")
    lessons = _active(view, "lesson")
    text = "\n\n".join(
        part
        for part in (
            _section(view, HEADINGS["rules"], [(r, _rule_line(r)) for r in rules]),
            _section(view, HEADINGS["lessons"], [(s, _entry_line(s)) for s in lessons]),
        )
        if part
    )
    return text, [r.id for r in rules] + [s.id for s in lessons], [r.id for r in rules]


# ---- the per-input part ----------------------------------------------------------------------------------------------


def _uses(term: str, text: str) -> bool:
    return bool(term.strip()) and re.search(rf"(?<!\w){re.escape(term.strip())}(?!\w)", text, re.IGNORECASE) is not None


_PART = re.compile(r"[A-Za-z0-9]+")


def _stem(word: str) -> str:
    """A word with its plural folded, so "reviewers" and "copies" match "reviewer" and "copy"."""
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 4:
        return w[:-1]
    return w


def _overlap_words(text: str) -> set[str]:
    """The words and ids of a text worth matching on, lower case: ids whole, and long words split at hyphens with their
    plurals folded."""
    found: set[str] = set()
    for token in _WORD.findall(text):
        if any(c.isdigit() for c in token):
            found.add(token.lower())
        found |= {_stem(part) for part in _PART.findall(token) if len(part) >= 4}
    return found


def topic_share(topic: str, text: str) -> float:
    """How much of a topic's words a text holds, from 0 to 1 (0 for a topic with no words worth matching)."""
    wanted = _overlap_words(topic)
    return len(wanted & _overlap_words(text)) / len(wanted) if wanted else 0.0


def per_input_section(
    view: Any,
    task_kind: str,
    projects: Iterable[str],
    people: Iterable[str],
    text: str,
    today: date,
    settings: KnowledgeSettings,
    moved: Iterable[str] = (),
    facts: bool = True,
    scope_projects: Iterable[str] | None = None,
    hide: Callable[[Mapping[str, Any]], bool] | None = None,
    about: Iterable[str] = (),
) -> PerInput:
    """The knowledge that depends on the input: rules narrowed to some projects or task kinds that cover it, rules a
    stage check enforces (in full) and rules that moved out of the stable part; lessons for its projects or people;
    routing for its people and projects; the glossary terms it uses once the glossary is too large to send whole;
    then the facts of its projects, ranked and cut at `facts_budget`. `text` is the input's words, which decide the
    terms and rank the facts. Returns the text, the ids given, the ids left out by scope, and how many facts didn't
    fit. With `facts` False (work the core's learning doesn't run on) the facts are left out. Scopes are matched against
    `scope_projects` (the projects and their ancestors; the projects alone when None); facts stay per exact project,
    except a fact marked as reaching the projects inside its own, which goes with them too. A fact `hide` is true for
    (one made from a message the draft's reader may not see) is never shown. `about` names the records the run works
    on: the facts recorded about them (a fact's `about`) go with the projects' facts, under the same budget."""
    project_set, people_set, moved_set = set(projects), set(people), set(moved)
    scoped = set(scope_projects) if scope_projects is not None else project_set
    ids: list[str] = []
    left_out: set[str] = set()
    sections: list[str] = []

    def passes(stored: Any, scope: Scope, also: str | None = None) -> bool:
        if not _covers_task(scope, task_kind):
            return False
        if (also is not None and also not in project_set) or not _in_scope_of_projects(scope, scoped):
            left_out.add(stored.id)
            return False
        return _about_these_people(scope, people_set)

    def add(heading: str, lines: list[tuple[Any, str]]) -> None:
        rendered = _section(view, heading, lines)
        if rendered:
            sections.append(rendered)
            ids.extend(stored.id for stored, _ in lines)

    # What the person's corrections taught that waits for their Keep comes first, so the cheapest model sees it before
    # anything else it might weigh: given as a guess, every step it decides marked.
    guesses = []
    for kind in ("lesson", "routing_entry"):
        for entry in sorted(view.list(kind), key=_key):
            data = entry.data
            if data.get("status") != "proposed" or not data.get("guess_until_kept"):
                continue
            scope = _scope(entry)
            if passes(entry, scope) and (_whole_workspace(scope) or bool(set(scope.projects) & scoped) or people_set):
                guesses.append((entry, _guess_line(entry, view)))
    add(HEADINGS["guesses"], guesses)

    rules = []
    for rule in _active(view, "rule"):
        scope = _scope(rule)
        if not passes(rule, scope):
            continue
        if not _stable_rule(scope, task_kind) or rule.data.get("check") or rule.id in moved_set:
            rules.append((rule, _rule_line(rule)))
    add(HEADINGS["input_rules"], rules)

    lessons = []
    for lesson in _active(view, "lesson"):
        scope = _scope(lesson)
        if passes(lesson, scope) and not _whole_workspace(scope):
            lessons.append((lesson, _entry_line(lesson)))
    add(HEADINGS["input_lessons"], lessons)

    teams = {
        t for pid in people_set if (person := view.get("person", pid)) is not None and (t := person.data.get("team"))
    }
    routing = []
    for entry in _active(view, "routing_entry"):
        scope = _scope(entry)
        if not passes(entry, scope):
            continue
        about_input = (
            entry.data.get("person") in people_set
            or (entry.data.get("team") is not None and entry.data["team"] in teams)
            or (scope.scope == "projects" and bool(set(scope.projects) & scoped))
            # an input about the entry's topic, whoever it names: who to ask is what the run needs to know
            or _uses(entry.data.get("topic") or "", text)
            or topic_share(entry.data.get("topic") or "", text) >= settings.routing_match
        )
        if about_input:
            routing.append((entry, _entry_line(entry)))
    add(HEADINGS["routing"], routing)

    # Style notes for the people this input names, and those for a kind of audience in words (design 6.22).
    style = []
    for note in _active(view, "style_note"):
        scope = _scope(note)
        if not passes(note, scope):
            continue
        audience = str(note.data.get("audience") or "")
        if view.get("person", audience) is None or audience in people_set:
            style.append((note, _entry_line(note)))
    add(HEADINGS["style"], style)

    whole = {
        s.id
        for s in _active(view, "glossary_entry")
        if _whole_workspace(_scope(s)) and _covers_task(_scope(s), task_kind) and not s.data.get("project")
    }
    send_whole = len(whole) < settings.glossary_all_below
    terms = []
    for entry in _active(view, "glossary_entry"):
        scope = _scope(entry)
        if entry.id in whole:
            wanted = not send_whole and _uses(entry.data["term"], text)
        elif passes(entry, scope, entry.data.get("project")):
            # An entry for some projects goes with them; one only narrowed by an exclusion goes when its term is used.
            wanted = scope.scope == "projects" or bool(entry.data.get("project")) or _uses(entry.data["term"], text)
        else:
            wanted = False
        if wanted:
            terms.append((entry, _term_line(entry)))
    add(HEADINGS["input_glossary"], terms)

    fact_text, fact_ids, cut = (
        _facts_section(view, project_set, text, today, settings.facts_budget, scoped, hide, set(about))
        if facts
        else ("", [], 0)
    )
    if fact_text:
        sections.append(fact_text)
        ids.extend(fact_ids)
    return PerInput("\n\n".join(sections), ids, sorted(left_out, key=_id_key), cut, len(fact_text))


def _facts_section(
    view: Any,
    projects: set[str],
    text: str,
    today: date,
    budget: int,
    scoped: set[str] | None = None,
    hide: Callable[[Mapping[str, Any]], bool] | None = None,
    about: set[str] | None = None,
) -> tuple[str, list[str], int]:
    """The input's projects' facts that no newer fact replaces, key facts first, then by how many of the input's words
    and ids they share, then newest; cut at `budget` characters with the count of those left out said. A fact of a
    project above them (`scoped` holds the projects and their ancestors) goes too when it is marked as reaching the
    projects inside it; any other fact of an ancestor stays with that project. A fact about one of the records the run
    works on (`about`) goes with them."""
    from engine.facts import replaced_ids

    facts = view.list("fact")
    replaced = replaced_ids(facts, hide)
    above = (scoped or projects) - projects
    mine = [
        f
        for f in facts
        if f.id not in replaced
        and not (hide is not None and hide(f.data))
        and (
            f.data.get("project") in projects
            or (f.data.get("project") in above and f.data.get("reaches_children"))
            or (about and f.data.get("about") in about)
        )
    ]
    if not mine:
        return "", [], 0
    words = _overlap_words(text)

    def when(fact: Any) -> date | None:
        if fact.data.get("as_of"):
            return min(date.fromisoformat(str(fact.data["as_of"])), today)
        source = view.get("source", fact.data["source"]) if fact.data.get("source") else None
        return min(day_of(source.data["received_at"], UTC), today) if source is not None else None

    def rank(fact: Any) -> tuple:
        day = when(fact)
        _, number, _ = _key(fact)
        return (
            not fact.data.get("key"),
            -len(_overlap_words(fact.data["text"]) & words),
            day is None,
            -(day.toordinal() if day else 0),
            -number,
        )

    def line(fact: Any) -> str:
        day = when(fact)
        source = view.get("source", fact.data["source"]) if fact.data.get("source") else None
        # A source's title is outside text even on a fact the person kept: nothing in it may read as a tag.
        title = quoted_attribute(source.data["title"]) if source else ""
        bits = ([f"as of {day.isoformat()}"] if day else []) + ([f"from {title}"] if title else [])
        return f"- {fact.id}: {fact.data['text']}" + (f" ({', '.join(bits)})" if bits else "")

    shown: list[tuple[Any, str]] = []
    used = len(HEADINGS["facts"])
    for fact in sorted(mine, key=rank):
        rendered = _shown(view, fact, line(fact))
        if used + len(rendered) + 1 > budget:
            break
        shown.append((fact, rendered))
        used += len(rendered) + 1
    cut = len(mine) - len(shown)
    lines = [HEADINGS["facts"], *(rendered for _, rendered in shown)]
    if cut:
        on = "this work" if about else "this project" if len(projects) == 1 else "these projects"
        lines.append(f"- {cut} more {'fact' if cut == 1 else 'facts'} on {on}; ask to search for them")
    return "\n".join(lines), [f.id for f, _ in shown], cut
