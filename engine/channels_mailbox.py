"""The core's `mailbox` channel: a plain mailbox acts through its own servers (design 6.12).

Messages go out through the account's outgoing server (SMTP over TLS) and a copy is saved to the sent folder unless the
server does that itself. Archive, move, label and mark read go over IMAP, finding each message by its Message-ID in the
account's folder. An answer to an invitation is a message to the organizer with the iTIP reply attached.

The Message-ID of an outgoing message is made from the attempt key, so `status` can ask the sent folder whether an
attempt went out. A server may keep no copy, so a message not found there is `ChannelUnknown`, never `ChannelNotSent`.

Each act makes one connection to each server it needs, waits at most the account's timeout, and never retries: a server
that says to try later is an `outage` and the person decides. A message is never deleted.
"""

from __future__ import annotations

import contextlib
import imaplib
import logging
import re
import smtplib
import socket
import ssl
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from pydantic import ValidationError

from engine import act_accounts, itip
from engine.channels import (
    ChannelContext,
    ChannelFailed,
    ChannelRegistration,
    ChannelSent,
    ChannelUndone,
    ChannelUnknown,
    OutgoingAct,
)
from engine.connectors import ConnectorError
from engine.connectors.mailbox import MailboxSettings, _close, _open, _quoted, parse_folders

log = logging.getLogger(__name__)

NAME = "mailbox"
#: What the channel does, by kind of target.
ACTIONS: dict[str, tuple[str, ...]] = {
    "message": ("send", "reply", "reply_all", "forward"),
    "mailbox": ("archive", "move", "label", "mark_read"),
    "calendar": ("answer",),
}
#: The answers to an invitation a mailbox can give (it can't propose another time), and why it refuses that one.
ANSWERS = ("accepted", "tentative", "declined")
NO_PROPOSE = "a mailbox can only accept, decline or say maybe to an invitation, not propose a new time"
#: The port that is a secure connection from the start; any other is made secure after connecting.
IMPLICIT_TLS_PORT = 465
#: How a person's answer to an invitation reads in the iTIP reply.
_STATUS = {"accepted": "ACCEPTED", "tentative": "TENTATIVE", "declined": "DECLINED"}
_FLAG_SEEN = "\\Seen"
_FLAG_DELETED = "\\Deleted"


class _Stop(Exception):
    """The act ends here with this answer (a `ChannelFailed` or a `ChannelUnknown`)."""

    def __init__(self, answer: Any):
        self.answer = answer


def message_id(key: str, address: str) -> str:
    """The Message-ID of the message an attempt sends: the same key always gives the same one."""
    domain = address.rsplit("@", 1)[-1] if "@" in address else "localhost"
    return f"<{key}@{domain}>"


def _refused(reason: str) -> _Stop:
    return _Stop(ChannelFailed("refused", reason))


def _failed_from(err: ConnectorError, settings: MailboxSettings) -> _Stop:
    """A connector's error as the channel's answer: sure that nothing was done."""
    if err.kind == "auth":
        return _Stop(
            ChannelFailed("auth", f"Sign in again to the mailbox {settings.user}: {err.detail or 'it was refused'}")
        )
    if err.kind in ("outage", "throttled"):
        return _Stop(ChannelFailed("outage", err.detail or "the mail server isn't answering"))
    if err.kind == "offline":
        return _Stop(ChannelFailed("offline", err.detail or "the mail server can't be reached from here"))
    return _refused(err.detail or "the mail server refused it")


def _by_code(code: int, what: str) -> _Stop:
    """What an SMTP reply code says about a step that was not accepted: 4xx is a try-later, 5xx a refusal; any other
    code is no clear answer."""
    if 400 <= code < 500:
        return _Stop(ChannelFailed("outage", f"the outgoing mail server can't take {what} right now; try again later"))
    if 500 <= code < 600:
        return _Stop(ChannelFailed("refused", f"the outgoing mail server refused {what}"))
    return _Stop(ChannelUnknown())


