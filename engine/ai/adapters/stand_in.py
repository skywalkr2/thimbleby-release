"""What the stand-in AI answers when nothing scripts it: plain rules over the input, so a person trying the app without
an account sees the whole loop work on their own words. It is no model and claims to be none.

Reading an input, each line is looked at on its own:
- "<Name> will <do something>" (or "is going to", "needs to", "should") becomes an action owned by that name; "I will"
  is the PM's own. A date written YYYY-MM-DD after "by", "on" or "before" becomes its due date.
- "We need <something>", "Need to <do something>" or "To do: <something>" becomes an action with no owner, which waits
  for the PM to pick one.
- "Decided: …", "Agreed: …" or "Decision: …" becomes a fact. In the user's own note it is their choice; in a document it
  is what the document lists, so the fact says that ("The notes list that …") and names no one as having chosen.
Every one cites its line word for word. Whatever else the input says is kept as one note.

Answering a question, it quotes the first passage of the user guide chosen for the question. The person's answer to one
of the questions in the lists, typed on the question, closes it with their words as the answer.

Learning from a correction, it generalizes nothing, except for the account check's fixed correction, which gets the one
lesson the check expects.
"""

from __future__ import annotations

import json
import re
from typing import Any

from engine.ai import learning_check

_INPUT = re.compile(r"<untrusted[^>]*>\s*(.+?)\s*</untrusted>|<note[^>]*>\s*(.+?)\s*</note>", re.S)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_NAME = r"[A-Z][\w'’-]+(?: [A-Z][\w'’-]+)?"
_WILL = re.compile(rf"^(?P<who>I|{_NAME}) (?:will|is going to|needs to|should) (?P<what>.+?)[.!]?$")
_NEED_TO = re.compile(r"^(?:we )?(?:still )?needs? to (?P<what>.+?)[.!]?$", re.I)
_NEED = re.compile(r"^we (?:still )?need (?P<what>.+?)[.!]?$", re.I)
_TODO = re.compile(r"^to ?do:\s*(?P<what>.+?)[.!]?$", re.I)
_DECIDED = re.compile(r"^(?:decided|agreed|decision):\s*(?P<what>.+?)\s*$", re.I)
_DUE = re.compile(r"\b(?:by|on|before) (\d{4}-\d{2}-\d{2})\b")
_NOT_NAMES = {"We", "They", "You", "He", "She", "It", "This", "That", "Someone", "Everyone", "Nobody"}


def _lines(request: str) -> list[tuple[str, bool]]:
    """The lines of the input, each with whether it is the user's own note; bullets removed, headings and blanks left
    out."""
    lines = []
    for match in _INPUT.finditer(request):
        own = match.group(1) is None
        for raw in (match.group(1) or match.group(2) or "").splitlines():
            line = _BULLET.sub("", raw).strip()
            if line and not line.startswith(("#", "{")):
                lines.append((line, own))
    return lines


def input_lines(request: str) -> list[str]:
    """The lines of the input (outside material and the PM's note), bullets removed, headings and blanks left out."""
    return [line for line, _ in _lines(request)]


def _sentence(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] + ("" if text.endswith((".", "!", "?")) else ".")


_RECORD = re.compile(r'<untrusted source="record">\s*(.+?)\s*</untrusted>', re.S)
_OWN_NOTE = re.compile(r"<note[^>]*>\s*(.+?)\s*</note>", re.S)


def _answer_to(request: str) -> dict[str, Any] | None:
    """The person's answer to a question, typed on the question: it closes the question with their words as the
    answer. None for any other input."""
    from engine.intake import NOTE_ROUTES

    note = _OWN_NOTE.search(request)
    for found in _RECORD.finditer(request):
        try:
            said = json.loads(found.group(1))
        except ValueError:
            continue
        record = said.get("record") if isinstance(said, dict) else None
        if not isinstance(record, dict) or said.get("the person") != NOTE_ROUTES["answered"] or note is None:
            continue
        if record.get("kind") == "question" and record.get("id"):
            words = " ".join(note.group(1).split())
            return {
                "summary": "The stand-in recorded your answer to the question.",
                "ops": [{"op": "question.done", "id": record["id"], "answer": words, "evidence": {"quote": words}}],
            }
    return None


