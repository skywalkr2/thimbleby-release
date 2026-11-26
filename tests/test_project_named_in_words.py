"""A note brings what was learned for the projects its words name, by full name or by a short form (the first-week
journey, row 11): people say a project by a short form far more often than by its full name.
Names are made up."""

from __future__ import annotations

import pytest

from engine.knowledge_section import projects_named_in
from engine.storage import Store, WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

_TEST = WriteContext("pm", "trusted", "test")
GALA, EXHIBIT = "Volunteer " + "Gala", "Spring " + "Exhibit"


@pytest.fixture
def view(tmp_path):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    store = Store(ws.db_path, cfg=ws.config(env={}))
    with store.transaction() as tx:
        ids = {
            "gala": tx.create("project", {"name": GALA}, _TEST).id,
            "exhibit": tx.create("project", {"name": EXHIBIT}, _TEST).id,
            "spring_fair": tx.create("project", {"name": "Spring Fair"}, _TEST).id,
            "office_move": tx.create("project", {"name": "Office Move"}, _TEST).id,
            "book_launch": tx.create("project", {"name": "Book Launch"}, _TEST).id,
            "kitchen": tx.create("project", {"name": "Kitchen Remodel"}, _TEST).id,
            "report": tx.create("project", {"name": "Annual Report"}, _TEST).id,
        }
    yield store.read(), ids
    store.close()


@pytest.mark.parametrize(
    "text, named",
    [
        ("We also need to send the gala sponsor thank-you letters.", {"gala"}),
        ("The Volunteer Gala needs a caterer.", {"gala"}),
        ("Book the hall for the exhibit.", {"exhibit"}),
        ("The exhibits open in March.", {"exhibit"}),
        ("Plans for our Exhibit are late.", {"exhibit"}),
        # An ordinary word (a verb at a sentence's start, a noun on its own) is no project's short form (#67, B-11).
        ("Move the meeting to Friday.", set()),
        ("We need office chairs.", set()),
        ("Buy a book for Sam.", set()),
        ("Paint kitchen walls on Sunday.", set()),
        ("Send report to Dana.", set()),
        ("Two exhibits open in March.", set()),
        # A word two projects' names share names neither; the word that only one holds names it.
        ("Plans for spring are late.", set()),
        ("The spring fair stalls are booked.", {"spring_fair"}),
        ("Buy milk on the way home.", set()),
        # #68 (B-13): a describing word and a brand are not a project; a head word starting a sentence is.
        ("Clean the office on Friday.", set()),
        ("Fix the kitchen sink.", set()),
        ("Read the book on the train.", set()),
        ("Stop by my office.", set()),
        ("We bought a Kitchen Aid mixer.", set()),
        ("Pick up supplies at Office Depot.", set()),
        ("Exhibit planning is late.", {"exhibit"}),
        ("Gala tickets sold out.", {"gala"}),
        ("Move it to Friday.", set()),
        ("Move the meeting.", set()),
        ("Give the Art Exhibit a miss.", set()),
        # #70 (B-8): a sentence's first word that is an ordinary verb or adjective names no project by itself.
        ("Move fast on the hiring.", set()),
        ("Move everything to Friday.", set()),
        ("Report back by Friday.", set()),
        ("Report cards come out Monday.", set()),
        ("Fair enough, let's do it.", set()),
        # Judged wrong: "report" is the head word of a project's name here, so the lean toward naming keeps it.
        ("Send the report to Dana.", {"report"}),
    ],
)
def test_a_project_is_named_by_its_full_name_or_a_short_form(view, text, named):
    reader, ids = view
    found = set(projects_named_in(reader, text))
    mine = {ids[k] for k in named}
    assert mine <= found, (text, found)
    assert not (found & set(ids.values())) - mine, (text, found)
