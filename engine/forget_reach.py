"""What else holds a forgotten person (design 5.2, 12.4; S-0443 part 2), reached by the same `person.forget` change.

Four rules decide what happens to each thing that holds them:

- **R1, content from them:** the mail they sent (its snapshot, saved source records, saved text files and the requests
  made from it), the answers they gave, and the files kept from their mail. The content goes as a confirmed set-aside's
  deletion does (`engine/set_aside.py`, `engine/files.py`): a marker in its place, the text files and bytes gone unless
  something else still holds them, the ledger's earlier values given up. The knowledge log of the runs made from their
  mail goes too.
- **R2, records that exist only for them:** routing entries and style notes about them and standing yeses for them. They
  are blanked and removed.
- **R3, the person's own work that mentions them:** every other record. It stays, references by id stay, and any copy of
  their name, address or phone in its words is replaced by a marker. An evidence quote taken from their mail is replaced
  by a "quote forgotten" marker. The long texts of such records are rewritten the same way.
- **R4, outside the database:** the private evaluation cases built from their mail or naming them are removed.

Every record changed is listed in the registry (`engine/redactions.py`) under `person.forget`, so the synced folder's
comparison and Undo cover it. Only the core's own record kinds are reached; a plugin's records are not.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.people_forget import FORGOTTEN_NAME
from engine.state_file import write_whole
from engine.storage import StoreError
from engine.storage.store import FORGOTTEN_QUOTE

#: What takes the place of a copy of an address, a phone number, an evidence quote, a piece of content and an answer.
FORGOTTEN_ADDRESS = "forgotten address"
FORGOTTEN_NUMBER = "forgotten number"
FORGOTTEN_CONTENT = "Forgotten with the person"
FORGOTTEN_ANSWER = "Answer forgotten"
#: The request states a forgotten mail's unfinished request is closed from.
_UNFINISHED = ("queued", "needs_you", "failed")
_SEPARATORS = r"[\s().\-]*"
#: The ledger entry (on the forgotten person's record) that lists what the forget gave up: a list of
#: [kind, record id, field] with ids and field names only. The synced folder's comparison and Undo read it.
REACH_FIELD = "forgotten_reach"
#: The two listed "fields" that are not a record's field: the evidence quotes of a record's entries, and (on a source)
#: every entry anywhere whose evidence quotes it.
EVIDENCE_QUOTE = "evidence quote"
QUOTED_FROM = "quoted from"


def _loose(text: str) -> str:
    """A pattern for a text in which any run of spaces matches any spacing."""
    return r"\s+".join(re.escape(part) for part in text.split())


class Identifiers:
    """What names a person: their names, their addresses and their phone numbers. `say` replaces each in a text with its
    marker, whatever the case or spacing; `found` says whether a text holds any."""

    def __init__(self, data: dict[str, Any]) -> None:
        from engine.contacts import all_values

        names = {" ".join(str(n).split()) for n in (data.get("full_name"), *(data.get("aliases") or [])) if n}
        self.people = sorted({n for n in names if len(n) > 1}, key=lambda n: (-len(n), n))
        first = " ".join(str(data.get("first_name") or "").split())
        self.names = sorted({*self.people, *([first] if len(first) > 1 else [])}, key=lambda n: (-len(n), n))
        values = sorted({v for v in all_values(data.get("how_to_reach")) if v}, key=lambda v: (-len(v), v))
        self._rules: list[tuple[re.Pattern[str], str]] = []
        self._sender: list[re.Pattern[str]] = []
        for value in values:
            digits = re.sub(r"\D", "", value)
            if "@" not in value and len(digits) >= 6 and len(digits) * 2 >= len(re.sub(r"\s", "", value)):
                # The number as written, and without its country code (the last ten digits), as people write it.
                for part in dict.fromkeys([digits, digits[-10:]]):
                    pattern = r"(?<!\d)(?:[+(]\s*)?" + _SEPARATORS.join(part) + r"(?!\d)"
                    self._rules.append((re.compile(pattern), FORGOTTEN_NUMBER))
                continue
            pattern = r"(?<![\w.+%-])" + _loose(value) + r"(?![\w-])"
            rule = re.compile(pattern, re.IGNORECASE)
            self._rules.append((rule, FORGOTTEN_ADDRESS))
            if "@" in value:
                self._sender.append(rule)
        for name in self.people:
            self._rules.append((re.compile(r"(?<!\w)" + _loose(name) + r"(?!\w)", re.IGNORECASE), FORGOTTEN_NAME))
        if len(first) > 1:
            # A lone first name is also a common word ("Will"): only its capital letter matches, never "will".
            lead = re.escape(first[0].upper())
            self._rules.append(
                (re.compile(r"(?<!\w)" + lead + "(?i:" + _loose(first[1:]) + r")(?!\w)"), FORGOTTEN_NAME)
            )
        self._sender += [re.compile(r"(?<!\w)" + _loose(n) + r"(?!\w)", re.IGNORECASE) for n in self.people]

    def say(self, text: str) -> str:
        for rule, marker in self._rules:
            text = rule.sub(marker, text)
        return text

    def found(self, text: str) -> bool:
        return any(rule.search(text) for rule, _ in self._rules)

    def from_sender(self, text: str) -> bool:
        """Whether a sender line (a name, an address or both) is theirs."""
        return any(rule.search(text) for rule in self._sender)


def scrub(
    value: Any,
    ids: Identifiers,
    *,
    sources: frozenset[str] = frozenset(),
    requests: frozenset[str] = frozenset(),
    all_quotes: bool = False,
) -> Any:
    """A copy of a stored value with every copy of the person's names, addresses and phone numbers replaced by its
    marker, and every evidence quote taken from their mail (a quote whose source is one of `sources` or whose request is
    one of `requests`, or any quote when `all_quotes` is set) replaced by the quote marker."""
    if isinstance(value, str):
        return ids.say(value)
    if isinstance(value, list):
        return [scrub(v, ids, sources=sources, requests=requests, all_quotes=all_quotes) for v in value]
    if isinstance(value, dict):
        out = {k: scrub(v, ids, sources=sources, requests=requests, all_quotes=all_quotes) for k, v in value.items()}
        if isinstance(value.get("quote"), str) and (
            all_quotes or value.get("source") in sources or value.get("request") in requests
        ):
            out["quote"] = FORGOTTEN_QUOTE
        return out
    return value


@dataclass
class Plan:
    """What holds the person, found before anything is written."""

    ids: Identifiers
    snapshots: list[str] = field(default_factory=list)
    sources: frozenset[str] = frozenset()
    requests: frozenset[str] = frozenset()
    files: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    only_theirs: list[tuple[str, str]] = field(default_factory=list)

    def knows(self) -> frozenset[str]:
        """The ids of the records that are their mail's content: a case built from one is built from their mail."""
        return frozenset([*self.snapshots, *self.sources, *self.requests, *self.files, *self.questions])


