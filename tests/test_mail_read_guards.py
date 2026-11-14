"""Reading mail from outside never lets one message stop the rest, replace another, or hide where a link goes."""

import imaplib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from engine.connectors import ConnectorContext
from engine.connectors.mailbox import MailboxSettings, message_item, read_mailbox

FIXTURES = Path(__file__).parent / "fixtures" / "network"
N = yaml.safe_load((FIXTURES / "network.yaml").read_text())
MESSAGE = (FIXTURES / "message.eml").read_bytes()
NOW = datetime(2030, 3, 4, 9, 0, tzinfo=UTC)
WEB = "https" + "://"


def html_mail(body: str, key: str = "<html-1@mail.example.com>") -> bytes:
    return (
        f"Message-ID: {key}\r\nFrom: a@example.com\r\nSubject: Links\r\nDate: Tue, 05 Mar 2030 09:15:00 +0000\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n\r\n{body}\r\n"
    ).encode()


def test_a_link_in_html_mail_shows_where_it_really_goes():
    hidden = f"{WEB}elsewhere.example.net/login"
    item = message_item(html_mail(f'<p>Sign in at <a href="{hidden}">{WEB}bank.example.com</a> today.</p>'))
    assert hidden in item.text, "the real address is in the text the assistant and the person read"
    assert f"{WEB}bank.example.com" in item.text
    plain_link = f"{WEB}same.example.com/page"
    same = message_item(html_mail(f'<a href="{plain_link}">{plain_link}</a>'))
    assert same.text.count(plain_link) == 1, "an address that is the link's own text is written once"


def test_a_link_with_words_keeps_its_address_beside_them():
    item = message_item(html_mail(f'<a href="{WEB}example.com/a">the schedule</a>'))
    assert f"the schedule ({WEB}example.com/a)" in item.text


class ServerWith(imaplib.IMAP4_SSL):
    """A stand-in IMAP server holding the messages the test gives, by UID."""

    messages: dict[int, bytes] = {}

    def __init__(self, host, port, ssl_context=None, timeout=None):
        pass

    def login(self, user, password):
        pass

    def select(self, folder, readonly=False):
        return "OK", [b"1"]

    def response(self, name):
        return name, [b"42"]

    def uid(self, command, *args):
        if command == "SEARCH":
            low = int(args[1].split()[1].split(":")[0]) if args[1].startswith("UID") else 1
            return "OK", [b" ".join(str(u).encode() for u in self.messages if u >= low)]
        return "OK", [(b"1 (BODY[] {10}", self.messages[int(args[0])]), b")"]

    def logout(self):
        pass


def mailbox(monkeypatch, tmp_path, messages: dict[int, bytes], state=None, **settings):
    ServerWith.messages = messages
    monkeypatch.setattr(imaplib, "IMAP4_SSL", ServerWith)
    monkeypatch.setenv("MAIL_PASSWORD", "x")
    config = MailboxSettings(host=N["mail_host"], user=N["mail_user"], password="env:MAIL_PASSWORD", **settings)
    return read_mailbox(config, state or {}, ConnectorContext(tmp_path))


def good(n: int) -> bytes:
    return MESSAGE.replace(b"msg-1", f"good-{n}".encode())


def broken() -> bytes:
    """A message the reader can't take: parts nested far deeper than any reader follows."""
    nest = b"".join(b"Content-Type: multipart/mixed; boundary=b%d\r\n\r\n--b%d\r\n" % (i, i) for i in range(3000))
    return b"Message-ID: <broken@mail.example.com>\r\nFrom: a@example.com\r\nSubject: S\r\n" + nest + b"text\r\n"


def test_one_message_that_cant_be_read_is_set_aside_with_its_reason_and_the_rest_are_read(monkeypatch, tmp_path):
    poll = mailbox(monkeypatch, tmp_path, {7: good(1), 8: broken(), 9: good(2)}, first_read=5)
    assert [i.key for i in poll.items] == ["<good-1@mail.example.com>", "<good-2@mail.example.com>"]
    assert [(u.key, u.reason) for u in poll.unreadable] == [("message 8", "its parts are nested too deeply to read")]
    assert poll.state["last_uid"] == 9, "the read moves past it, so the same message isn't tried on every pass"
    assert "broken@mail.example.com" not in json.dumps([u.reason for u in poll.unreadable]), "no mail content"


def test_a_message_the_server_gave_no_text_for_is_recorded_not_dropped(monkeypatch, tmp_path):
    poll = mailbox(monkeypatch, tmp_path, {7: good(1), 8: b"", 9: good(2)}, first_read=5)
    assert len(poll.items) == 2 and [u.key for u in poll.unreadable] == ["message 8"]