def read(request: str) -> dict[str, Any]:
    """A changeset for one input, by the rules above."""
    if (answered := _answer_to(request)) is not None:
        return answered
    ops: list[dict[str, Any]] = []
    rest: list[str] = []
    for line, own in _lines(request):
        will, decided = _WILL.match(line), _DECIDED.match(line)
        todo = _NEED_TO.match(line) or _TODO.match(line)
        need = _NEED.match(line)
        if will and will.group("who").split()[0] not in _NOT_NAMES:
            who = "me" if will.group("who") == "I" else will.group("who")
            op = {"op": "action.add", "text": _sentence(will.group("what")), "owners": [who]}
        elif todo:
            op = {"op": "action.add", "text": _sentence(todo.group("what")), "owners": []}
        elif need:
            op = {"op": "action.add", "text": _sentence("get " + need.group("what")), "owners": []}
        elif decided:
            what = decided.group("what")
            # The person's own note is a choice they made; a document's line only says what the document lists.
            op = {"op": "fact", "text": _sentence(what if own else f"the notes list that {what.rstrip('.!?')}")}
        else:
            rest.append(line)
            continue
        if op["op"] == "action.add" and (due := _DUE.search(line)):
            op["due"] = due.group(1)
        op["evidence"] = {"quote": line}
        ops.append(op)
    if rest or not ops:
        ops.append({"op": "note", "text": " ".join(rest)[:2000] or "(empty input)"})
    found = sum(1 for op in ops if op["op"] != "note")
    summary = (
        f"The stand-in read {found} item{'s' if found != 1 else ''} by its rules."
        if found
        else ("The stand-in found nothing it reads by rule, so it kept the input as a note.")
    )
    return {"summary": summary, "ops": ops}


def answer(request: str, stable: str) -> dict[str, Any]:
    """An answer quoting the first sentence of the first guide passage chosen for the question."""
    guide = request.split("# From the user guide", 1)[1] if "# From the user guide" in request else ""
    guide = guide.split("<question>", 1)[0]
    section = re.search(r"^## (?P<title>[^\n]+)\n(?P<text>.+?)(?=\n## |\Z)", guide.strip(), re.S | re.M)
    if section:
        first = re.split(r"(?<=[.!?])\s", " ".join(section.group("text").split()), maxsplit=1)[0]
        return {
            "summary": "Answered from the user guide.",
            "ops": [
                {
                    "op": "answer",
                    "text": f'The stand-in can only point to the user guide. Under "{section.group("title")}" it '
                    f"says: {first}",
                    "cites": [{"quote": first}],
                }
            ],
        }
    install = stable.split("# What this install can do\n", 1)[1] if "# What this install can do\n" in stable else ""
    can_do = next((line.strip() for line in install.splitlines() if line.strip() and not line.startswith("#")), "")
    return {
        "summary": "Nothing in the user guide matched.",
        "ops": [
            {
                "op": "answer",
                "text": "The stand-in found nothing in the user guide about that. An AI account answers in its own "
                "words.",
                "cites": [{"quote": can_do or "the user guide"}],
            }
        ],
    }


#: A subject that only says something is ready to view, with no figure in it: a notice, whatever its words suggest.
_READY_TO_VIEW = re.compile(r"\b(?:is|are)\s+(?:now\s+)?(?:available|ready)\b|\bready to (?:view|download)\b", re.I)


def sort_mail(request: str) -> dict[str, Any]:
    """Sorting mail headers: the stand-in weighs the built-in rules' `hints` the way the prompt asks a real model to.
    Mail sent to many or filed under promotions, social or forums is sales; an automated notice not written to the
    person alone is a notice; a notice written to the person alone, and anything with no such hint, is work. It reads
    nothing else, so it hides nothing on a guess."""
    answers = []
    for line in request.splitlines():
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        hints = " ".join(str(h) for h in row.get("hints") or []).lower()
        if (
            "automated notice" in hints
            and _READY_TO_VIEW.search(str(row.get("subject") or ""))
            and not re.search(r"\d", str(row.get("subject") or ""))
        ):
            word = "notice"  # an automated "it is ready to view" with nothing owed in its header
        elif "written to you alone" in hints:
            word = "work"
        elif any(c in hints for c in ("promotions", "social", "forums")):
            word = "sales"
        elif "automated notice" in hints or "one-time code" in hints or "under updates" in hints:
            word = "notice"
        elif "many people" in hints:
            word = "sales"
        else:
            word = "work"
        answers.append({"id": row.get("id"), "answer": word})
    return {"answers": answers}


