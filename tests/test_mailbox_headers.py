"""The built-in mailbox reads a year of headers on its first read (S-0628): with IMAP's own header fetch, no text
and no files, over the folder the source reads, at most `watch.first_headers_max_items`, kept as headers, never as
inputs."""

from __future__ import annotations

import imaplib
from datetime import UTC, date, datetime, timedelta

import yaml

from engine.config import load_config
from engine.connectors import ConnectorContext
from engine.connectors.mailbox import MailboxSettings, read_headers
from engine.storage import Store
from engine.watch import refresh
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

NOW = datetime(2030, 3, 4, 9, 0, tzinfo=UTC)
HOST = "mail.example.com"
USER = "reader@example.com"
SECRET_WORDS = "words that only a full fetch would bring"


def raw(n: int, days: int, *, subject: str | None = None, to: str = "friend@example.com") -> bytes:
    sent = (NOW - timedelta(days=days)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    return (
        f"Message-ID: <h{n}@mail.example.com>\r\nFrom: Sender {n} <sender{n}@example.com>\r\nTo: {to}\r\n"
        f"Subject: {subject or f'Subject {n}'}\r\nDate: {sent}\r\n\r\n{SECRET_WORDS}\r\n"
    ).encode()


class Recorded(imaplib.IMAP4_SSL):
    """A stand-in server holding a recorded fictional mailbox: UID -> (message, opened). It answers a header fetch with
    the requested fields alone and records every command, so a test can see that no text was asked for."""

    mailbox: dict[int, tuple[bytes, bool]] = {}
    commands: list[tuple] = []
    flags_after = False  # some servers say the flags after the header's text, in the bytes that close the answer

    def __init__(self, host, port, ssl_context=None, timeout=None):
        pass

    def login(self, user, password):
        pass

    def select(self, folder, readonly=False):
        return "OK", [b"1"]

    def response(self, name):
        return name, [b"42"]

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u in self.mailbox)]
        wanted = [int(u) for u in args[0].split(",")]
        if "BODY.PEEK[HEADER.FIELDS" not in args[1]:
            return "OK", [(b"1 (BODY[] {1}", self.mailbox[wanted[0]][0]), b")"]
        parts: list = []
        for uid in wanted:
            message, opened = self.mailbox[uid]
            head = message.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
            flags = b"\\Seen" if opened else b""
            if self.flags_after:
                opening = f"{uid} (UID {uid} BODY[HEADER.FIELDS (...)] {{{len(head)}}}".encode()
                parts += [(opening, head), f" FLAGS ({flags.decode()}))".encode()]
            else:
                opening = (
                    f"{uid} (UID {uid} FLAGS ({flags.decode()}) BODY[HEADER.FIELDS (...)] {{{len(head)}}}".encode()
                )
                parts += [(opening, head), b")"]
        return "OK", parts

    def logout(self):
        pass


def serve(monkeypatch, mailbox: dict[int, tuple[bytes, bool]]) -> None:
    Recorded.mailbox, Recorded.commands = mailbox, []
    monkeypatch.setattr(imaplib, "IMAP4_SSL", Recorded)
    monkeypatch.setenv("MAIL_PASSWORD", "x")


def settings(**more) -> MailboxSettings:
    return MailboxSettings(host=HOST, user=USER, password="env:MAIL_PASSWORD", **more)


def test_the_headers_come_from_the_headers_fetch_alone_with_no_text_and_no_files(monkeypatch, tmp_path):
    serve(monkeypatch, {7: (raw(1, 30), True), 8: (raw(2, 60), False), 9: (raw(3, 90), False)})
    found = read_headers(settings(), (NOW - timedelta(days=365)).date(), NOW.date(), 10, ConnectorContext(tmp_path))
    assert [i.key for i in found] == ["<h1@mail.example.com>", "<h2@mail.example.com>", "<h3@mail.example.com>"]
    one = found[0]
    assert (one.title, one.text, one.files) == ("Subject 1", "", ())
    assert one.message.sender == "Sender 1 <sender1@example.com>"
    assert one.message.participants == ("friend@example.com",)
    assert (one.message.unread, found[1].message.unread, one.message.where) == (False, True, "inbox")
    fetches = [c for c in Recorded.commands if c[0] == "FETCH"]
    assert fetches and all("HEADER.FIELDS" in c[2] and "BODY.PEEK[]" not in c[2] for c in fetches)
    assert SECRET_WORDS not in repr(found)