class MailboxChannel:
    """The channel. `settings_of` gives an account's mailbox settings (None when there is no such mailbox now),
    `acting_accounts` the mailbox accounts acting is on for (the ones a status can look in), and `now`
    the clock. A forward's quoted original is a part of the act (`quoted`), so it is what the person approved."""

    def __init__(
        self,
        settings_of: Callable[[str], MailboxSettings | None],
        acting_accounts: Callable[[], list[str]],
        now: Callable[[], datetime] | None = None,
    ):
        self.settings_of = settings_of
        self.acting_accounts = acting_accounts
        self.now = now or (lambda: datetime.now(UTC))

    def registration(self) -> ChannelRegistration:
        return ChannelRegistration(
            NAME,
            "Mailbox",
            tuple(ACTIONS),
            send=self.send,
            status=self.status,
            undo=self.undo,
            actions=dict(ACTIONS),
            accounts=(act_accounts.MAILBOX,),
            binding=self.binding,
        )

    # ---- sending -----------------------------------------------------------------------------------------------------

    def send(self, act: OutgoingAct, attempt_key: str, context: ChannelContext | None = None) -> Any:
        try:
            settings = self._settings(act)
            if act.kind == "mailbox":
                return self._mailbox_act(act, settings)
            if act.kind == "message" and act.action in ACTIONS["message"]:
                return self._send_mail(act, settings, attempt_key, self._compose(act, settings, attempt_key))
            if act.kind == "calendar" and act.action == "answer":
                return self._send_mail(act, settings, attempt_key, self._answer(act, settings, attempt_key))
            raise _refused(f"a mailbox can't {act.action or 'do that'} for a {act.kind} act")
        except _Stop as stop:
            return stop.answer

    def _settings(self, act: OutgoingAct) -> MailboxSettings:
        found = self.settings_of(act.account) if act.account else None
        if found is None:
            raise _refused("the mailbox this goes through isn't set up any more")
        return found

    def _compose(self, act: OutgoingAct, settings: MailboxSettings, key: str) -> EmailMessage:
        sender = self._sender(settings)
        message = self._envelope(act, settings, key, sender, act.parts.get("subject") or "(no subject)")
        body = act.parts.get("body") or ""
        if act.action in ("reply", "reply_all", "forward") and act.about and act.about[0].service_id:
            original = act.about[0]
            if act.action != "forward":
                message["In-Reply-To"] = original.service_id
                message["References"] = original.service_id
            elif act.parts.get("quoted"):
                quoted = "\n".join("> " + line for line in act.parts["quoted"].splitlines())
                body = f"{body}\n\n{quoted}"
        message.set_content(body)
        return message

    def _answer(self, act: OutgoingAct, settings: MailboxSettings, key: str) -> EmailMessage:
        status = _STATUS.get(act.answer or "")
        if status is None:
            raise _refused(NO_PROPOSE)
        if not act.about or not act.about[0].uid:
            raise _refused("the invitation has no id to answer")
        if not act.recipients:
            raise _refused("the invitation names no organizer to answer")
        sender = self._sender(settings)
        about = act.about[0]
        start: datetime | None = None
        with contextlib.suppress(TypeError, ValueError):
            start = datetime.fromisoformat(act.start) if act.start else None
        invitation = itip.Invitation(
            method="REQUEST",
            uid=about.uid,
            # The organizer's own revision number, as the calendar entry holds it; unknown, the reply carries none.
            sequence=about.sequence if about.sequence is not None else 0,
            summary=act.title or "",
            start=start,
            end=None,
            organizer=act.recipients[0].address,
            attendees=(itip.Attendee(email=sender),),
            cancelled=False,
            dtstamp=self.now(),
        )
        try:
            ics = itip.reply_ics(
                invitation,
                sender,
                status,
                act.parts.get("comment"),
                dtstamp=self.now(),
                sequence_known=about.sequence is not None,
            )
        except ValueError as err:
            raise _refused(f"the answer can't be prepared: {err}") from None
        message = self._envelope(act, settings, key, sender, act.parts.get("subject") or act.title or about.uid)
        message.set_content(act.parts.get("body") or "")
        message.add_attachment(
            ics, subtype="calendar", charset="utf-8", params={"method": "REPLY"}, filename="reply.ics"
        )
        return message

    def _sender(self, settings: MailboxSettings) -> str:
        if not settings.sender:
            raise _refused("the mailbox has no address to send from; set one in its settings")
        return settings.sender

    def _envelope(
        self, act: OutgoingAct, settings: MailboxSettings, key: str, sender: str, subject: str
    ) -> EmailMessage:
        to = [r.address for r in act.recipients if r.role == "to"]
        cc = [r.address for r in act.recipients if r.role == "cc"]
        if not to and not cc:
            raise _refused("there is no one to send it to")
        message = EmailMessage()
        message["From"] = sender
        if to:
            message["To"] = ", ".join(to)
        if cc:
            message["Cc"] = ", ".join(cc)
        message["Subject"] = " ".join(subject.split())
        message["Date"] = format_datetime(self.now())
        message["Message-ID"] = message_id(key, sender)
        return message

    def _send_mail(self, act: OutgoingAct, settings: MailboxSettings, key: str, message: EmailMessage) -> Any:
        from engine.secrets import SecretError, resolve_secret

        try:
            password = resolve_secret(settings.password)
        except SecretError as err:
            raise _Stop(
                ChannelFailed("auth", f"the password of the mailbox {settings.user} isn't set: {err}")
            ) from None
        recipients = [r.address for r in act.recipients]
        self._submit(settings, password or "", self._sender(settings), recipients, message.as_bytes())
        sent_id = str(message["Message-ID"])
        if not settings.server_keeps_sent:
            self._save_copy(settings, message)
        return ChannelSent(sent_id)

    def _submit(self, settings: MailboxSettings, password: str, sender: str, recipients: list[str], raw: bytes) -> None:
        """Hand the message to the outgoing server. Raises `_Stop` with the answer unless the server took it."""
        host, port, wait = settings.outgoing_host, settings.smtp_port, settings.timeout_seconds
        context = ssl.create_default_context()
        server: Any = None
        try:
            try:
                if port == IMPLICIT_TLS_PORT:
                    server = smtplib.SMTP_SSL(host, port, timeout=wait, context=context)
                else:
                    server = smtplib.SMTP(host, port, timeout=wait)
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                server.login(settings.user, password)
            except smtplib.SMTPNotSupportedError:
                raise _refused("the outgoing mail server doesn't offer a secure, signed-in connection") from None
            except smtplib.SMTPAuthenticationError:
                raise _Stop(
                    ChannelFailed(
                        "auth", f"Sign in again to the mailbox {settings.user}: the outgoing server refused it"
                    )
                ) from None
            except smtplib.SMTPResponseException as err:
                if err.smtp_code in (530, 534, 535, 538):
                    raise _Stop(
                        ChannelFailed(
                            "auth", f"Sign in again to the mailbox {settings.user}: the outgoing server refused it"
                        )
                    ) from None
                raise _by_code(err.smtp_code, "the sign-in") from None
            except smtplib.SMTPException:  # (these are OSErrors too, so they are named first)
                raise _Stop(ChannelFailed("outage", "the outgoing mail server stopped answering")) from None
            except (socket.gaierror, ConnectionError, TimeoutError, OSError):
                raise _Stop(ChannelFailed("offline", "couldn't reach the outgoing mail server")) from None
            self._transfer(server, sender, recipients, raw)
        finally:
            if server is not None:
                with contextlib.suppress(smtplib.SMTPException, OSError):
                    server.quit()

    def _transfer(self, server: Any, sender: str, recipients: list[str], raw: bytes) -> None:
        """MAIL, every RCPT, then DATA. Nothing is handed over unless every recipient is accepted; a connection lost
        while the message itself is going over is no clear answer."""
        try:
            code, _ = server.mail(sender)
            if code != 250:
                raise _by_code(code, "the message")
            for address in recipients:
                code, _ = server.rcpt(address)
                if code not in (250, 251):
                    raise _by_code(code, f"the address {address}")
        except smtplib.SMTPResponseException as err:
            raise _by_code(err.smtp_code, "the message") from None
        except (smtplib.SMTPException, OSError):
            raise _Stop(ChannelFailed("outage", "the outgoing mail server stopped answering")) from None
        try:
            code, _ = server.data(raw)
        except smtplib.SMTPDataError as err:
            raise _by_code(err.smtp_code, "the message") from None
        except (smtplib.SMTPException, OSError):
            raise _Stop(ChannelUnknown()) from None
        if not 200 <= code < 300:
            raise _by_code(code, "the message")

    def _save_copy(self, settings: MailboxSettings, message: EmailMessage) -> None:
        """Save a copy in the sent folder. The message has gone out, so a copy that can't be saved changes nothing
        about the answer."""
        try:
            server = _open(settings)
        except ConnectorError:
            log.warning("a sent message's copy wasn't saved: the mailbox didn't sign in")
            return
        try:
            folder = _sent_folder(server, settings)
            server.append(_quoted(folder), _FLAG_SEEN, imaplib.Time2Internaldate(self.now()), message.as_bytes())
        except (imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError):
            log.warning("a sent message's copy wasn't saved: the sent folder didn't take it")
        finally:
            _close(server)

    # ---- what happened to an attempt ---------------------------------------------------------------------------------

    def status(self, attempt_key: str, context: ChannelContext | None = None) -> Any:
        """Found in the sent folder of a mailbox acting is on for: sent. Anything else: unknown."""
        for account in self.acting_accounts():
            settings = self.settings_of(account)
            if settings is None or not settings.sender:
                continue
            wanted = f"<{attempt_key}@"
            try:
                server = _open(settings)
            except ConnectorError:
                continue
            try:
                status, _ = server.select(_quoted(_sent_folder(server, settings)), readonly=True)
                if status != "OK":
                    continue
                status, found = server.uid("SEARCH", None, "HEADER", "Message-ID", _quoted(wanted))
                if status == "OK" and (found[0] or b"").split():
                    return ChannelSent(message_id(attempt_key, settings.sender))
            except (imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError):
                continue
            finally:
                _close(server)
        return ChannelUnknown()

    # ---- what the account resolves to --------------------------------------------------------------------------------

    def binding(self, act: OutgoingAct) -> dict[str, str]:
        """What the act's account resolves to now, for the person's yes to cover: the mailbox it signs in to (server
        and user), the address and server it sends through, and for a mailbox act the folder it works in and, for an
        archive, the folder set to archive to (empty: the one the server marks). A password is no part of it, so a new
        one for the same mailbox changes nothing."""
        settings = self.settings_of(act.account) if act.account else None
        if settings is None:
            return {"mailbox": ""}
        found = {
            **_identity(settings),
            "sender": settings.sender.lower(),
            "outgoing": f"{settings.outgoing_host.lower()}:{settings.smtp_port}",
        }
        if act.kind == "mailbox":
            found["folder"] = settings.folder
            if act.action == "archive":
                found["to"] = settings.archive_folder or ""
        return found

    # ---- mailbox acts ------------------------------------------------------------------------------------------------

    def _mailbox_act(self, act: OutgoingAct, settings: MailboxSettings) -> Any:
        ids = self._ids(act)
        if act.action not in ACTIONS["mailbox"]:
            raise _refused(f"a mailbox can't {act.action} messages")
        try:
            server = _open(settings)
        except ConnectorError as err:
            raise _failed_from(err, settings) from None
        progress = _Progress(settings, {})
        try:
            if act.action in ("archive", "move"):
                destination = self._destination(act, settings, server)
                progress = _Progress(settings, _earlier(act, settings, "to", destination))
                progress.did["to"] = destination
                self._relocate(server, ids, settings.folder, destination, progress)
            else:
                flag = _keyword(act.label) if act.action == "label" else _FLAG_SEEN
                progress = _Progress(settings, _earlier(act, settings, "flag", flag))
                progress.did["flag"] = flag
                self._flag(server, ids, settings.folder, flag, progress)
        except _Stop as stop:
            # Sure that this step did nothing, but an earlier one did: the act is part done, never a plain failure.
            if progress.touched and isinstance(stop.answer, ChannelFailed):
                return ChannelUnknown(progress.said(stop.answer.reason), progress.did)
            raise
        except (imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError):
            if progress.touched:
                return ChannelUnknown(progress.said("the mail server stopped answering"), progress.did)
            return ChannelUnknown()
        finally:
            _close(server)
        return ChannelSent(", ".join(ids), progress.did)

    def undo(self, act: OutgoingAct, service_id: str, context: ChannelContext | None = None) -> Any:
        """Put a mailbox act back, as far as the act itself went: the messages it moved go back to the folder they
        left, and a label or the read mark comes off only the messages it put it on. It works in the mailbox and the
        folders the act ran with, as kept when it ran."""
        try:
            if act.kind != "mailbox" or act.action not in ACTIONS["mailbox"]:
                raise _refused("that can't be taken back")
            settings = self._settings(act)
            ids = self._ids(act)
            did = dict(act.did or {})
            moves = act.action in ("archive", "move")
            if not did and not moves:
                # Nothing says which messages the act marked, and a mark that was there before isn't its to remove.
                raise _refused("what this changed wasn't kept when it ran, so it can't be taken back from here")
            if did and did.get("mailbox") != _identity(settings):
                raise _refused(
                    "the mailbox this ran in isn't the one set up under that name now, so it can't be taken back "
                    "from here"
                )
            try:
                server = _open(settings)
            except ConnectorError as err:
                raise _failed_from(err, settings) from None
            try:
                home = str(did.get("from") or settings.folder)
                if moves:
                    there = str(did.get("to") or "") or self._destination(act, settings, server)
                    moved = [str(i) for i in did.get("moved") or []] if did else ids
                    back = _Progress(settings, {"from": there, "moved": moved})
                    self._relocate(server, moved, there, home, back)
                else:
                    marked = [str(i) for i in did.get("flagged") or []]
                    flag = str(did.get("flag") or (_keyword(act.label) if act.action == "label" else _FLAG_SEEN))
                    for uid in self._locate(server, home, marked).values():
                        self._store(server, uid, "-FLAGS", flag)
            except (imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError):
                raise _Stop(ChannelUnknown()) from None
            finally:
                _close(server)
        except _Stop as stop:
            return stop.answer
        return ChannelUndone()

    def _ids(self, act: OutgoingAct) -> list[str]:
        ids = [a.service_id for a in act.about]
        if not ids or not all(ids):
            raise _refused("a message this is about has no id on the mail server")
        return [str(i) for i in ids]

    def _destination(self, act: OutgoingAct, settings: MailboxSettings, server: Any) -> str:
        if act.action == "move":
            if not act.folder:
                raise _refused("no folder was named to move the messages to")
            return act.folder
        if settings.archive_folder:
            return settings.archive_folder
        status, data = server.list()
        found = parse_folders(list(data or [])).archive if status == "OK" else None
        if found is None:
            raise _refused("this mailbox has no archive folder; pick one in its settings")
        return found

    def _find(
        self, server: Any, folder: str, ids: list[str], *, readonly: bool = False
    ) -> dict[str, str | None] | None:
        """The UID of each message in the folder, found by Message-ID (None for one that isn't there). None when there
        is no such folder."""
        status, _ = server.select(_quoted(folder), readonly=readonly)
        if status != "OK":
            return None
        found: dict[str, str | None] = {}
        for wanted in ids:
            status, hits_of = server.uid("SEARCH", None, "HEADER", "Message-ID", _quoted(wanted))
            hits = (hits_of[0] or b"").split() if status == "OK" and hits_of else []
            found[wanted] = (hits[0].decode() if isinstance(hits[0], bytes) else str(hits[0])) if hits else None
        return found

    def _locate(self, server: Any, folder: str, ids: list[str]) -> dict[str, str]:
        """The UID of each message in the folder, by Message-ID; every one must be there before anything changes."""
        found = self._find(server, folder, ids)
        if found is None:
            raise _refused(f"there is no folder {folder}")
        if any(uid is None for uid in found.values()):
            raise _refused(f"a message isn't in {folder} any more: it was moved or deleted")
        return {wanted: str(uid) for wanted, uid in found.items()}

    def _relocate(self, server: Any, ids: list[str], source: str, destination: str, progress: _Progress) -> None:
        """Move each message from one folder to another, looking in the destination first: a message an earlier attempt
        of this act already put there is not copied again, and one copied there but still in the folder it left is only
        removed from that folder. Every message is accounted for before anything changes."""
        there = self._find(server, destination, ids, readonly=True) or {}
        here = self._find(server, source, ids)
        if here is None:
            raise _refused(f"there is no folder {source}")
        for wanted in ids:
            if here[wanted] is None and not (there.get(wanted) and wanted in progress.ours):
                raise _refused(f"a message isn't in {source} any more: it was moved or deleted")
        for wanted in ids:
            uid = here[wanted]
            if uid is None:
                progress.moved(wanted)  # an earlier attempt of this act finished it
            else:
                self._move(server, wanted, uid, destination, progress, copied=bool(there.get(wanted)))

    def _move(self, server: Any, wanted: str, uid: str, destination: str, progress: _Progress, *, copied: bool) -> None:
        """Move one message. Where the server has no MOVE, copy it and mark only that one message deleted and expunge
        only it; a server with neither way is refused rather than risking another message. `copied`: it is in the
        destination already, so it is only removed from the folder it is leaving."""
        capabilities = {str(c).upper() for c in getattr(server, "capabilities", ())}
        target = _quoted(destination)
        if "MOVE" in capabilities and not (copied and "UIDPLUS" in capabilities):
            progress.begin(wanted, "moving")
            status, _ = server.uid("MOVE", uid, target)
            if status != "OK":
                progress.untouched()
                raise _refused(f"the mail server wouldn't move the message to {destination}")
            progress.moved(wanted)
            return
        if "UIDPLUS" not in capabilities:
            raise _refused("this mail server can't move a message without risking others")
        if not copied:
            progress.begin(wanted, "copying")
            status, _ = server.uid("COPY", uid, target)
            if status != "OK":
                progress.untouched()
                raise _refused(f"the mail server wouldn't copy the message to {destination}")
        # From here the message is in both folders: anything short of the end is part done, never a failure.
        progress.begin(wanted, "copied")
        status, _ = server.uid("STORE", uid, "+FLAGS", f"({_FLAG_DELETED})")
        if status != "OK":
            raise _Stop(ChannelUnknown(progress.said("the mail server wouldn't mark it as moved"), progress.did))
        progress.begin(wanted, "marked")
        status, _ = server.uid("EXPUNGE", uid)
        if status != "OK":
            raise _Stop(ChannelUnknown(progress.said("the mail server wouldn't finish the move"), progress.did))
        progress.moved(wanted)

    def _flag(self, server: Any, ids: list[str], folder: str, flag: str, progress: _Progress) -> None:
        """Put a label or the read mark on each message that doesn't carry it, and note which those were: a mark that
        was there before the act is not the act's."""
        found = self._locate(server, folder, ids)
        carried = {wanted: self._flags(server, uid) for wanted, uid in found.items()}
        for wanted, uid in found.items():
            if flag.lower() in carried[wanted]:
                continue
            progress.begin(wanted, "marking")
            status, _ = server.uid("STORE", uid, "+FLAGS", f"({flag})")
            if status != "OK":
                progress.untouched()
                raise _refused("the mail server wouldn't change the message")
            progress.flagged(wanted)

    def _flags(self, server: Any, uid: str) -> set[str]:
        """The flags and keywords a message carries now, lowercased. Refused when the server won't say: without them
        nothing can tell a mark the act adds from one that was there."""
        status, data = server.uid("FETCH", uid, "(FLAGS)")
        text = b" ".join(part if isinstance(part, bytes) else b"" for part in (data or []))
        found = re.search(rb"FLAGS \(([^)]*)\)", text) if status == "OK" else None
        if found is None:
            raise _refused("the mail server wouldn't say how the message is marked")
        return {word.decode("utf-8", "replace").lower() for word in found.group(1).split()}

    def _store(self, server: Any, uid: str, how: str, flag: str) -> None:
        status, _ = server.uid("STORE", uid, how, f"({flag})")
        if status != "OK":
            raise _refused("the mail server wouldn't change the message")