def follow_on() -> dict[str, Any]:
    """A follow-on run's answer: nothing is changed, because a plain rule can't judge what a moved date means for the
    records tied to it."""
    return {"summary": "Nothing tied needed a change.", "ops": []}


_TALLY_LINE = re.compile(
    r"^(?P<address>\S+@\S+) \| (?P<name>[^|]+) \| (?P<from>\d+) from them, (?P<to>\d+) to them \| [^|]+"
    r"(?: \| sides: [^|]*)?(?: \| hints: (?P<hints>[^|]*))?(?P<on_file> \| on file: \S+)?$"
)
#: The most people the stand-in offers from one look, and the fewest messages (both ways added) it takes as a pattern.
_LOOK_MOST, _LOOK_FEWEST = 5, 3
#: The hints that say a sender is a machine or a list; the stand-in has no judgment, so it leaves these out.
_MACHINE_HINTS = ("automated sender", "marked bulk mail", "mail of a kind the app tracks")


def knowledge_person(request: str) -> dict[str, Any]:
    """A weekly look's answer, for trying the app with no account: an offer of each of the few addresses the user deals
    with most (at least `_LOOK_FEWEST` messages, both ways added, not on file, and with no hint of a machine or a
    list), said as plainly as the counts say it. It makes no judgment about a name's shape or a role address: a rule
    can't tell who is a person, which is the assistant's reading. It suggests no organization and no routing, and a
    routine for each weekly entry that isn't a meeting with other people."""
    block = re.search(r'<untrusted source="contact-tally">\s*(.*?)\s*</untrusted>', request, re.S)
    found = []
    for line in (block.group(1) if block else "").splitlines():
        row = _TALLY_LINE.match(line.strip())
        if row is None or row["on_file"] or any(h in (row["hints"] or "") for h in _MACHINE_HINTS):
            continue
        count = int(row["from"]) + int(row["to"])
        if count >= _LOOK_FEWEST:
            found.append((count, row["name"].strip(), row["address"], int(row["from"]), int(row["to"])))
    found.sort(key=lambda f: (-f[0], f[1]))
    people = [
        {
            "address": address,
            "name": name,
            "why": f"Someone you deal with: {sent_by} messages from them and {sent_to} sent to them.",
        }
        for _count, name, address, sent_by, sent_to in found[:_LOOK_MOST]
    ]
    ops: list[dict[str, Any]] = [{"op": "person.offer", "people": people}] if people else []
    ops += _routine_ops(request)
    return {"summary": "People you deal with." if ops else "Nothing plain enough to suggest.", "ops": ops}


_WEEK_LINE = re.compile(
    r"^\[(?P<id>[^\]]+)\] (?P<kind>\w+) \| (?P<first>\d{4}-\d\d-\d\d)"
    r"(?: to (?P<last>\d{4}-\d\d-\d\d))? \| (?P<title>[^|]+)"
)


def week_ahead(request: str) -> dict[str, Any]:
    """A week-ahead answer by plain rules: one row for each record the request lists, the soonest first, as many as the
    request allows, saying only the title; and a sentence that counts them. A rule can't tell what matters; this is for
    trying the app with no account."""
    block = re.search(r'<untrusted source="week-records">\s*(.*?)\s*</untrusted>', request, re.S)
    most = re.search(r"Give at most (\d+) rows", request)
    held = re.search(r'<untrusted source="today-lines">\s*(.*?)\s*</untrusted>', request, re.S)
    rows = []
    for line in (block.group(1) if block else "").splitlines():
        found = _WEEK_LINE.match(line.strip())
        if found is None or (held and found["id"] in held.group(1)):  # what Today holds is left out, as asked
            continue
        row = {"from_day": found["first"], "words": found["title"].strip()[:160], "source": found["id"]}
        if found["last"]:
            row["to_day"] = found["last"]
        rows.append(row)
    rows = rows[: int(most.group(1)) if most else 8]
    count = len(rows)
    sentence = f"{count} {'thing' if count == 1 else 'things'} in the week ahead." if count else "A quiet week."
    return {"summary": "The week ahead.", "ops": [{"op": "week.read", "sentence": sentence, "rows": rows}]}


_GOAL_LINE = re.compile(
    r"^\[(?P<id>[^\]]+)\] (?P<kind>task|promise) \| (?P<day>\d{4}-\d\d-\d\d|no day) \| (?P<text>[^|]+)"
)


