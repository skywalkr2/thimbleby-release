"""Report a problem (design 7, Help): the report goes to the configured address only through the send route, carries
exactly the person's words, reply address, version, system, the lines shown and the technical details (when left in),
and says why when it did not go."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import engine.net
from api.app import create_app
from engine import report_send
from engine.legacy_names import private_dir
from engine.reminder_content import own_address
from engine.storage import WriteContext
from engine.workspace import init_workspace
from tests.conftest import DEMO_B

TOKEN = "test-token-value"
LOCAL_FORM = "http" + "://127.0.0.1:9/api/report"
FORM = "https" + "://form.example.com/api/report"
WORDS = "The inbox stayed blank after I signed in."
LINES = "What was happening: reading a source\nStatus: 503"


def serve(status: int = 200, seen: list | None = None):
    def answer(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(status, json={"ok": status < 300})

    return httpx.MockTransport(answer)


def test_the_address_is_the_settings_then_the_builds_and_only_https_or_this_computer():
    build = {"report_to": FORM}
    assert report_send.address("", build) == build["report_to"]
    assert report_send.address(LOCAL_FORM, build) == LOCAL_FORM
    assert report_send.address("", {}) is None
    assert report_send.address("", {"report_to": None}) is None
    assert report_send.address(FORM.replace("https", "http"), {}) is None
    assert report_send.address(FORM.replace("https", "ftp"), {}) is None


def test_a_report_carries_five_parts_and_the_optional_details_and_no_identifier(monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    done = report_send.send(LOCAL_FORM, words=WORDS, reply_to="sam@example.com", version="9.8.7", problems=LINES)
    assert done.ok is True
    ((url, body),) = seen
    assert url == LOCAL_FORM
    assert sorted(body) == ["problems", "reply_to", "system", "version", "words"]
    assert body["words"] == WORDS and body["problems"] == LINES and body["version"] == "9.8.7"
    assert body["system"] == report_send.system_text()
    seen.clear()
    report_send.send(
        LOCAL_FORM,
        words=WORDS,
        reply_to="",
        version="9.8.7",
        problems=LINES,
        details="2026-01-01 WARNING engine.x: slow",
    )
    ((_, with_details),) = seen
    assert sorted(with_details) == ["details", "problems", "reply_to", "system", "version", "words"]
    assert with_details["details"] == "2026-01-01 WARNING engine.x: slow"


def test_the_limits_are_the_forms_copy_and_every_one_is_a_positive_number():
    path = Path(report_send.__file__).parent / "defaults" / "report_limits.json"
    copy = json.loads(path.read_text(encoding="utf-8"))
    assert "_source" in copy
    numbers = {k: v for k, v in copy.items() if not k.startswith("_")}
    assert numbers and all(isinstance(v, int) and v > 0 for v in numbers.values())
    assert numbers == report_send.LIMITS and "details" in numbers


def test_details_over_the_limit_are_refused_and_never_sent(monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    over = "x" * (report_send.LIMITS["details"] + 1)
    done = report_send.send(LOCAL_FORM, words=WORDS, reply_to="", version="1", problems="", details=over)
    assert (done.ok, done.why) == (False, "refused")
    assert seen == []
    exact = "x" * report_send.LIMITS["details"]
    assert report_send.send(LOCAL_FORM, words=WORDS, reply_to="", version="1", problems="", details=exact).ok
    assert len(seen) == 1


def test_details_hide_secrets_folders_and_addresses_and_keep_the_newest_lines_within_the_limit():
    home, ws_root = "/home/sam", "/home/sam/work/ws"
    lines = [
        f"2026-01-01 ERROR engine.x: could not read {ws_root}/data/a.md",
        f"2026-01-01 ERROR engine.x: under {home}/Documents/notes",
        "2026-01-01 ERROR engine.x: mail from sam.person@example.com failed",
        "2026-01-01 ERROR engine.x: key sk-abcdefghijklmnopqrstuvwxyz0123456789 refused",
    ]
    out = report_send.details_text("\n".join(lines), folders={home: "~", ws_root: "<workspace>"})
    for leaked in ("sam.person@example.com", "abcdefghijklmnopqrstuvwxyz0123456789", ws_root, home + "/", "/home/sam"):
        assert leaked not in out
    # A masked-nothing case: the folders are replaced when the text mask lets them through.
    assert report_send.scrub("at /srv/ws/x", masker=lambda t: t or "", folders={"/srv/ws": "<workspace>"}) == (
        "at <workspace>/x"
    )
    assert report_send.scrub("~/a /home/sam/b", masker=lambda t: t or "", folders={"/home/sam": "~"}) == "~/a ~/b"
    assert report_send.scrub("write to a.b@example.org now", masker=lambda t: t or "") == "write to <address> now"
    big = "\n".join(f"line {n:06d} " + "y" * 90 for n in range(2000))
    fitted = report_send.details_text(big)
    assert len(fitted) <= report_send.LIMITS["details"]
    assert fitted.endswith("line 001999 " + "y" * 90) and "line 000000" not in fitted
    assert report_send.fit("a" * 50, 10) == "a" * 10


def test_an_exception_gives_its_type_message_and_own_code_places_and_no_variable_value():
    secret_local = "value-held-in-a-local-variable"

    def deep():
        _hidden = secret_local
        raise ValueError("it broke")

    try:
        deep()
    except ValueError as err:
        lines = report_send.exception_lines(err)
    assert lines[0] == "ValueError: it broke"
    assert all(secret_local not in line for line in lines)
    assert all(line.startswith("  ") and " in " in line for line in lines[1:])

    def engine_frame():
        raise KeyError("k")

    # A frame outside the app's packages (this test file) is not kept.
    try:
        engine_frame()
    except KeyError as err:
        assert report_send.exception_lines(err) == ["KeyError: 'k'"]


def test_the_facts_show_the_details_a_send_carries_and_unchecking_them_sends_none(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    client, app, _cfg = make_client(tmp_path, LOCAL_FORM)
    log = private_dir(tmp_path / "ws") / "logs" / "thimbleby.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("2026-01-01 ERROR engine.x: mail from a.b@example.org failed\n", encoding="utf-8")
    with client:
        shown = client.get("/api/report/facts").json()["details"]
        assert "a.b@example.org" not in shown and "<address>" in shown
        client.post("/api/report/send", json={"words": WORDS, "details": shown})
        client.post("/api/report/send", json={"words": WORDS, "details": shown, "include_details": False})
    assert seen[0][1]["details"] == shown
    assert "details" not in seen[1][1]


@pytest.mark.parametrize(
    ("status", "why"), [(429, "busy"), (503, "unavailable"), (500, "unavailable"), (400, "refused"), (403, "refused")]
)
def test_a_form_that_does_not_take_it_says_why(monkeypatch, status, why):
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(status))
    done = report_send.send(LOCAL_FORM, words=WORDS, reply_to="", version="1", problems="")
    assert (done.ok, done.why) == (False, why)


def test_no_connection_says_offline(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(engine.net, "TRANSPORT", httpx.MockTransport(refuse))
    done = report_send.send(LOCAL_FORM, words=WORDS, reply_to="", version="1", problems="")
    assert (done.ok, done.why) == (False, "offline")


def make_client(tmp_path, address: str):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    flags = {"storage.backups.automatic": False, **({"ui.report_to": address} if address else {})}
    cfg = ws.config(env={}, flags=flags)
    app = create_app(ws, cfg, TOKEN, ui_dist=ws.root / "no-ui")
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}), app, cfg


def test_with_no_address_the_item_is_not_offered_and_a_send_is_refused(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    client, _app, _cfg = make_client(tmp_path, "")
    with client:
        assert client.get("/api/runtime-config").json()["report_enabled"] is False
        assert client.get("/api/report/facts").json()["enabled"] is False
        assert client.post("/api/report/send", json={"words": WORDS}).status_code == 404
    assert seen == []


def test_the_facts_offer_the_persons_own_address_and_a_send_reaches_the_form_once(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    client, app, cfg = make_client(tmp_path, LOCAL_FORM)
    with client:
        assert client.get("/api/runtime-config").json()["report_enabled"] is True
        facts = client.get("/api/report/facts").json()
        with app.state.store.read_scope():
            mine = own_address(app.state.store.read(), cfg.workspace.user.person)
        assert facts["enabled"] is True and facts["reply_to"] == mine
        assert facts["system"] == report_send.system_text() and facts["version"]
        # Nothing has left before Send.
        assert seen == []
        sent = client.post(
            "/api/report/send", json={"words": f"  {WORDS} ", "reply_to": " a@example.com ", "problems": LINES}
        )
    assert sent.json() == {"ok": True, "why": None}
    ((url, body),) = seen
    assert url == LOCAL_FORM
    assert body == {
        "words": WORDS,
        "reply_to": "a@example.com",
        "version": facts["version"],
        "system": facts["system"],
        "problems": LINES,
    }


def test_a_refusal_and_empty_words_are_answered_without_sending(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(503, seen))
    client, _app, _cfg = make_client(tmp_path, LOCAL_FORM)
    with client:
        down = client.post("/api/report/send", json={"words": WORDS})
        assert down.json() == {"ok": False, "why": "unavailable"}
        assert client.post("/api/report/send", json={"words": ""}).status_code == 422
    assert len(seen) == 1


def test_details_are_measured_as_the_form_counts_them_so_wide_characters_never_push_them_over():
    from engine.report_send import details_text, units

    wide = "\U0001f600" * 30  # each counts twice on the form
    text = details_text("\n".join(f"line {i} {wide}" for i in range(2000)), masker=lambda s: s or "", limit=1000)
    assert 0 < units(text) <= 1000
    assert text.endswith(f"line 1999 {wide}")
    one_long = details_text(wide * 100, masker=lambda s: s or "", limit=51)
    assert 0 < units(one_long) <= 51


def test_a_send_with_no_facts_call_still_carries_the_version_and_system(tmp_path, monkeypatch):
    """The form doesn't wait for the facts: whatever it sent, the app adds its own version and system."""
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    client, _app, _cfg = make_client(tmp_path, LOCAL_FORM)
    with client:
        done = client.post("/api/report/send", json={"words": WORDS}).json()
    assert done["ok"] is True
    body = seen[0][1]
    assert body["version"] and body["system"] == report_send.system_text()