def _head(sources_dir: Path, digest: Any) -> str:
    """The top of a saved text, where a mail's From line is."""
    if not digest:
        return ""
    path = sources_dir / f"{digest}.txt"
    try:
        return path.read_text(encoding="utf-8")[:1000] if path.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return ""


def _is_theirs(ids: Identifiers, sender: Any, author: Any, head: str) -> bool:
    lines = [line[5:] for line in head.splitlines()[:6] if line[:5].lower() == "from:"]
    return any(ids.from_sender(str(c)) for c in (sender, author, *lines) if c)


def plan_of(view: Any, person_id: str, root: Path) -> Plan:
    """Find everything that holds the person, from the person's own record: the mail whose sender is one of their
    addresses or names, the saved sources and requests made from it, the files kept from their mail, the questions
    they answered, and the records that exist only for them."""
    held = view.get("person", person_id)
    if held is None:
        raise StoreError(f"there is no person {person_id}")
    ids = Identifiers(held.data)
    sources_dir = root / "sources"
    snapshots = [
        s
        for s in view.list("snapshot", include_deleted=True)
        if s.data.get("message")
        and _is_theirs(
            ids, s.data["message"].get("sender"), s.data.get("author"), _head(sources_dir, s.data.get("content_hash"))
        )
    ]
    linked = {(s.data["source"], s.data["key"]) for s in snapshots}
    sources = set()
    for src in view.list("source", include_deleted=True):
        watched = src.data.get("watched") or {}
        if (watched.get("source"), watched.get("key")) in linked or _is_theirs(
            ids, None, src.data.get("author"), _head(sources_dir, src.data.get("content_hash"))
        ):
            sources.add(src.id)
    requests = {r.id for r in view.list("request", include_deleted=True) if r.data.get("source") in sources}
    only_theirs = [
        ("routing_entry", r.id)
        for r in view.list("routing_entry", include_deleted=True)
        if r.data.get("person") == person_id
    ]
    only_theirs += [
        ("style_note", r.id)
        for r in view.list("style_note", include_deleted=True)
        if r.data.get("audience") == person_id or ids.found(str(r.data.get("audience") or ""))
    ]
    only_theirs += [
        ("standing_yes", r.id)
        for r in view.list("standing_yes", include_deleted=True)
        if r.data.get("person") == person_id
    ]
    return Plan(
        ids=ids,
        snapshots=[s.id for s in snapshots],
        sources=frozenset(sources),
        requests=frozenset(requests),
        files=[f.id for f in view.list("file", include_deleted=True) if f.data.get("from_person") == person_id],
        questions=[
            q.id
            for q in view.list("question", include_deleted=True)
            if q.data.get("answer") and (q.data.get("to") == person_id or q.data.get("source") in sources)
        ],
        only_theirs=only_theirs,
    )


