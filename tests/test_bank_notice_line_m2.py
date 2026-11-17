# ruff: noqa: F811
"""The stopped line of a bank's notice (S-0569) names the service, never the machine-made address it came from."""

from engine.dispatcher import DROPPED_STOP, needs_you
from engine.today_queue import queue
from tests.test_bank_notice_m2 import SERVICE_ADDRESS, STATEMENT
from tests.test_silent_stops import env, hand  # noqa: F401


def test_a_stopped_line_for_mail_from_a_machine_made_address_names_the_service(env):
    ws, cfg, store, clock = env
    request = hand(env, f"From: {SERVICE_ADDRESS}\nSubject: {STATEMENT}\n\nYour statement is ready.")
    needs_you(store, request, DROPPED_STOP)
    [line] = [x for x in queue(ws, store, cfg, clock()) if x.kind == "refused"]
    assert line.title.kind == "email" and line.title.sender == "Northfield Bank"
    assert line.title.topic == STATEMENT
    assert "@" not in (line.title.sender or "")
    assert line.waiting == DROPPED_STOP and "account" not in line.waiting.lower()