ANSWER = "The assistant's own words, with the person's material: ask Pat about the Henderson order."


def stop_a_request(app, cfg, *, answer: str | None = ANSWER, state: str = "needs_you", days_ago: int = 0) -> str:
    """A request that stopped for the person, with the answer it kept; made `days_ago` days before the store's clock."""
    from datetime import datetime, timedelta

    store = app.state.store
    made = datetime.fromisoformat(store.clock()) - timedelta(days=days_ago)
    task = next(iter(cfg.ai.tasks))
    data = {"task": task, "origin": "pm", "state": state, "created_at": made.isoformat(), "stopped_answer": answer}
    with store.transaction() as tx:
        created = tx.create("request", data, WriteContext(actor="engine", trust="trusted", op="test"))
    return created.id if hasattr(created, "id") else str(created)


def test_the_answer_is_offered_only_with_a_kept_answer_within_the_window(tmp_path):
    client, app, cfg = make_client(tmp_path, LOCAL_FORM)
    with client:
        assert client.get("/api/report/facts").json()["answer"] == ""
        stop_a_request(app, cfg, answer=None)
        stop_a_request(app, cfg, state="done")
        stop_a_request(app, cfg, days_ago=cfg.ui.feedback_problem_days + 5)
        assert client.get("/api/report/facts").json()["answer"] == ""
        stop_a_request(app, cfg, answer="An older answer.", days_ago=1)
        stop_a_request(app, cfg)
        facts = client.get("/api/report/facts").json()
    assert facts["answer"].endswith("\n" + ANSWER) and "An older answer." not in facts["answer"]
    assert facts["answer"].startswith("The assistant's last answer, from the request made 20")


