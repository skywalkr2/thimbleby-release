# ruff: noqa: F811
"""An outward act does exactly what was approved, and Undo takes back only what the act did (design 6.7, 6.12).

The person's yes covers what the act's account resolves to, so a mailbox that took an account's name never carries an
act approved for another. A move that was begun and not finished is uncertain, never failed, and carrying it out again
copies nothing twice. Undo takes off only the marks the act put on, in the mailbox and folders the act ran with. An
answer to an invitation echoes the organizer's own revision number, and a newer revision ends the yes.

The mail servers are the recording stand-ins of the mailbox channel's tests; nothing reaches a network. Names, ids and
addresses come from the fixtures; every address is on example.com."""

from __future__ import annotations

import imaplib
from datetime import UTC, date, datetime
from typing import Any

import pytest

from engine import acts, itip, source_entries
from engine.applier import apply_as_person
from engine.channels import ChannelFailed, ChannelSent, ChannelUndone, ChannelUnknown
from engine.config.schema import WatchSource
from engine.connectors import calendar as calendar_files
from tests.test_act_actions import ACCOUNT, END, MAILBOX, START, calendar_entry, saved_message, update_record
from tests.test_mailbox_channel import (  # noqa: F401  (the fixtures)
    ME,
    ORIGINAL,
    channel,
    env,
    mailbox_act,
    ran,
    ready_target,
    sent_message,
    servers,
    uid_commands,
)
from tests.test_publisher import Env

SECOND = "<two@example.com>"
ELSEWHERE = "someone.else@example.com"
NO = ("NO", [b"refused"])
COPY_ONLY = ("IMAP4REV1", "UIDPLUS")  # a server with no MOVE: copy, mark deleted, expunge


def mailbox_source(env: Env) -> WatchSource:
    return next(s for s in env.cfg.watch.sources if s.id == MAILBOX)


def set_mailbox(env: Env, **settings: Any) -> None:
    """The mailbox behind the account's name is set up differently now."""
    source = mailbox_source(env)
    source.settings = {**source.settings, **settings}


def archive_act(env: Env, *keys: str) -> str:
    about = [saved_message(env, key) for key in keys or ("thread",)]
    return ready_target(env, {"kind": "mailbox", "action": "archive", "about": about}, channel="mailbox")


def again(env: Env, act_id: str) -> None:
    """The person has an uncertain act carried out again."""
    apply_as_person(env.store, env.cfg, [{"op": "act.resend", "id": act_id}], "Send it again")


# ---- O1: the yes covers what the account resolves to ----------------------------------------------------------------


def test_a_yes_never_carries_a_message_through_another_mailbox_that_took_the_accounts_name(env, servers):
    outgoing, _ = servers
    act_id = env.ready(channel="mailbox", account=ACCOUNT)
    set_mailbox(env, user=ELSEWHERE)  # the same account name, another mailbox and another address to send from

    assert env.publisher.send(act_id).status == "stale"
    data = env.act(act_id)
    assert data["why"] == ["account"] and data["approved"] is None
    assert outgoing.calls == [] and outgoing.delivered == []  # no server was even connected to

    # What changed is there to show: the address it would send from, before and now.
    now = acts.current_shown(env.store.read(), env.store.plugins, data)
    changed = {d.field: (d.before, d.after) for d in acts.differences(data["was_approved"]["shown"], now)}
    assert changed["sender"] == (ME, ELSEWHERE) and changed["user"] == (ME, ELSEWHERE)


def test_a_changed_send_from_address_or_server_ends_the_yes_and_a_new_password_does_not(env, servers, monkeypatch):
    outgoing, _ = servers
    for change in ({"from_address": ELSEWHERE}, {"host": "imap.other." + "example.com"}, {"smtp_host": "smtp.other"}):
        act_id = env.ready(channel="mailbox", account=ACCOUNT)
        before = dict(mailbox_source(env).settings)
        set_mailbox(env, **change)
        assert env.publisher.send(act_id).status == "stale", change
        mailbox_source(env).settings = before
    assert outgoing.delivered == []

    monkeypatch.setenv("NEW_MAIL_PASSWORD", "a-new-app-password")
    act_id = env.ready(channel="mailbox", account=ACCOUNT)
    set_mailbox(env, password="env:NEW_MAIL_PASSWORD")  # the same mailbox, signed in to with a new password
    assert env.publisher.send(act_id).status == "sent"
    assert outgoing.of("login")[-1] == ("login", ME, "a-new-app-password") and len(outgoing.delivered) == 1


