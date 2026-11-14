"""The ops that give up the earlier values of a record's fields in the ledger (design 5.2, 12.4), in one place.

A redacting op blanks the before and after values of some fields of the records it removes. Two computers sharing a
synced folder compare their ledgers line by line, so both the comparison and the loading computer need to know which
ops redact and which fields they blank; they read it here rather than each knowing the ops.
"""

from __future__ import annotations

from typing import Any


def redacting_ops() -> dict[str, dict[str, list[str]]]:
    """{op name: {record kind: fields whose earlier values the ledger gives up}} for every redacting op."""
    from engine import people_forget
    from engine.files import CHANGESET_FIELDS, FORGET_FIELDS
    from engine.set_aside import DELETE_OP, REDACTED_FIELDS

    # A person's forget names what else it gave up in the ledger itself (`forget_reach.REACH_FIELD`): the entries that
    # say which records and fields, so this table holds only the person's own fields for it.
    return {
        DELETE_OP: REDACTED_FIELDS,
        "file.forget": {"file": FORGET_FIELDS, "changeset": CHANGESET_FIELDS},
        "person.forget": {"person": people_forget.FORGET_FIELDS},
    }


def rebuild_problem(ws: Any) -> str | None:
    """Why the readable export's history can't be rebuilt after a forget, or None. Asked before a forget changes
    anything, so a refusal leaves everything as it was."""
    from engine.storage.export import history_problem

    return history_problem(ws.root)


def rebuild_export(ws: Any, store: Any) -> None:
    """After a forget: write the readable export again, then replace the workspace's git history with a fresh one
    holding only the current state, so the forgotten values are in no earlier version (design 5.2). A workspace that
    keeps no git history only has its export written again."""
    from engine.set_aside import refresh_export
    from engine.storage.export import rebuild_history

    refresh_export(ws, store)
    rebuild_history(ws.root, "Export")


def redacted_fields(entry: dict[str, Any]) -> list[str] | None:
    """The fields a ledger entry's op redacts on its record, or None when the entry is not from a redacting op."""
    name = str(entry.get("op") or "").split("#", 1)[0]
    return redacting_ops().get(name, {}).get(entry.get("kind"))


def undo_problem(tx: Any, entries: list[dict[str, Any]]) -> str | None:
    """Why undoing these ledger entries is refused, or None. A record whose content a redacting op gave up (a deletion,
    a forgotten file, or any record a person's forget listed) is never brought back by an Undo of an earlier change (or
    of the redaction itself): its fields stay forgotten, not restored."""
    import json

    from engine.forget_reach import REACH_FIELD, reached_in

    ops = redacting_ops()
    listed = reached_in(
        {"kind": "person", "field": REACH_FIELD, "after": json.loads(row["after"])}
        for row in tx.sql(
            "SELECT after FROM ledger WHERE kind='person' AND field=? AND after IS NOT NULL", (REACH_FIELD,)
        )
    )
    for kind, record_id in sorted({(e["kind"], e["record_id"]) for e in entries}):
        for row in tx.sql("SELECT DISTINCT op FROM ledger WHERE kind=? AND record_id=?", (kind, record_id)):
            fields = ops.get(str(row["op"]).split("#", 1)[0], {}).get(kind)
            if fields is not None:
                return f"{kind} {record_id} was forgotten ({', '.join(fields)}: forgotten, not restored)"
        gone = sorted(
            set(listed[0].get((kind, record_id), ())) | ({"evidence"} if (kind, record_id) in listed[1] else set())
        )
        if gone:
            return f"{kind} {record_id} was forgotten ({', '.join(gone)}: forgotten, not restored)"
    return None