def fields_of(kind: str, models: Any = None) -> list[str] | None:
    """The fields of a record kind whose earlier values the ledger gives up when a forget changed one of its records:
    all of them but the id. The core's kinds, and a plugin's when the transaction's models are passed; None for a kind
    nobody defines."""
    from engine.records import REGISTRY

    model = (models if models is not None else REGISTRY).get(kind)
    return None if model is None else [name for name in model.model_fields if name != "id"]


def reach(tx: Any, store: Any, person_id: str, plan: Plan, ctx: Any, *, root: Path) -> None:
    """Apply the four rules inside the applier's transaction (the person's own record was forgotten first). Every record
    written is noted, and at the end the ledger gives up their earlier values, and also the earlier values of any record
    whose current words are clean but whose history names the person. The transaction keeps the list of what it gave
    up (`tx.redactions`), which `person.forget` writes into the ledger."""
    ids = plan.ids
    whole: set[tuple[str, str]] = set()
    changed: dict[tuple[str, str], set[str]] = {}

    def write(
        kind: str, record_id: str, changes: dict[str, Any], *, removed: bool = False, all_fields: bool = False
    ) -> None:
        """Change a record, a removed one included (brought back for the write and removed again), and note it."""
        held = tx.get(kind, record_id, include_deleted=True)
        if held is None:
            return
        differs = any(held.data.get(k) != v for k, v in changes.items())
        if not differs and not (removed and not held.deleted):
            return
        version = held.version
        if held.deleted:
            tx.undelete(kind, record_id, ctx, read_version=version)
            version += 1
        changed_record = tx.update(kind, record_id, changes, ctx, read_version=version)
        if removed or held.deleted:
            tx.delete(kind, record_id, ctx, read_version=changed_record.version)
        changed.setdefault((kind, record_id), set()).update(changes)
        if all_fields:
            whole.add((kind, record_id))

    def rewrite(kind: str, record_id: str, *, all_quotes: bool = False) -> None:
        """Replace the person's copies in a record's own words, and note it when anything changed."""
        held = tx.get(kind, record_id, include_deleted=True)
        if held is None:
            return
        data = {k: v for k, v in held.data.items() if k != "id"}
        clean = scrub(data, ids, sources=plan.sources, requests=plan.requests, all_quotes=all_quotes)
        changes = {k: v for k, v in clean.items() if v != data.get(k)}
        if changes:
            write(kind, record_id, changes)

    # R1: their mail's snapshots, sources and requests.
    from engine.set_aside import purge_snapshots

    _, _, redact = purge_snapshots(tx, root / "sources", plan.snapshots, ctx, keep_sender=False)
    whole.update((kind, record_id) for kind, record_id, _ in redact)
    for snapshot_id in plan.snapshots:
        held = tx.get("snapshot", snapshot_id, include_deleted=True)
        if held is not None and (held.data.get("message") or {}).get("sender"):
            write("snapshot", snapshot_id, {"message": {**held.data["message"], "sender": None}}, all_fields=True)
    for source_id in sorted(plan.sources):
        held = tx.get("source", source_id, include_deleted=True)
        blank = {"title": "", "content_hash": "", "url": None, "watched": None, "author": None}
        if held is not None and any(held.data.get(k) != v for k, v in blank.items()):
            write("source", source_id, blank, all_fields=True)
    for request_id in sorted(plan.requests):
        held = tx.get("request", request_id, include_deleted=True)
        if held is None:
            continue
        changes: dict[str, Any] = {"note": None}
        if held.data.get("waiting"):
            changes["waiting"] = FORGOTTEN_CONTENT
        if held.data["state"] in _UNFINISHED:
            changes.update(state="done", waiting=FORGOTTEN_CONTENT)
        write("request", request_id, {k: v for k, v in changes.items() if held.data.get(k) != v})
    for run in tx.list("run", include_deleted=True):
        if run.data.get("request") in plan.requests:
            write("run", run.id, {"knowledge": None, "error_detail": None})
    for question_id in plan.questions:
        write("question", question_id, {"answer": FORGOTTEN_ANSWER})
    # R1: the files kept from their mail (the file forget gives up the ledger's values itself).
    from engine.files import forget_record as forget_file

    for file_id in plan.files:
        held = tx.get("file", file_id, include_deleted=True)
        if held is None or (held.deleted and not held.data["sha256"]):
            continue
        version = held.version
        if held.deleted:
            tx.undelete("file", file_id, ctx, read_version=version)
            version += 1
        forget_file(store, tx, file_id, ctx, read_version=version)
    # R2: records that exist only for them.
    blanks = {
        "routing_entry": {
            "text": FORGOTTEN_CONTENT,
            "topic": FORGOTTEN_CONTENT,
            "look_up": None,
            "evidence": None,
            "more_evidence": [],
        },
        "style_note": {
            "text": FORGOTTEN_CONTENT,
            "audience": FORGOTTEN_CONTENT,
            "observation": FORGOTTEN_CONTENT,
            "evidence": None,
            "more_evidence": [],
        },
        "standing_yes": {"address": None},
    }
    for kind, record_id in plan.only_theirs:
        write(kind, record_id, blanks[kind], removed=True, all_fields=True)
    # R3: long texts, then every record's own words (a plugin's short text fields too; its long texts are its own).
    _rewrite_texts(tx, store, ids, write)
    for kind in sorted({row["kind"] for row in tx.sql("SELECT DISTINCT kind FROM records")}):
        if fields_of(kind, tx.models) is None:
            continue
        for record in tx.list(kind, include_deleted=True):
            if (kind, record.id) == ("person", person_id):
                continue
            rewrite(kind, record.id, all_quotes=kind == "changeset" and record.data.get("request") in plan.requests)
    # What the ledger gives up: every record changed above (all the fields of one kept only for them, the changed fields
    # of one that stays), then whatever else in the history still names them.
    for kind, record_id in sorted(whole):
        tx.redact_ledger(kind, record_id, fields_of(kind, tx.models) or [])
    for (kind, record_id), fields in sorted(changed.items()):
        if (kind, record_id) not in whole:
            tx.redact_ledger(kind, record_id, sorted(fields))
    _redact_history(tx, ids, plan)