def test_a_changed_archive_folder_ends_the_yes_of_an_archive_and_of_nothing_else(env, servers):
    outgoing, mail = servers
    mail.put("INBOX", ORIGINAL)
    archive = archive_act(env)
    message = env.ready(channel="mailbox", account=ACCOUNT)
    set_mailbox(env, archive_folder="Projects")

    assert env.publisher.send(archive).status == "stale" and env.act(archive)["why"] == ["account"]
    assert mail.ids("INBOX") == [ORIGINAL] and mail.ids("Projects") == [] and uid_commands(mail, "MOVE") == []
    assert env.publisher.send(message).status == "sent"  # a message goes nowhere near the archive folder

    env.yes(archive)  # shown the new folder, the person says yes again
    assert env.publisher.send(archive).status == "sent" and mail.ids("Projects") == [ORIGINAL]


def test_an_account_with_no_mailbox_behind_it_any_more_ends_the_yes(env, servers):
    outgoing, _ = servers
    act_id = env.ready(channel="mailbox", account=ACCOUNT)
    mailbox_source(env).settings = {}  # no longer a mailbox that is set up
    assert env.publisher.send(act_id).status == "stale" and outgoing.calls == []


def test_undo_works_in_the_folders_the_act_ran_with_and_never_in_another_mailbox(env, servers):
    _, mail = servers
    mail.put("INBOX", ORIGINAL)
    act_id = archive_act(env)
    assert env.publisher.send(act_id).status == "sent" and mail.ids("Old Mail") == [ORIGINAL]
    did = env.act(act_id)["did"]
    assert (did["from"], did["to"], did["moved"]) == ("INBOX", "Old Mail", [ORIGINAL])

    set_mailbox(env, archive_folder="Projects", folder="Projects")  # the same mailbox, other folders in its settings
    env.person_op("act.undo", act_id)
    assert env.publisher.undo(act_id).status == "undone"
    assert mail.ids("INBOX") == [ORIGINAL] and mail.ids("Old Mail") == [] and mail.ids("Projects") == []


def test_undo_is_refused_when_the_accounts_name_now_means_another_mailbox(env, servers):
    _, mail = servers
    mail.put("INBOX", ORIGINAL)
    act_id = archive_act(env)
    assert env.publisher.send(act_id).status == "sent"
    logins = mail.logins
    set_mailbox(env, user=ELSEWHERE)

    env.person_op("act.undo", act_id)
    assert env.publisher.undo(act_id).status == "failed"
    data = env.act(act_id)
    assert data["status"] == "sent" and data["undo_failure"]["kind"] == "refused"
    assert mail.logins == logins and mail.ids("Old Mail") == [ORIGINAL]  # the other mailbox was never signed in to


# ---- O3: a move begun and not finished is uncertain, and a retry copies nothing twice --------------------------------


@pytest.mark.parametrize(("stuck", "step"), [("STORE", "copied"), ("EXPUNGE", "marked")])
def test_a_move_that_copied_and_could_not_finish_is_uncertain_and_a_retry_does_not_copy_again(
    env, servers, stuck, step
):
    _, mail = servers
    mail.capabilities = COPY_ONLY
    mail.put("INBOX", ORIGINAL)
    act_id = archive_act(env)
    mail.refuse[stuck] = NO

    result = env.publisher.send(act_id)
    data = env.act(act_id)
    assert result.status == "uncertain" and data["status"] == "uncertain" and data["failure"] is None
    assert data["why"] == ["part_done"] and "Old Mail" in data["uncertain_reason"]
    assert (data["did"]["to"], data["did"]["unsure"]) == ("Old Mail", {"id": ORIGINAL, "step": step})
    assert mail.ids("INBOX") == [ORIGINAL] and mail.ids("Old Mail") == [ORIGINAL]  # in both, as recorded

    mail.refuse.clear()
    again(env, act_id)
    assert env.publisher.send(act_id).status == "sent"
    assert len(uid_commands(mail, "COPY")) == 1  # the retry found it in the destination and copied nothing
    assert mail.ids("INBOX") == [] and mail.ids("Old Mail") == [ORIGINAL]
    assert env.act(act_id)["did"]["moved"] == [ORIGINAL] and env.act(act_id)["uncertain_reason"] is None

    env.person_op("act.undo", act_id)  # and what the two attempts did together can be taken back
    assert env.publisher.undo(act_id).status == "undone"
    assert mail.ids("INBOX") == [ORIGINAL] and mail.ids("Old Mail") == []


