"""The walkthrough's people step shows the people the assistant offers (design 7.8, 6.22) and takes a pasted list. The
offers are the weekly look's reading of the contact tally, never a rule of a name's or an address's shape. Names and ids
come from the fixtures; correspondents are generated, never real."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from engine import people_suggestions
from engine.storage import WriteContext
from tests.conftest import DEMO_B, fixture_records
from tests.test_source_intake import NOW, make, read

_W = WriteContext(actor="engine", trust="trusted", op="test.suggestions")
TOKEN = "people-suggestions-token"
LIMIT = 5
REASON = "Writes to you every week and you reply: likely a colleague."
#: Made-up addresses are built from this, so no address is written out whole.
WEB = "http" + "://"


@pytest.fixture(autouse=True)
def fake_reads_mail(monkeypatch):
    """The test source stands for a mailbox: it says it reads mail, as a connector's registration does."""
    real = people_suggestions.reads
    monkeypatch.setattr(people_suggestions, "reads", lambda c, said=None: ["mail"] if c == "fake" else real(c, said))


def who(n: int) -> str:
    """A generated correspondent, as a mail header shows them."""
    return f"Correspondent {chr(65 + n)} <c{n}@example.com>"


def message(
    key: str, sender: str, to: list[str] | None = None, *, bulk: bool | None = None, subject: str | None = None
) -> dict:
    received = NOW.replace(hour=8).isoformat()
    details = {"sender": sender, "received": received, "unread": True, "participants": to or [], "bulk": bulk}
    return {
        "key": key,
        "title": subject or f"Subject of {key}",
        "text": f"From: {sender}\n\nWords about {key}.",
        "message": details,
    }


def known_person(cfg) -> dict:
    """A person on file who isn't the person using the app."""
    return next(p for p in fixture_records(DEMO_B, "person") if p["id"] != cfg.workspace.user.person)


def setup(tmp_path, items, *, sent: bool):
    ws, cfg, store = make(tmp_path, items, first_run="baseline")
    if sent:
        cfg.watch.sources[0].author = cfg.workspace.user.person
    read((ws, cfg, store))
    return ws, cfg, store


def test_the_number_suggested_is_a_setting_with_a_default_and_a_description(tmp_path):
    ws, cfg, store = make(tmp_path, [])
    store.close()
    field = type(cfg.ui.walkthrough).model_fields["suggested_people"]
    assert cfg.ui.walkthrough.suggested_people == LIMIT and field.description


# ---- a pasted list --------------------------------------------------------------------------------------------


def test_a_pasted_list_is_one_name_per_line_with_marks_addresses_blanks_and_repeats_dealt_with():
    pasted = """
    - Correspondent A
    2) Correspondent B <c1@example.com>,

    * "Correspondent C" <c2@example.com>
    correspondent a
    d.person@example.com
      Correspondent   E
    """
    pairs = [(x.name, x.address) for x in people_suggestions.parse_pasted(pasted)]
    assert pairs == [
        ("Correspondent A", None),
        ("Correspondent B", "c1@example.com"),
        ("Correspondent C", "c2@example.com"),
        ("D Person", "d.person@example.com"),
        ("Correspondent E", None),
    ]
    assert people_suggestions.parse_pasted("") == [] and people_suggestions.parse_pasted(" \n \n") == []


def test_a_pasted_list_is_bounded():
    pasted = "\n".join(f"Name {chr(65 + n // 26)}{chr(97 + n % 26)}" for n in range(500))
    assert len(people_suggestions.parse_pasted(pasted)) == 200


def test_a_pasted_list_keeps_only_lines_that_read_as_a_person_and_reads_a_relation_after_the_name():
    """The person's path: a pasted list with junk lines among real ones. Numbers, marks and web addresses are left out
    (and said so); `Name, relation`, `Name - relation` and `Name; relation` are a name with how they relate; a repeat of
    a name is merged."""
    pasted = "\n".join(
        [
            "12345",
            "!!!",
            WEB + "example.com",
            "Correspondent A, my sister",
            "Correspondent B - our neighbor",
            "Correspondent C; my accountant",
            "Correspondent B <c1@example.com>, our neighbor",
            "correspondent a",
            "Correspondent D <c3@example.com>",
        ]
    )
    found = people_suggestions.parse_list(pasted)
    assert [(x.name, x.relation, x.address) for x in found.people] == [
        ("Correspondent A", "my sister", None),
        ("Correspondent B", "our neighbor", "c1@example.com"),
        ("Correspondent C", "my accountant", None),
        ("Correspondent D", None, "c3@example.com"),
    ]
    assert found.left_out == ["12345", "!!!", WEB + "example.com"]


