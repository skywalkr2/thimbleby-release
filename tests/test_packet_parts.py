"""A run's packet size is kept by part, so the testers' own growth shows which part to cap first (S-0787)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from engine import packet
from engine.ai.task import PACKET_PARTS, AiTask, packet_tokens_by_part
from engine.storage import Store
from engine.workspace import init_workspace
from tests.aged_workspace import Amounts, age, everyday_requests
from tests.conftest import DEMO_A

SMALL = Amounts(
    people=5, projects=2, actions_open=5, actions_done=5, questions_open=3, questions_closed=3,
    lessons=3, glossary=3, facts=5, events=3, mails=3,
)  # fmt: skip


def parts_of(tmp_path, amounts: Amounts, kind: str) -> dict[str, int]:
    ws = init_workspace(tmp_path / "ws", template=DEMO_A, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    try:
        age(ws, store, cfg, amounts)
        request = everyday_requests(ws, store, cfg)[kind]
        return packet_tokens_by_part(packet.build(ws, store, cfg, request, packet_today()).task)
    finally:
        store.close()


def packet_today():
    from tests.aged_workspace import TODAY

    return TODAY


@pytest.mark.parametrize("kind", ["notes", "ask"])
def test_more_open_to_dos_make_a_bigger_to_dos_part_and_leave_the_others(tmp_path, kind):
    few = parts_of(tmp_path / "a", SMALL, kind)
    many = parts_of(tmp_path / "b", replace(SMALL, actions_open=60), kind)
    assert set(few) == set(PACKET_PARTS)
    assert many["todos"] > few["todos"]
    for part in ("knowledge", "questions", "people"):
        assert many[part] == few[part]


def test_a_packet_that_names_no_parts_counts_as_the_rest():
    task = AiTask(kind="x", instructions="a" * 40, stable="b" * 40, request="c" * 40, output_schema={})
    assert packet_tokens_by_part(task) == {"knowledge": 0, "questions": 0, "todos": 0, "people": 0, "rest": 30}