def _redact_history(tx: Any, ids: Identifiers, plan: Plan) -> None:
    """Give up what the history still holds of them: a ledger entry whose earlier or later value names them (a record
    whose current words are clean was once edited from words that did), and each evidence quote that names them or is
    taken from their mail. Records the forget gave up already are skipped."""
    done = set(tx.redactions)
    fields: dict[tuple[str, str], set[str]] = {}
    plain: set[tuple[str, str]] = set()
    for row in tx.sql("SELECT kind, record_id, field, before, after, evidence FROM ledger").fetchall():
        kind, record_id, field = row["kind"], row["record_id"], row["field"]
        if (
            field is not None
            and (kind, record_id, field) not in done
            and any(row[key] is not None and ids.found(row[key]) for key in ("before", "after"))
        ):
            fields.setdefault((kind, record_id), set()).add(field)
            continue
        quote = _quote_of(row["evidence"])
        if quote is not None and ids.found(quote) and _source_of(row["evidence"]) not in plan.sources:
            plain.add((kind, record_id))
    for (kind, record_id), names in sorted(fields.items()):
        tx.redact_ledger(kind, record_id, sorted(names))
    for kind, record_id in sorted(plain):
        tx.redact_evidence(kind, record_id)
    for source_id in sorted(plan.sources):
        tx.redact_quotes_from(source_id)