def test_a_connection_lost_after_the_copy_is_uncertain_with_the_step_reached(servers):
    _, mail = servers
    mail.capabilities = COPY_ONLY
    mail.put("INBOX", ORIGINAL)
    mail.refuse["STORE"] = imaplib.IMAP4.abort("the connection dropped")
    act = mailbox_act("archive")

    answer = channel().send(act, "key-1")
    assert isinstance(answer, ChannelUnknown) and not isinstance(answer, ChannelFailed)
    assert answer.did["unsure"] == {"id": ORIGINAL, "step": "copied"} and answer.did["to"] == "Old Mail"

    mail.refuse.clear()
    assert isinstance(channel().send(ran(act, answer), "key-2"), ChannelSent)
    assert len(uid_commands(mail, "COPY")) == 1 and mail.ids("Old Mail") == [ORIGINAL] and mail.ids("INBOX") == []


def test_a_move_whose_answer_was_lost_is_found_done_on_the_retry(servers):
    _, mail = servers
    found = mail.put("INBOX", ORIGINAL)
    act = mailbox_act("archive")

    class Lost(imaplib.IMAP4.abort):
        """The server moved the message and the answer never arrived."""

    def move_then_drop() -> None:
        mail.folders["INBOX"].remove(found)
        mail.put("Old Mail", ORIGINAL)
        raise Lost("no answer")

    mail.refuse["MOVE"] = move_then_drop
    answer = channel().send(act, "key-1")
    assert isinstance(answer, ChannelUnknown) and answer.did["unsure"] == {"id": ORIGINAL, "step": "moving"}

    mail.refuse.clear()
    retried = channel().send(ran(act, answer), "key-2")
    assert isinstance(retried, ChannelSent) and retried.did["moved"] == [ORIGINAL]
    assert len(uid_commands(mail, "MOVE")) == 1 and mail.ids("Old Mail") == [ORIGINAL]


def test_a_second_message_that_fails_after_the_first_moved_is_part_done_not_a_failure(servers):
    _, mail = servers
    mail.put("INBOX", ORIGINAL)
    mail.put("INBOX", SECOND)
    act = mailbox_act("archive", (ORIGINAL, SECOND))
    moves: list[int] = []

    def second_refused() -> Any:
        moves.append(1)
        return NO if len(moves) > 1 else None

    mail.refuse["MOVE"] = second_refused
    answer = channel().send(act, "key-1")
    assert isinstance(answer, ChannelUnknown) and answer.did["moved"] == [ORIGINAL] and "unsure" not in answer.did
    assert mail.ids("INBOX") == [SECOND] and mail.ids("Old Mail") == [ORIGINAL]

    mail.refuse.clear()
    retried = channel().send(ran(act, answer), "key-2")
    assert isinstance(retried, ChannelSent) and retried.did["moved"] == [ORIGINAL, SECOND]
    assert mail.ids("Old Mail") == [ORIGINAL, SECOND] and len(uid_commands(mail, "MOVE")) == 3  # one each, one refused


def test_a_step_the_server_refuses_before_anything_changed_is_still_a_plain_failure(servers):
    _, mail = servers
    mail.capabilities = COPY_ONLY
    mail.put("INBOX", ORIGINAL)
    mail.refuse["COPY"] = NO
    answer = channel().send(mailbox_act("archive"), "key-1")
    assert isinstance(answer, ChannelFailed) and answer.kind == "refused"
    assert mail.ids("INBOX") == [ORIGINAL] and mail.ids("Old Mail") == []
    assert mail.folders["INBOX"][0].flags == set()


def test_a_message_someone_else_moved_is_not_taken_for_the_acts_own_work(servers):
    _, mail = servers
    mail.put("Old Mail", ORIGINAL)  # already in the archive, and not by this act
    answer = channel().send(mailbox_act("archive"), "key-1")
    assert isinstance(answer, ChannelFailed) and "moved or deleted" in answer.reason
    assert mail.ids("Old Mail") == [ORIGINAL] and uid_commands(mail, "MOVE") == []