def monday_goals(request: str) -> dict[str, Any]:
    """A goals answer by plain rules: the to-dos and promises the request lists, the soonest due first, as many as it
    allows, in their own words. A rule can't tell what matters most in a week; this is for trying the app with no
    account."""
    block = re.search(r'<untrusted source="week-items">\s*(.*?)\s*</untrusted>', request, re.S)
    most = re.search(r"Give at most (\d+) goals", request)
    found = []
    for line in (block.group(1) if block else "").splitlines():
        m = _GOAL_LINE.match(line.strip())
        if m is not None:
            found.append((m["day"], m["text"].strip()[:200], m["id"]))
    seen: set[str] = set()
    goals = []
    for _day, text, record_id in sorted(found):
        if text.lower() not in seen:
            seen.add(text.lower())
            goals.append({"words": text, "source": record_id})
    goals = goals[: int(most.group(1)) if most else 5]
    return {"summary": "Goals for the week.", "ops": [{"op": "week.goals", "goals": goals}]}


_AREA_LINE = re.compile(
    r"^\[(?P<id>[^\]]+)\] (?P<kind>to-do|question|fact|calendar entry) \|.*\| shares: (?P<shared>.*)$"
)
_AREA_KINDS = {"to-do": "action", "question": "question", "fact": "fact", "calendar entry": "event"}


def area_read(request: str) -> dict[str, Any]:
    """An areas answer by plain rules: the items the request lists, grouped by the first word they share, a group of two
    or more named by that word. A rule can't tell what items are about; this is for trying the app with no account."""
    block = re.search(r'<untrusted source="area-items">\s*(.*?)\s*</untrusted>', request, re.S)
    groups: dict[str, list[dict[str, str]]] = {}
    for line in (block.group(1) if block else "").splitlines():
        m = _AREA_LINE.match(line.strip())
        if m is not None and m["shared"].strip():
            word = m["shared"].split(",")[0].strip()
            groups.setdefault(word, []).append({"kind": _AREA_KINDS[m["kind"]], "id": m["id"]})
    areas = [
        {"name": word.capitalize(), "why": f"{len(items)} items are about {word}.", "items": items}
        for word, items in groups.items()
        if len(items) >= 2
    ]
    return {
        "summary": "Areas of your life." if areas else "No area stands out.",
        "ops": [{"op": "area.offer", "areas": areas}],
    }


_SERIES_LINE = re.compile(
    r"^(?P<title>[^|]+) \| (?P<day>[A-Z][a-z]+) (?P<start>\d\d:\d\d)-(?P<end>\d\d:\d\d) \| repeats: (?P<rule>.*)$"
)
#: Words in a title that make it a meeting with other people, which the stand-in doesn't take as a routine.
_MEETING_WORDS = ("sync", "meeting", "standup", "stand-up", "call", "review", "1:1", "interview", "with ")


def _routine_ops(request: str) -> list[dict[str, Any]]:
    """A routine for each weekly entry or slot kept week after week whose title isn't a meeting with other people."""
    block = re.search(r'<untrusted source="repeating-entries">\s*(.*?)\s*</untrusted>', request, re.S)
    ops = []
    for line in (block.group(1) if block else "").splitlines():
        row = _SERIES_LINE.match(line.strip())
        if row is None or any(w in row["title"].lower() for w in _MEETING_WORDS):
            continue
        rule = row["rule"]
        if not (rule.startswith("same time on") or (rule.startswith("FREQ=WEEKLY") and "INTERVAL" not in rule)):
            continue
        title, day, start, end = row["title"].strip(), row["day"], row["start"], row["end"]
        meaning = f"{day}s {start} to {end}"
        ops.append(
            {
                "op": "glossary.add",
                "text": f"{title}: {meaning}",
                "term": title,
                "meaning": meaning,
                "confidence": "assumed",
                "routine": {"days": [day.lower()], "start": start, "end": end},
                "evidence": {"quote": line.strip()},
            }
        )
    return ops


def learn(request: str) -> dict[str, Any]:
    """A learning run's answer: the one lesson the account check's correction teaches, and nothing for any other."""
    if learning_check.CHECK_REQUEST not in request:
        return {"summary": "Nothing to generalize.", "topic": "", "ops": []}
    return {
        "summary": "A lesson.",
        "topic": "delivery dates",
        "ops": [
            {
                "op": "lesson.add",
                "text": "Questions about a delivery date go to whoever owns the delivery.",
                "guard": "Ask the owner of the delivery, not the head of the project.",
            }
        ],
    }
