"""The text of a source item as the app reads it: its own words as plain text, with the files it carries read as text
and added after them. This is the one place the text of every watched item passes before it is compared, stored or
handed to the assistant, so markup that came in a part labeled as plain text (or in a description) is turned into text
here (`engine/html_text.py`) and nothing after it ever sees a tag.

A connector hands files as bytes and never parses them; the core reads each with its readers (a plugin's reader for
the type first), cuts the text at the configured size with a mark, and appends it after the item's text, one block per
file. The item's text is what the assistant reads as outside content, so the files' words are marked like the rest.
A file that came by mail is also kept as a file record (untrusted, at the source's data level, recording the person it
came from), once for the same bytes, name and sender; one that can't be kept (a type or size the file limits refuse)
is named after the item's text with the reason.
A file that can't be read is named in its block with the reason, and is an issue about its reader on Today; a type no
reader takes is named the same way, in the item it came with, and is never a question: nothing is asked of the person
about a file they can't do anything with.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from engine.connectors import SourceItem
from engine.extract import Unsupported, health, read_file
from engine.extract.core import ExtractError
from engine.html_text import as_text
from engine.storage import WriteContext

_FLAGGER = WriteContext(actor="watcher", trust="trusted", op="watch.unsupported_file")
_KEEPER = WriteContext(actor="watcher", trust="untrusted", op="file.add")
MB = 1024 * 1024


def with_files_read(
    ws: Any, store: Any, cfg: Any, item: SourceItem, where: str, *, keep_at_level: str | None = None
) -> SourceItem:
    """The item with its own text as plain text, its files' text added after it and its files taken out (they are
    read now, once). With `keep_at_level`, the files of a mail message are also kept as file records at that data
    level, recording the person the message came from, so nothing that arrived by mail is lost."""
    text = as_text(item.text)
    if text != item.text:
        item = replace(item, text=text)
    if not item.files:
        return item
    limits = cfg.storage.files
    blocks = []
    sender = _sender_person(store, cfg, item) if keep_at_level and item.message is not None else None
    for file in item.files:
        name = " ".join(file.name.split()) or "unnamed file"
        if keep_at_level and item.message is not None and (why := _keep(store, cfg, file, name, sender, keep_at_level)):
            blocks.append(f"Not kept as a file: {name} ({why})")
        try:
            read = read_file(
                file.data,
                name,
                file.media_type,
                max_chars=limits.read_max_chars,
                max_bytes=int(limits.read_max_mb * MB),
                plugin=store.plugins.read_with_plugins,
            )
        except Unsupported as err:
            blocks.append(f"Attached file: {name} (not read: {err.reason})")
            health.flag_unsupported(ws, err.media_type)
        except ExtractError as err:
            blocks.append(f"Attached file: {name} (not read: {err.reason})")
            if err.kind is not None:
                health.note_read(ws, err.kind, err.reason)
        else:
            health.note_read(ws, read.kind, None)
            blocks.append(f"Attached file: {name}\n{read.text}\nEnd of attached file: {name}")
    text = "\n\n".join(part for part in (item.text.strip(), *blocks) if part)
    return replace(item, text=text, files=())


def _sender_person(store: Any, cfg: Any, item: SourceItem) -> str | None:
    """The person id the mail came from, when its sender names exactly one known person."""
    from engine.names import People

    sender = (item.message.sender if item.message is not None else None) or item.author
    if not sender:
        return None
    found = People(store, cfg).resolve(sender)
    return found.person if found.status == "ok" else None


def _keep(store: Any, cfg: Any, file: Any, name: str, person: str | None, level: str) -> str | None:
    """Keep one attachment as an untrusted file record (once for the same bytes, name and sender); why it could not
    be kept, or None."""
    import hashlib

    from engine.files import add_file
    from engine.storage import StoreError

    digest = hashlib.sha256(file.data).hexdigest()
    if any(
        f.data["name"] == name and f.data["from_person"] == person
        for f in store.read().find("file", {"sha256": digest})
    ):
        return None
    try:
        add_file(
            store,
            cfg,
            file.data,
            name=name,
            media_type=file.media_type,
            origin="tool",
            from_person=person,
            data_level=level,
            preserve_generic=True,
            context=_KEEPER,
        )
    except StoreError as err:
        return str(err)
    return None
