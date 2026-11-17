"""Signing in is the whole setup: once a mail add-on's sign-in finishes, the person's sent mail is read and counted, so
the assistant's look can offer the people they write to with no extra step (S-0520, S-0590). The add-on is a stand-in
whose sent folder holds mail to made-up people."""

from datetime import UTC, datetime

import yaml

from tests.test_sign_in import SIGNING
from tests.test_sign_in import signing as signing  # noqa: F401 - the fixture
from tests.test_sign_in_sources import _app, _reopen, _with_sources, sign_in

#: One sent message per entry: its recipients, in the add-on's own shape (everyone else on it).
SENT_TO = [
    ["Riley Quinn <riley.quinn@example.com>", "Sam Ortega <sam.ortega@example.com>"],
    ["Riley Quinn <riley.quinn@example.com>"],
    ["Riley Quinn <riley.quinn@example.com>", "Avery Lund <avery.lund@example.com>"],
    ["Sam Ortega <sam.ortega@example.com>"],
    ["Jordan Pike <jordan.pike@example.com>"],
    ["<responses+8c4261ed-0c87-44f0-bed8-4d9b5892e623@replies.bulletin.example.com>"],
]
DAYS_AGO = [1, 3, 9, 20, 4, 2]

READING = SIGNING.replace(
    '        scopes=["read", "offline"], params={"access_type": "offline"},\n',
    '        scopes=["read", "offline"], params={"access_type": "offline"},\n'
    '        sources=[{"connector": "p18/inbox", "label": "Your inbox", "settings": {"folders": ["INBOX"]}},\n'
    '                 {"connector": "p18/inbox", "label": "Your sent mail", "settings": {"folders": ["SENT"]},'
    ' "sent": True}],\n',
).replace(
    "def register(registrar):\n",
    "from datetime import UTC, datetime, timedelta\n"
    "from pydantic import BaseModel, Field\n"
    "from engine.plugin_api import MessageDetails, Poll, SourceItem\n\n"
    f"SENT_TO = {SENT_TO!r}\n"
    f"DAYS_AGO = {DAYS_AGO!r}\n\n"
    "class InboxSettings(BaseModel):\n"
    "    folders: list[str] = Field(default_factory=list)\n\n"
    "def poll_inbox(settings, state, context):\n"
    "    if settings.folders != ['SENT']:\n"
    "        return Poll([], {})\n"
    "    items = []\n"
    "    for n, (to, days) in enumerate(zip(SENT_TO, DAYS_AGO)):\n"
    "        when = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0).isoformat()\n"
    "        items.append(SourceItem(key=f's{n}', title=f'Sent {n}', text=f'From: Me\\n\\nWords {n}.', author='Me',\n"
    "            changed_at=when, message=MessageDetails(sender='Me <me@example.com>', received=when, unread=False,\n"
    "                participants=tuple(to))))\n"
    "    return Poll(items, {})\n\n"
    "def register(registrar):\n"
    "    registrar.connector('p18/inbox', label='Inbox', settings=InboxSettings, poll=poll_inbox, reads='mail')\n",
)


def test_after_signing_in_the_sent_mail_is_counted_by_who_it_went_to_and_no_rule_picks_the_people(signing):  # noqa: F811
    from engine.watch import refresh

    ws, cfg, store = signing[:3]
    store.close()
    _with_sources(ws, READING)
    manifest_path = ws.root / "plugins" / "p18" / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["provides"]["connector_reads"] = {"p18/inbox": "mail"}
    manifest_path.write_text(yaml.safe_dump(manifest))
    c, api = _app(ws, cfg)
    sign_in(c, api)
    cfg2, store2 = _reopen(ws, cfg)
    try:
        sent = [s for s in cfg2.watch.sources if s.label == "Your sent mail"]
        assert len(sent) == 1 and sent[0].author == cfg2.workspace.user.person
        for source in cfg2.watch.sources:
            if source.connector == "p18/inbox":
                refresh(ws, store2, cfg2, source.id, datetime.now(UTC))
    finally:
        store2.close()
    # The sent mail is counted by who it went to, the most written to first, the reply address of a newsletter service
    # among them with the mark a code gives it (the assistant weighs the mark).
    from engine import contact_tally

    cfg3, store3 = _reopen(ws, cfg)
    try:
        counted = contact_tally.tally(store3, cfg3)
    finally:
        store3.close()
    people = [(c.name, c.to_them) for c in counted if not c.hints]
    assert people == [("Riley Quinn", 3), ("Sam Ortega", 2), ("Avery Lund", 1), ("Jordan Pike", 1)], people
    assert [c.hints for c in counted if "replies." in c.address] == [(contact_tally.AUTOMATED, contact_tally.CODE)]
    # No one is offered by a rule: the offers are the assistant's, and none has been made.
    body = c.get(f"{api}/setup/people-suggestions").json()
    assert body["people"] == []