# ---- O4: undo takes off only what the act put on ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "extra", "flag"), [("label", {"label": "Needs review"}, "Needs-review"), ("mark_read", {}, "\\Seen")]
)
def test_undo_takes_a_mark_off_only_the_messages_the_act_put_it_on(env, servers, action, extra, flag):
    _, mail = servers
    had_it, fresh = mail.put("INBOX", ORIGINAL), mail.put("INBOX", SECOND)
    had_it.flags.add(flag)  # the person marked this one themselves, before the act
    about = [saved_message(env, "thread"), saved_message(env, "two")]
    act_id = ready_target(env, {"kind": "mailbox", "action": action, "about": about, **extra}, channel="mailbox")

    assert env.publisher.send(act_id).status == "sent"
    assert had_it.flags == {flag} and fresh.flags == {flag}
    assert env.act(act_id)["did"]["flagged"] == [SECOND]  # the act added it to one message only
    assert [c[2] for c in uid_commands(mail, "STORE")] == [str(fresh.uid)]

    env.person_op("act.undo", act_id)
    assert env.publisher.undo(act_id).status == "undone"
    assert had_it.flags == {flag} and fresh.flags == set()  # the person's own mark is still there


def test_an_act_that_added_nothing_takes_nothing_back(servers):
    _, mail = servers
    found = mail.put("INBOX", ORIGINAL)
    found.flags.add("\\Seen")
    act = mailbox_act("mark_read")
    sent = channel().send(act, "key-1")
    assert isinstance(sent, ChannelSent) and sent.did["flagged"] == [] and uid_commands(mail, "STORE") == []
    assert channel().undo(ran(act, sent), ORIGINAL) == ChannelUndone() and found.flags == {"\\Seen"}


def test_a_mark_is_never_taken_off_when_nothing_says_the_act_put_it_on(servers):
    _, mail = servers
    found = mail.put("INBOX", ORIGINAL)
    found.flags.add("\\Seen")
    answer = channel().undo(mailbox_act("mark_read"), ORIGINAL)  # an act that ran before what it changed was kept
    assert isinstance(answer, ChannelFailed) and answer.kind == "refused"
    assert found.flags == {"\\Seen"} and uid_commands(mail, "STORE") == []


def test_a_server_that_will_not_say_how_a_message_is_marked_gets_no_mark(servers):
    _, mail = servers
    found = mail.put("INBOX", ORIGINAL)
    mail.refuse["FETCH"] = NO
    answer = channel().send(mailbox_act("label", label="Later"), "key-1")
    assert isinstance(answer, ChannelFailed) and answer.kind == "refused" and found.flags == set()


# ---- O5: an answer echoes the organizer's revision number ------------------------------------------------------------

NOW = datetime(2030, 3, 4, 9, 0, tzinfo=UTC)


def invitation_file(sequence: int | None) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Fictional//Calendar//EN", "METHOD:REQUEST", "BEGIN:VEVENT"]
    lines += ["UID:planning@calendar.example.com", "DTSTAMP:20300301T080000Z", "DTSTART:20300309T150000Z"]
    lines += ["DTEND:20300309T160000Z", "SUMMARY:Planning session", "ORGANIZER:mailto:organizer@example.com"]
    lines += [f"ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:{ME}"]
    lines += [f"SEQUENCE:{sequence}"] if sequence is not None else []
    return "\n".join([*lines, "END:VEVENT", "END:VCALENDAR", ""])


def kept_entry(env: Env, sequence: int | None) -> Any:
    """The calendar entry kept from a read of a calendar file that holds the invitation at that revision."""
    source = WatchSource(id="calendar", connector="calendar", label="Work calendar")
    items = calendar_files.items(invitation_file(sequence), NOW, 30, 30)
    assert [i.event.sequence for i in items] == [sequence]
    source_entries.keep(env.store, env.cfg, source, items, NOW)
    (entry,) = env.store.read().find("event", {"source": "calendar"})
    return entry


def test_the_organizers_revision_number_is_kept_from_the_calendar_to_the_entry(env):
    assert kept_entry(env, 3).data["sequence"] == 3
    assert kept_entry(env, 4).data["sequence"] == 4  # a later read of a newer revision moves the same entry on
    assert acts.service_ref(env.store.read(), kept_entry(env, 4).id)["sequence"] == 4


def test_a_calendar_that_gives_no_revision_number_leaves_it_unknown(env):
    assert kept_entry(env, None).data.get("sequence") is None