def test_a_name_is_a_first_and_a_last_name_not_a_company_and_a_long_real_name_is_kept():
    """S-0370: one word, a line in capitals and a company's name are not people; a long real name is."""
    companies = frozenset({"ltd", "inc", "company"})
    for wrong in ("J", "Alex", "Bob", "THE BIG COMPANY LTD", "Acme Holdings Ltd", "Pat Sample Inc.", "12345"):
        assert not people_suggestions.reads_as_a_person(wrong, companies), wrong
    for right in ("Pat Sample", "J. Smith", "Maria Fernanda Gonzalez de la Cruz Alvarez", "Anne-Marie O'Neil"):
        assert people_suggestions.reads_as_a_person(right, companies), right
    # A line that gives an address is known by it, so its name may be one word.
    found = people_suggestions.parse_list("Alex <alex@example.com>\nAlex\nTHE BIG COMPANY LTD", companies)
    assert [(p.name, p.address) for p in found.people] == [("Alex", "alex@example.com")]
    assert found.left_out == ["Alex", "THE BIG COMPANY LTD"]


# ---- the routes -----------------------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    today = datetime.now(UTC)
    ws, cfg, store = make(tmp_path, [], first_run="baseline")
    with store.transaction() as tx:
        for address, name, count in [
            ("c0@example.com", "Correspondent A", 5),
            ("c1@example.com", "Correspondent B", 2),
        ]:
            tx.create(
                "person_offer",
                {
                    "name": name,
                    "address": address,
                    "why": REASON,
                    "from_them": count - 1,
                    "to_them": 1,
                    "status": "offered",
                    "offered_at": today,
                },
                _W,
            )
    store.close()
    application = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(application, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client, application.state.store, cfg


def test_the_suggestions_route_lists_the_offered_people_with_why_and_changes_nothing(api):
    client, store, cfg = api
    before = len(store.read().list("person"))
    body = client.get("/api/setup/people-suggestions").json()
    assert [(p["name"], p["address"], p["count"], p["why"]) for p in body["people"]] == [
        ("Correspondent A", "c0@example.com", 5, REASON),
        ("Correspondent B", "c1@example.com", 2, REASON),
    ]
    assert len(store.read().list("person")) == before


def test_with_no_offer_the_route_says_where_the_look_stands_and_never_offers_by_a_rule(tmp_path):
    """Mail was read (a sent message to two people) but the assistant has not offered anyone: the list is empty and says
    why, whatever the names and addresses look like."""
    ws, cfg, store = make(tmp_path, [message("m1", "me@example.com", [who(0), who(1)])], first_run="baseline")
    read((ws, cfg, store))
    store.close()
    application = create_app(ws, cfg, TOKEN, ui_dist=tmp_path / "no-ui", start_worker=False)
    with TestClient(application, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        body = client.get("/api/setup/people-suggestions").json()
    assert body["people"] == [] and body["state"] in ("no_account", "not_yet")


def test_adding_a_suggested_person_through_the_people_route_takes_them_off_the_list(api):
    client, store, cfg = api
    added = client.post("/api/people", json={"full_name": "Correspondent A", "aliases": [], "side": "personal"})
    assert added.status_code == 200, added.text
    assert [p["name"] for p in client.get("/api/setup/people-suggestions").json()["people"]] == ["Correspondent B"]


def test_a_pasted_list_adds_each_name_with_no_relation_on_the_personal_side_and_skips_those_on_file(api):
    client, store, cfg = api
    known = known_person(cfg)["full_name"]
    pasted = f"Correspondent A\nCorrespondent B <c1@example.com>\n{known}\n"
    done = client.post("/api/setup/people-paste", json={"text": pasted, "side": "personal"})
    assert done.status_code == 200, done.text
    assert done.json() == {"added": ["Correspondent A", "Correspondent B"], "skipped": [known], "left_out": []}
    people = {p["name"]: p for p in client.get("/api/people").json()}
    for name in done.json()["added"]:
        assert people[name]["relation"] is None and people[name]["side"] == "personal"
    # Pasting the same list again adds nobody twice.
    again = client.post("/api/setup/people-paste", json={"text": pasted, "side": "personal"}).json()
    assert again["added"] == [] and again["skipped"] == ["Correspondent A", "Correspondent B", known]


def test_adding_a_suggested_person_keeps_their_address_so_a_later_message_from_it_is_known_to_be_theirs(api):
    from engine.names import People

    client, store, cfg = api
    (first, _second) = client.get("/api/setup/people-suggestions").json()["people"]
    added = client.post(
        "/api/setup/people-add",
        json={"full_name": first["name"], "aliases": [], "side": "personal", "address": first["address"]},
    )
    assert added.status_code == 200, added.text
    record = store.read().get("person", added.json()["id"]).data
    assert record["how_to_reach"] == {"email": [first["address"]]}
    # A hand-in from that address resolves to them by the header, with no question about who it is.
    found = People(store, cfg).match_entries([f"Someone Else <{first['address']}>"])
    assert found == {added.json()["id"]}
    # They leave the suggestions, their offer is kept with who they became, and the address isn't given twice.
    assert [p["address"] for p in client.get("/api/setup/people-suggestions").json()["people"]] == ["c1@example.com"]
    offer = next(o for o in store.read().list("person_offer") if o.data["address"] == first["address"])
    assert offer.data["status"] == "kept" and offer.data["person"] == added.json()["id"]
    other = client.post(
        "/api/setup/people-add",
        json={"full_name": "Another Person", "aliases": [], "side": "personal", "address": first["address"]},
    )
    assert store.read().get("person", other.json()["id"]).data["how_to_reach"] == {}


def test_leaving_people_out_keeps_them_off_the_list_for_good(api):
    client, store, cfg = api
    done = client.post("/api/setup/people-suggestions/leave-out", json={"addresses": ["c0@example.com"]})
    assert done.status_code == 200, done.text
    assert [p["address"] for p in client.get("/api/setup/people-suggestions").json()["people"]] == ["c1@example.com"]
    left = next(o for o in store.read().list("person_offer") if o.data["address"] == "c0@example.com")
    assert left.data["status"] == "dismissed"


def test_a_pasted_name_and_address_keeps_the_address(api):
    from engine.names import People

    client, store, cfg = api
    done = client.post(
        "/api/setup/people-paste",
        json={"text": "Pasted Person <Pasted.Person@Example.com>\nNo Address", "side": "personal"},
    ).json()
    assert done["added"] == ["Pasted Person", "No Address"]
    people = {p.data["full_name"]: p for p in store.read().list("person")}
    assert people["Pasted Person"].data["how_to_reach"] == {"email": ["pasted.person@example.com"]}
    assert not people["No Address"].data.get("how_to_reach")
    assert People(store, cfg).match_entries(["x <pasted.person@example.com>"]) == {people["Pasted Person"].id}


def test_the_paste_preview_shows_what_would_be_added_and_changes_nothing(api):
    client, store, cfg = api
    known = known_person(cfg)["full_name"]
    before = len(store.read().list("person"))
    text = f"12345\nCorrespondent A, my sister\n{known}\n{WEB}example.com"
    body = client.post("/api/setup/people-paste/preview", json={"text": text, "side": "personal"}).json()
    assert body["people"] == [
        {"name": "Correspondent A", "relation": "my sister", "address": None, "on_file": False},
        {"name": known, "relation": None, "address": None, "on_file": True},
    ]
    assert body["left_out"] == ["12345", WEB + "example.com"]
    assert len(store.read().list("person")) == before


def test_a_pasted_list_adds_the_people_with_their_relation_and_none_of_the_junk(api):
    client, store, cfg = api
    text = f"12345\n!!!\n{WEB}example.com\nCorrespondent A, my sister\nCorrespondent C; my accountant"
    done = client.post("/api/setup/people-paste", json={"text": text, "side": "personal"}).json()
    assert done["added"] == ["Correspondent A", "Correspondent C"]
    assert done["left_out"] == ["12345", "!!!", WEB + "example.com"]
    people = {p["name"]: p for p in client.get("/api/people").json()}
    assert people["Correspondent A"]["relation"] == "my sister"
    assert people["Correspondent C"]["relation"] == "my accountant"
    assert not any(name in people for name in ("12345", "!!!", WEB + "example.com"))