def test_a_message_with_no_message_id_is_recorded_not_dropped(monkeypatch, tmp_path):
    bare = b"From: a@example.com\r\nSubject: S\r\n\r\nbody\r\n"
    poll = mailbox(monkeypatch, tmp_path, {7: good(1), 8: bare}, first_read=5)
    assert len(poll.items) == 1 and [u.key for u in poll.unreadable] == ["message 8"]


def test_the_older_read_sets_a_bad_message_aside_too(monkeypatch, tmp_path):
    from engine.connectors import mailbox as module

    ServerWith.messages = {7: good(1), 8: broken()}
    monkeypatch.setattr(imaplib, "IMAP4_SSL", ServerWith)
    monkeypatch.setattr(module, "_older_uids", lambda *a, **k: [7, 8])
    monkeypatch.setenv("MAIL_PASSWORD", "x")
    config = MailboxSettings(host=N["mail_host"], user=N["mail_user"], password="env:MAIL_PASSWORD")
    found = module.read_older(config, NOW.date(), NOW.date(), 10, ConnectorContext(tmp_path))
    assert [i.key for i in found] == ["<good-1@mail.example.com>"]


def test_a_repeated_message_id_in_one_read_keeps_both_messages(monkeypatch, tmp_path):
    first = MESSAGE.replace(b"msg-1", b"twice")
    second = first.replace(b"Revised floor plan", b"Something else entirely")
    assert second != first
    poll = mailbox(monkeypatch, tmp_path, {7: first, 8: second}, first_read=5)
    assert [i.key for i in poll.items] == ["<twice@mail.example.com>", "<twice@mail.example.com>#2"]
    assert [i.title for i in poll.items] == ["Revised floor plan", "Something else entirely"]
    from engine.connectors import checked_poll

    checked_poll(poll)


# ---- what the watcher does with them ------------------------------------------------------------------------------


NOW_WATCH = datetime(2030, 3, 4, 9, 0, tzinfo=UTC)


def watched(tmp_path, *sources):
    from tests.test_watch import make

    return make(tmp_path, list(sources))


def source(source_id="s", label="Board", **settings):
    return {"id": source_id, "connector": "fake", "label": label, "first_run": "all", "settings": settings}


def asked_about_unreadable(store, source_id="s"):
    return [
        q
        for q in store.read().list("question")
        if (q.data.get("resolves") or {}).get("kind") == "watch_unreadable"
        and q.data["resolves"]["source"] == source_id
    ]


def test_items_a_read_set_aside_are_recorded_and_the_person_gets_one_line_naming_them(tmp_path):
    from engine.watch import refresh

    items = [{"key": "a", "title": "A", "text": "first"}]
    bad = [{"key": "message 8", "reason": "it couldn't be read"}]
    ws, cfg, store = watched(tmp_path, source(items=items, unreadable=bad))
    try:
        result = refresh(ws, store, cfg, "s", NOW_WATCH)
        assert result.outcome == "ok" and len(result.new) == 1, "the good item is still handed in"
        run = store.read().find("watch_run", {"source": "s"})[-1].data
        assert run["unreadable"] == bad
        (line,) = asked_about_unreadable(store)
        assert line.data["to"] == cfg.workspace.user.person and line.data["status"] == "open"
        assert line.data["title"] == "Look at the 1 item in Board that couldn't be read"
        assert "message 8 (it couldn't be read)" in line.data["text"]
        refresh(ws, store, cfg, "s", NOW_WATCH + timedelta(hours=1))
        assert len(asked_about_unreadable(store)) == 1, "the same items don't ask again"
    finally:
        store.close()


def test_a_later_read_adds_to_the_same_line_and_a_read_with_none_leaves_it(tmp_path):
    from engine.watch import refresh

    ws, cfg, store = watched(tmp_path, source(unreadable=[{"key": "message 8", "reason": "it couldn't be read"}]))
    try:
        refresh(ws, store, cfg, "s", NOW_WATCH)
        store.close()
        import yaml

        from engine.config import load_config
        from engine.storage import Store

        current = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
        current["sources"][0]["settings"]["unreadable"] = [{"key": "message 9", "reason": "it has no Message-ID"}]
        (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump(current))
        cfg = load_config(ws.config_dir, env={})
        store = Store(ws.db_path, cfg=cfg)
        refresh(ws, store, cfg, "s", NOW_WATCH + timedelta(hours=1))
        (line,) = asked_about_unreadable(store)
        assert line.data["title"] == "Look at the 2 items in Board that couldn't be read"
        assert "message 8" in line.data["text"] and "message 9 (it has no Message-ID)" in line.data["text"]
    finally:
        store.close()


