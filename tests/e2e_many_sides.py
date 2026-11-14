"""What `tests/e2e_server.py --many-sides` seeds, apart from the server so a test can read it without starting one: a
workspace made as a person with no work makes it, then a job and three businesses are added as setup adds them, so
there are five sides (Personal beside four). Three of the names are long enough to test truncation. Every name is made
up; nothing here is read from a real service."""

from __future__ import annotations

import json
from pathlib import Path

#: The sides added, in order, with the kind setup gives each. Two of the businesses are the long ones. They are in a
#: data file so the capture tool (web/visual) adds the same ones.
SIDES: tuple[tuple[str, str], ...] = tuple(
    (side["name"], side["kind"])
    for side in json.loads(Path(__file__).with_name("e2e_many_sides.json").read_text(encoding="utf-8"))["sides"]
)


def business_names() -> list[str]:
    return [name for name, _ in SIDES]


def seed_many_sides(client) -> dict:
    """Add each side through the setup route, as setup adds it. `client` is a test client of the running app. Returns
    the names and the ids they were given, for the browser test to read."""
    ids = []
    for name, kind in SIDES:
        made = client.post("/api/setup/business", json={"name": name, "kind": kind})
        assert made.status_code == 200, made.text
        ids.append(made.json()["project"])
    return {"names": business_names(), "ids": ids}