def answer_to(env: Env, entry: str) -> str:
    target = {"kind": "calendar", "action": "answer", "about": [entry], "answer": "accepted"}
    return ready_target(env, target, channel="mailbox")


def reply_of(outgoing: Any, n: int = 0) -> str:
    (reply,) = [p for p in sent_message(outgoing, n).iter_attachments()]
    return reply.get_content()


def test_an_answer_echoes_the_revision_the_person_was_answering(env, servers):
    outgoing, _ = servers
    entry = calendar_entry(env, "uid-9", source=saved_message(env, "invite"), sequence=3)
    assert env.publisher.send(answer_to(env, entry)).status == "sent"
    text = reply_of(outgoing)
    assert "SEQUENCE:3" in text and "SEQUENCE:0" not in text
    assert itip.read_invitation(text).sequence == 3  # as the organizer's calendar will read it


def test_a_newer_revision_of_the_invitation_ends_a_yes_given_to_the_older_one(env, servers):
    outgoing, _ = servers
    entry = calendar_entry(env, "uid-9", source=saved_message(env, "invite"), sequence=3)
    act_id = answer_to(env, entry)
    update_record(env, "event", entry, sequence=4)  # the organizer changed it after the yes

    assert env.publisher.send(act_id).status == "stale"
    assert env.act(act_id)["why"] == ["about"] and outgoing.delivered == []

    env.yes(act_id)
    assert env.publisher.send(act_id).status == "sent" and "SEQUENCE:4" in reply_of(outgoing)


def test_an_answer_writes_no_revision_number_nobody_gave(env, servers):
    outgoing, _ = servers
    entry = calendar_entry(env, "uid-9", source=saved_message(env, "invite"))  # its source gave no revision number
    assert env.publisher.send(answer_to(env, entry)).status == "sent"
    assert "SEQUENCE" not in reply_of(outgoing) and "UID:uid-9" in reply_of(outgoing)


# ---- H5-32: an answer to one date of a repeating invitation names that date ------------------------------------------


def occurrence_reply(env: Env, servers: Any, key: str) -> Any:
    outgoing, _ = servers
    entry = calendar_entry(env, key, source=saved_message(env, "invite"), sequence=3)
    assert env.publisher.send(answer_to(env, entry)).status == "sent"
    return itip.read_invitation(reply_of(outgoing))


def test_an_answer_to_one_date_of_a_series_names_the_series_and_that_date(env, servers):
    reply = occurrence_reply(env, servers, "uid-9#2030-03-11")
    assert reply.uid == "uid-9" and reply.recurrence_id == date(2030, 3, 11)


def test_an_answer_to_a_zoned_date_time_names_the_same_moment(env, servers):
    reply = occurrence_reply(env, servers, "uid-9#2030-03-11T10:00:00+02:00")
    assert reply.uid == "uid-9" and reply.recurrence_id == datetime(2030, 3, 11, 8, 0, tzinfo=UTC)


def test_an_answer_to_a_utc_date_time_names_it_in_utc(env, servers):
    reply = occurrence_reply(env, servers, "uid-9#2030-03-11T09:00:00+00:00")
    assert reply.uid == "uid-9" and reply.recurrence_id == datetime(2030, 3, 11, 9, 0, tzinfo=UTC)


def test_an_answer_to_the_whole_series_names_no_date(env, servers):
    outgoing, _ = servers
    reply = occurrence_reply(env, servers, "uid-9")
    assert reply.uid == "uid-9" and reply.recurrence_id is None
    assert "RECURRENCE-ID" not in reply_of(outgoing)


def test_a_key_that_only_contains_a_hash_is_not_taken_for_a_date():
    assert acts.occurrence_of("room#4") == ("room#4", None)
    assert acts.occurrence_of("a#b#2030-03-11") == ("a#b", "2030-03-11")


def test_a_stale_answer_whose_only_change_is_the_revision_shows_before_and_after(env, servers):
    entry = calendar_entry(env, "uid-9", source=saved_message(env, "invite"), sequence=3)
    act_id = answer_to(env, entry)
    update_record(env, "event", entry, sequence=4)
    assert env.publisher.send(act_id).status == "stale"
    data = env.act(act_id)
    found = acts.differences(
        data["was_approved"]["shown"], acts.current_shown(env.store.read(), env.store.plugins, data)
    )
    assert [(d.part, d.before, d.after) for d in found] == [
        ("about", f"{START} - {END} (revision 3)", f"{START} - {END} (revision 4)")
    ]