def test_a_poll_with_an_unreadable_entry_missing_its_reason_is_refused():
    from engine.connectors import Poll, Unreadable, checked_poll

    checked_poll(Poll([], unreadable=[Unreadable("message 8", "it couldn't be read")]))
    with pytest.raises(ValueError, match="unreadable"):
        checked_poll(Poll([], unreadable=[Unreadable("message 8", "")]))
    with pytest.raises(ValueError, match="unreadable"):
        checked_poll(Poll([], unreadable=["message 8"]))  # type: ignore[list-item]


def test_a_source_that_crashes_is_recorded_and_the_next_one_is_still_read(tmp_path):
    from fastapi.testclient import TestClient  # noqa: F401  (the app's worker is built the way the app builds it)

    from api.app import create_app

    good = [{"key": "a", "title": "A", "text": "first"}]
    ws, cfg, store = watched(tmp_path, source("one", "Broken", crash=True), source("two", "Fine", items=good))
    store.close()
    app = create_app(ws, cfg, "t", start_worker=False)
    worker = app.state.worker
    assert worker.run_due_watches() == 2
    from engine.storage import Store

    check = Store(ws.db_path, cfg=cfg)
    try:
        broken = check.read().find("watch_run", {"source": "one"})
        assert [(r.data["outcome"], r.data["error_kind"]) for r in broken] == [("failed", "unreadable")]
        assert "boom" not in (broken[0].data["error"] or "") and "crash" not in (broken[0].data["error"] or "")
        fine = check.read().find("watch_run", {"source": "two"})
        assert [r.data["outcome"] for r in fine] == ["baseline"] or [r.data["outcome"] for r in fine] == ["ok"]
    finally:
        check.close()


def test_a_second_message_with_a_saved_ones_message_id_is_its_own_item(tmp_path):
    from engine.watch import refresh

    def mail(subject, sender, received):
        return {
            "key": "<same@example.com>",
            "title": subject,
            "text": f"From: {sender}\n\n{subject}",
            "message": {"sender": sender, "received": received},
        }

    first = mail("The real one", "First <first@example.com>", "2030-03-01T09:00:00+00:00")
    ws, cfg, store = watched(tmp_path, source(items=[first]))
    try:
        refresh(ws, store, cfg, "s", NOW_WATCH)
        store.close()
        import yaml

        from engine.config import load_config
        from engine.storage import Store

        copy = mail("Pay this instead", "Second <second@example.net>", "2030-03-02T09:00:00+00:00")
        current = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
        current["sources"][0]["settings"]["items"] = [first, copy]
        (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump(current))
        cfg = load_config(ws.config_dir, env={})
        store = Store(ws.db_path, cfg=cfg)
        result = refresh(ws, store, cfg, "s", NOW_WATCH + timedelta(hours=1))
        saved = {s.data["key"]: s.data["title"] for s in store.read().find("snapshot", {"source": "s"})}
        assert saved == {"<same@example.com>": "The real one", "<same@example.com>#2": "Pay this instead"}
        assert len(result.new) == 1 and not result.changed, "the copy is new, and nothing was changed"
        again = refresh(ws, store, cfg, "s", NOW_WATCH + timedelta(hours=2))
        assert not again.new and not again.changed, "read again, both are what was saved"
    finally:
        store.close()


def test_a_sender_whose_display_name_changed_is_still_the_same_message(tmp_path):
    from engine.watch import refresh

    def mail(name):
        return {
            "key": "<same@example.com>",
            "title": "Subject",
            "text": "Same words",
            "message": {"sender": f"{name} <who@example.com>", "received": "2030-03-01T09:00:00+00:00"},
        }

    ws, cfg, store = watched(tmp_path, source(items=[mail("Old Name")]))
    try:
        refresh(ws, store, cfg, "s", NOW_WATCH)
        store.close()
        from engine.config import load_config
        from engine.storage import Store

        current = yaml.safe_load((ws.config_dir / "watch.yaml").read_text())
        current["sources"][0]["settings"]["items"] = [mail("New Name")]
        (ws.config_dir / "watch.yaml").write_text(yaml.safe_dump(current))
        cfg = load_config(ws.config_dir, env={})
        store = Store(ws.db_path, cfg=cfg)
        result = refresh(ws, store, cfg, "s", NOW_WATCH + timedelta(hours=1))
        assert not result.new and not result.changed
        assert [s.data["key"] for s in store.read().find("snapshot", {"source": "s"})] == ["<same@example.com>"]
    finally:
        store.close()