def _identity(settings: MailboxSettings) -> dict[str, str]:
    """Which mailbox these settings sign in to: the server and the user, never the password."""
    return {"user": settings.user.strip(), "server": f"{settings.host.strip().lower()}:{settings.port}"}


def _earlier(act: OutgoingAct, settings: MailboxSettings, name: str, value: str) -> dict[str, Any]:
    """What an earlier attempt of this act reported, when it ran in this same mailbox and folder towards the same end
    (`name`: the folder a move goes to, or the mark put on); nothing otherwise, so what was done somewhere else is
    never taken for done here."""
    did = dict(act.did or {})
    if did.get("mailbox") != _identity(settings) or did.get("from") != settings.folder or did.get(name) != value:
        return {}
    return did


class _Progress:
    """What one mailbox act has done so far, as the channel reports it (`did`): the mailbox and folder it ran in, where
    a move goes, the messages moved and the messages a mark was put on, and, while a step's outcome isn't known, the
    message it was on and how far that got. `touched` says whether anything changed, or may have."""

    def __init__(self, settings: MailboxSettings, before: Mapping[str, Any]):
        self.did: dict[str, Any] = {
            "mailbox": _identity(settings),
            "from": before.get("from") or settings.folder,
            "moved": [str(i) for i in before.get("moved") or []],
            "flagged": [str(i) for i in before.get("flagged") or []],
        }
        unsure = before.get("unsure") or {}
        #: The messages an earlier attempt of this act moved, or may have.
        self.ours = {*self.did["moved"], *([str(unsure["id"])] if unsure.get("id") else [])}
        self.touched = bool(self.ours or self.did["flagged"])

    def begin(self, wanted: str, step: str) -> None:
        """A step whose outcome isn't known until the server answers."""
        self.touched = True
        self.did["unsure"] = {"id": wanted, "step": step}

    def untouched(self) -> None:
        """The server said no to the step just begun: that message is as it was."""
        self.did.pop("unsure", None)
        self.touched = bool(self.did["moved"] or self.did["flagged"])

    def moved(self, wanted: str) -> None:
        self._done("moved", wanted)

    def flagged(self, wanted: str) -> None:
        self._done("flagged", wanted)

    def _done(self, name: str, wanted: str) -> None:
        self.did.pop("unsure", None)
        if wanted not in self.did[name]:
            self.did[name].append(wanted)
        self.touched = True

    def said(self, why: str) -> str:
        """How far the act got, in plain words for the person."""
        unsure = self.did.get("unsure") or {}
        to = self.did.get("to")
        if unsure.get("step") in ("copied", "marked") and to:
            return (
                f"a message was copied to {to} but is still in {self.did['from']}: {why}. "
                "Send it again to finish; nothing is copied twice"
            )
        done = len(self.did["moved"]) + len(self.did["flagged"])
        return f"it stopped part way, with {done} done: {why}. Send it again to finish the rest"


