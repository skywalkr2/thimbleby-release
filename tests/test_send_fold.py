"""Messages to send are one line when many people have some (design 7.7): the fold is by count, keeps every item and the
oldest ready day, leaves the follow-up lines alone, and can be turned off."""

from __future__ import annotations

from engine.today_queue import Line, _fold_sends


def send(person: str, items: int, since: str | None) -> Line:
    return Line(
        key=f"send:{person}",
        group="send",
        kind="send",
        count=items,
        person=person,
        actions=[f"{person}-a{n}" for n in range(items)],
        ready_since=since,
        since=person,
    )


def nudge(person: str) -> Line:
    return Line(key=f"nudge:{person}", group="send", kind="nudge", person=person, since=person)


def test_the_send_lines_fold_into_one_that_counts_every_item_and_names_the_oldest_day():
    lines = [send("a", 2, "2030-03-05"), nudge("a"), send("b", 3, "2030-03-01"), send("c", 1, None)]
    out = _fold_sends(lines, 3)
    folded = [line for line in out if line.kind == "sends"]
    assert len(folded) == 1 and [line.kind for line in out] == ["sends", "nudge"]
    assert folded[0].count == 6 and len(folded[0].actions) == 6
    assert [part.person for part in folded[0].parts] == ["a", "b", "c"]
    assert folded[0].ready_since == "2030-03-01"


def test_fewer_lines_than_the_setting_stay_one_for_each_person_and_zero_never_folds():
    lines = [send("a", 1, None), send("b", 1, None)]
    assert _fold_sends(lines, 3) == lines
    many = [send(p, 1, None) for p in "abcde"]
    assert _fold_sends(many, 0) == many