def test_off_nothing_of_the_answer_is_sent_and_on_exactly_the_previewed_text_is(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    client, app, cfg = make_client(tmp_path, LOCAL_FORM)
    log = private_dir(tmp_path / "ws") / "logs" / "thimbleby.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("2026-01-01 WARNING engine.x: slow\n", encoding="utf-8")
    stop_a_request(app, cfg)
    with client:
        facts = client.get("/api/report/facts").json()
        shown, details = facts["answer"], facts["details"]
        assert ANSWER in shown and ANSWER not in details
        base = {"words": WORDS, "details": details, "answer_block": shown}
        client.post("/api/report/send", json=base)  # the choice defaults to off
        client.post("/api/report/send", json={**base, "include_answer": False})
        client.post("/api/report/send", json={**base, "include_answer": True})
        client.post("/api/report/send", json={**base, "include_answer": True, "include_details": False})
        # Only the preview the server made goes: an empty or a changed block with the choice on is refused, and
        # nothing is sent (the #67 re-check, N-5).
        empty = client.post("/api/report/send", json={**base, "include_answer": True, "answer_block": ""})
        forged = client.post("/api/report/send", json={**base, "include_answer": True, "answer_block": shown + " more"})
    assert empty.status_code == 409 and forged.status_code == 409
    off_default, off, on, on_alone = (body for _url, body in seen)
    assert ANSWER not in json.dumps([off_default, off])
    assert off["details"] == details
    assert on["details"] == f"{details}\n\n{shown}" and ANSWER in on["details"]
    assert on_alone["details"] == shown
    assert all(set(body) <= set(report_send.LIMITS) for _url, body in seen)


def test_a_long_log_and_the_longest_answer_still_fit_the_form(tmp_path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(engine.net, "TRANSPORT", serve(200, seen))
    client, app, cfg = make_client(tmp_path, LOCAL_FORM)
    log = private_dir(tmp_path / "ws") / "logs" / "thimbleby.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "\n".join(f"2026-01-01 WARNING engine.x: line {n:06d} " + "y" * 90 for n in range(2000)), encoding="utf-8"
    )
    stop_a_request(app, cfg, answer="z" * 50000)
    with client:
        facts = client.get("/api/report/facts").json()
        assert report_send.units(facts["answer"]) <= report_send.ANSWER_MAX + report_send.ANSWER_HEADING_ROOM
        sent = client.post(
            "/api/report/send",
            json={"words": WORDS, "details": facts["details"], "answer_block": facts["answer"], "include_answer": True},
        )
    assert sent.json() == {"ok": True, "why": None}
    assert report_send.units(seen[0][1]["details"]) <= report_send.LIMITS["details"]
    assert seen[0][1]["details"].endswith(facts["answer"])