def test_at_most_the_newest_max_items_are_read(monkeypatch, tmp_path):
    serve(monkeypatch, {u: (raw(u, u), False) for u in range(1, 8)})
    found = read_headers(settings(), date(2029, 1, 1), NOW.date(), 3, ConnectorContext(tmp_path))
    assert [i.key for i in found] == [f"<h{n}@mail.example.com>" for n in (5, 6, 7)]


def test_a_message_with_no_message_id_is_left_out_and_the_rest_are_read(monkeypatch, tmp_path):
    bare = b"From: a@example.com\r\nSubject: S\r\n\r\nbody\r\n"
    serve(monkeypatch, {7: (raw(1, 5), False), 8: (bare, False), 9: (raw(2, 6), False)})
    found = read_headers(settings(), date(2029, 1, 1), NOW.date(), 10, ConnectorContext(tmp_path))
    assert len(found) == 2


def test_the_first_read_is_followed_by_the_year_of_headers_kept_as_headers_and_no_input_comes_of_them(
    monkeypatch, tmp_path
):
    serve(monkeypatch, {7: (raw(1, 20), False), 8: (raw(2, 200), True), 9: (raw(3, 300), False)})
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    (ws.config_dir / "watch.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sorting": "rules",
                "sources": [
                    {
                        "id": "box",
                        "connector": "mailbox",
                        "label": "Mailbox",
                        "settings": {"host": HOST, "user": USER, "password": "env:MAIL_PASSWORD", "first_read": 1},
                    }
                ],
            }
        )
    )
    cfg = load_config(ws.config_dir, env={})
    store = Store(ws.db_path, cfg=cfg)
    refresh(ws, store, cfg, "box", now=NOW)
    view = store.read()
    kept = {h.data["key"]: h.data for h in view.find("mail_header", {"source": "box"})}
    assert len(kept) == 2, "the year of headers was kept, less the message the first read holds"
    assert all(h["message"]["sender"] for h in kept.values()) and all(
        SECRET_WORDS not in repr(h) for h in kept.values()
    )
    held = {s.data["key"] for s in view.find("snapshot", {"source": "box"})}
    assert not held & set(kept), "a message the first read holds is not kept again as a header"
    assert any(c[0] == "FETCH" and "HEADER.FIELDS" in c[2] for c in Recorded.commands)
    inputs = [i for i in view.find("input", {"source": "box"})]
    assert not [i for i in inputs if i.data.get("key") in kept], "no input was made from a header"


def test_a_server_that_says_the_flags_after_the_header_text_still_tells_what_was_opened(monkeypatch, tmp_path):
    serve(monkeypatch, {7: (raw(1, 30), True), 8: (raw(2, 60), False)})
    monkeypatch.setattr(Recorded, "flags_after", True)
    found = read_headers(settings(), date(2029, 1, 1), NOW.date(), 10, ConnectorContext(tmp_path))
    assert [i.message.unread for i in found] == [False, True]


def test_a_header_read_past_its_deadline_keeps_the_newest_batch_and_says_it_stopped(monkeypatch, tmp_path):
    from engine.connectors import Poll
    from engine.connectors import mailbox as mb

    monkeypatch.setattr(mb, "_HEADER_BATCH", 2)
    serve(monkeypatch, {u: (raw(u, u), False) for u in range(1, 6)})
    context = ConnectorContext(tmp_path, fetch_deadline_seconds=-1.0)
    found = read_headers(settings(), date(2029, 1, 1), NOW.date(), 10, context)
    assert isinstance(found, Poll) and found.stopped is not None
    assert [i.key for i in found.items] == [f"<h{n}@mail.example.com>" for n in (4, 5)]
    assert len([c for c in Recorded.commands if c[0] == "FETCH"]) == 1