def _quote_of(evidence: Any) -> str | None:
    import json

    try:
        found = json.loads(evidence) if evidence else None
    except ValueError:
        return None
    return found.get("quote") if isinstance(found, dict) and isinstance(found.get("quote"), str) else None


def _source_of(evidence: Any) -> str | None:
    import json

    try:
        found = json.loads(evidence) if evidence else None
    except ValueError:
        return None
    return found.get("source") if isinstance(found, dict) else None


def reach_list(tx: Any) -> list[list[str]]:
    """What this transaction gave up, as the list the ledger keeps: [kind, record id, field], each once, in order."""
    return [list(item) for item in dict.fromkeys(tx.redactions)]


def reached_in(entries: Any) -> tuple[dict[tuple[str, str], set[str]], set[tuple[str, str]], set[str]]:
    """What forgets listed, found in ledger entries (dicts): {(kind, id): fields}, the (kind, id) whose evidence quotes
    go, and the sources whose quotes go wherever they are."""
    fields: dict[tuple[str, str], set[str]] = {}
    evidence: set[tuple[str, str]] = set()
    cited: set[str] = set()
    for entry in entries:
        if entry.get("kind") != "person" or entry.get("field") != REACH_FIELD or not entry.get("after"):
            continue
        for kind, record_id, name in entry["after"]:
            if name == EVIDENCE_QUOTE:
                evidence.add((kind, record_id))
            elif name == QUOTED_FROM:
                cited.add(record_id)
            else:
                fields.setdefault((kind, record_id), set()).add(name)
    return fields, evidence, cited


def redact_entry(
    entry: dict[str, Any],
    reached: tuple[dict[tuple[str, str], set[str]], set[tuple[str, str]], set[str]],
) -> dict[str, Any]:
    """A ledger entry (dict) with what the forgets' lists give up applied, as the store applies it: the before and after
    values of a listed field and the evidence quote it carried."""
    fields, evidence, cited = reached
    key = (entry.get("kind"), entry.get("record_id"))
    blank_quote = key in evidence
    if entry.get("field") is not None and entry["field"] in fields.get(key, ()):
        entry = {**entry, "before": None, "after": None}
        blank_quote = True
    found = entry.get("evidence")
    if isinstance(found, dict) and found.get("source") in cited:
        blank_quote = True
    if blank_quote and isinstance(found, dict) and found.get("quote") not in (None, FORGOTTEN_QUOTE):
        entry = {**entry, "evidence": {**found, "quote": FORGOTTEN_QUOTE}}
    return entry