def _sent_folder(server: Any, settings: MailboxSettings) -> str:
    """The folder sent copies are saved in and read from: the one set, else the server's own, else Sent."""
    if settings.sent_folder:
        return settings.sent_folder
    status, data = server.list()
    found = parse_folders(list(data or [])).sent if status == "OK" else None
    return found or "Sent"


def _keyword(label: str | None) -> str:
    """A label as an IMAP keyword: letters, digits and a few marks; anything else becomes a dash."""
    word = re.sub(r"[^A-Za-z0-9_.-]", "-", (label or "").strip())
    if not word:
        raise _refused("no label was named")
    return word


def for_workspace(store: Any, cfg_of: Callable[[], Any]) -> MailboxChannel:
    """The channel for a workspace: an account `mailbox:<source id>` is that watched mailbox source, with its settings
    as the configuration holds them now."""

    def settings_of(account: str) -> MailboxSettings | None:
        if act_accounts.kind_of(account) != act_accounts.MAILBOX:
            return None
        name = act_accounts.name_of(account)
        source = next((s for s in cfg_of().watch.sources if s.connector == act_accounts.MAILBOX and s.id == name), None)
        if source is None:
            return None
        try:
            return MailboxSettings.model_validate(source.settings)
        except ValidationError:  # a mailbox that isn't set up fully is one that can't be used yet
            return None

    def acting_accounts() -> list[str]:
        return [a for a in cfg_of().watch.acting if act_accounts.kind_of(a) == act_accounts.MAILBOX]

    return MailboxChannel(settings_of, acting_accounts)