def _rewrite_texts(tx: Any, store: Any, ids: Identifiers, write: Any) -> None:
    """Rewrite the stored long texts of the core's own records that hold the person: each version gets the new text's
    hash, words and authorship, and the field of the record that held the old hash holds the new one."""
    from engine import texts

    made: dict[str, tuple[str, str]] = {}
    for version in tx.list("text_version", include_deleted=True):
        data = version.data
        if "/" in data["owner_kind"]:
            continue  # a plugin's text is its writer's own work
        old = data["sha256"]
        if old not in made:
            try:
                text = texts.read_text(store, old)
            except (OSError, ValueError):
                continue
            clean = ids.say(text)
            if clean == text:
                continue
            made[old] = (texts.store_text(store, clean), clean)
        digest, clean = made[old]
        original = texts.read_text(store, old)
        old_units = texts.units_of(store, data["format"], original)
        new_units = texts.units_of(store, data["format"], clean)
        spans = data["authorship"]
        if len(old_units) == len(new_units):
            authors = texts.unit_authors(spans, old_units)
            spans = [
                {**span, "words": texts.words(clean[span["start"] : span["end"]])}
                for span in texts.spans_for(new_units, authors)
            ]
        write("text_version", version.id, {"sha256": digest, "words": texts.words(clean), "authorship": spans})
        owner = tx.get(data["owner_kind"], data["owner_id"], include_deleted=True)
        if owner is not None and owner.data.get(data["field"]) == old:
            write(data["owner_kind"], owner.id, {data["field"]: digest})


@dataclass(frozen=True)
class Hashes:
    """The hashes of the files a workspace keeps outside its database, as its records hold them."""

    sources: frozenset[str]
    texts: frozenset[str]
    files: frozenset[str]


def held_hashes(rows: Any) -> Hashes:
    """What the records (`(kind, data)` pairs, removed ones included) still hold of the saved texts, the long texts and
    the stored files."""
    sources: set[str] = set()
    texts: set[str] = set()
    files: set[str] = set()
    for kind, data in rows:
        if kind in ("snapshot", "source"):
            sources.add(data.get("content_hash") or "")
        elif kind == "text_version":
            texts.add(data.get("sha256") or "")
        elif kind == "file":
            files.add(data.get("sha256") or "")
    return Hashes(frozenset(sources - {""}), frozenset(texts - {""}), frozenset(files - {""}))


def held_by(view: Any) -> Hashes:
    return held_hashes(
        (kind, record.data)
        for kind in ("snapshot", "source", "text_version", "file")
        for record in view.list(kind, include_deleted=True)
    )


def drop_gone(root: Path, before: Hashes, after: Hashes, *, files: bool = True) -> None:
    """Delete the saved texts, long texts and stored files that records held before and no longer hold."""
    from engine.files import blob_path_in

    for digest in before.sources - after.sources:
        (root / "sources" / f"{digest}.txt").unlink(missing_ok=True)
    for digest in before.texts - after.texts:
        path = root / "texts" / digest[:2] / f"{digest}.txt"
        path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            path.parent.rmdir()
    for digest in (before.files - after.files) if files else ():
        path = blob_path_in(root, digest)
        path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            path.parent.rmdir()


def forget_evals(root: Path, plan: Plan) -> list[str]:
    """Remove the private evaluation cases (`evals/`) that copy their mail or name them, and replace the person's
    copies in the shared starting files and notes the others read. Returns the names removed."""
    from engine.yaml_load import load_yaml

    folder = root / "evals"
    if not folder.is_dir():
        return []
    known = [re.compile(r"(?<![A-Za-z0-9-])" + re.escape(i) + r"(?![A-Za-z0-9])") for i in sorted(plan.knows())]
    removed = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        is_case = False
        if path.suffix in (".yaml", ".yml"):
            with contextlib.suppress(Exception):
                is_case = isinstance(load_yaml(text), dict)
        if is_case and (plan.ids.found(text) or any(rule.search(text) for rule in known)):
            path.unlink()
            removed.append(path.name)
        elif (clean := plan.ids.say(text)) != text:
            write_whole(path, clean)
    return removed
