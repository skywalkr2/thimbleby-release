"""The parcels add-on (S-0522): the common carriers' public tracking pages are its data, and it reads the page of a
delivery that has no arrival day yet. Every page here is a saved, made-up page; nothing reaches the network. Carrier
names and pages are read from the add-on's own file, never written out here."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import yaml

from engine import delivery_tracking, today
from engine import net as net_module
from engine.ai.adapters.stub import set_responder
from engine.ai.router import Router
from engine.config import load_config
from engine.dispatcher import process
from engine.plugin_host import BUNDLED
from engine.plugin_manifest import read_manifest
from engine.storage import Store
from engine.workspace import init_workspace
from tests.conftest import DEMO_B
from tests.test_deliveries import NOW, TRACKING_A, WEB, apply, delivery_op, entries, only

PLUGIN = BUNDLED / "parcels"
MANIFEST = read_manifest(PLUGIN / "plugin.yaml")
CARRIERS = yaml.safe_load((PLUGIN / "carriers.yaml").read_text(encoding="utf-8"))["carriers"]
CARRIER = CARRIERS[0]
#: The carrier as a mail writes it: the words of its entry, capitalized.
NAME = " ".join(w.capitalize() for w in CARRIER["words"])
DAY = "2026-11-19"
STATES = "Estimated delivery: Thursday, November 19"
PAGE = f"<html><head><script>var x = 1;</script></head><body><h1>Tracking</h1><p>{STATES}</p></body></html>"
NO_DAY = "<html><body><h1>Tracking</h1><p>Your parcel has left the sorting centre.</p></body></html>"
SCRIPTS_ONLY = "<html><head><script>window.location = '/app';</script></head><body><noscript>x</noscript></body></html>"


def make_env(tmp_path, *, plugin_settings: dict | None = None, enabled: bool = True):
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    path = ws.config_dir / "workspace.yaml"
    settings = yaml.safe_load(path.read_text())
    others = [name for name in settings["plugins"]["enabled"] if name != "parcels"]
    settings["plugins"]["enabled"] = [*others, *(["parcels"] if enabled else [])]
    path.write_text(yaml.safe_dump(settings))
    if plugin_settings:
        (ws.config_dir / "plugins" / "parcels.yaml").write_text(yaml.safe_dump({"version": 1, **plugin_settings}))
    cfg = load_config(ws.config_dir, env={"COCKPIT__WORKSPACE__USER__TIMEZONE": "UTC"})
    return ws, cfg, Store(ws.db_path, cfg=cfg)


class Pages:
    """The saved pages the carrier's address answers with, and every address asked for."""

    def __init__(self) -> None:
        self.answer: Any = httpx.Response(200, text=PAGE)
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(str(request.url))
        return self.answer


@pytest.fixture
def pages(monkeypatch):
    pages = Pages()
    monkeypatch.setattr(net_module, "TRANSPORT", httpx.MockTransport(pages))
    return pages


@pytest.fixture
def env(tmp_path, pages):
    ws, cfg, store = make_env(tmp_path)
    assert store.plugins.active("parcels"), store.plugins.status["parcels"].reason
    yield ws, cfg, store, pages
    store.close()
    set_responder(None)


def undated(ws, cfg, store, tracking: str = TRACKING_A, carrier: str = NAME) -> Any:
    """A delivery from a mail that gave no day: one entry, on no day."""
    apply((ws, cfg, store), [delivery_op("Shipped", tracking=tracking, carrier=carrier)])
    return entries(store)[-1]


def waiting(store, task: str = "parcels/read-arrival") -> list[Any]:
    return [r for r in store.read().list("request") if r.data["task"] == task]


def answer(quote: str, start: str = DAY, **more: Any) -> Any:
    op = {
        "op": "event.add",
        "title": "Parcel",
        "start": start,
        "delivery": {"tracking": TRACKING_A, "carrier": NAME},
        "evidence": {"quote": quote},
        **more,
    }
    return lambda task: json.dumps({"summary": "Expected.", "ops": [op]})


def run(ws, cfg, store) -> list[Any]:
    """The lookup, then the assistant's reading of each page it queued."""
    assert store.plugins.run_job("parcels/lookup", datetime.now(UTC)) == "ok"
    queued = waiting(store)
    for request in queued:
        process(ws, store, cfg, Router(cfg, store, env={}), request.id)
    return queued


# ---- the carriers' pages are the add-on's data -----------------------------------------------------------------------


def test_every_carrier_page_is_a_plain_address_on_a_host_the_add_on_declares():
    from engine.config.schema import CarrierPage

    assert MANIFEST.provides.delivery_carriers == ["carriers.yaml"]
    hosts = set(MANIFEST.requires.network)
    for entry in CARRIERS:
        carrier = CarrierPage.model_validate(entry)
        assert carrier.page.split("/")[0] in hosts, carrier.id


def test_with_the_add_on_on_a_listed_carriers_delivery_has_a_track_link_to_its_page(tmp_path, pages):
    ws, cfg, store = make_env(tmp_path)
    try:
        undated(ws, cfg, store)
        [item] = today.agenda(store, cfg, NOW, through=NOW.date(), undated=True)
        expected = WEB + CARRIER["page"].replace("{number}", TRACKING_A)
        assert item.delivery["track"] == expected
        assert "tracking" not in item.delivery
    finally:
        store.close()


def test_without_the_add_on_that_carrier_has_no_track_link(tmp_path, pages):
    ws, cfg, store = make_env(tmp_path, enabled=False)
    try:
        undated(ws, cfg, store)
        [item] = today.agenda(store, cfg, NOW, through=NOW.date(), undated=True)
        assert item.delivery["track"] is None
        assert delivery_tracking.page_for(cfg, NAME, TRACKING_A) is None
    finally:
        store.close()


def test_a_workspaces_own_carrier_with_an_add_ons_id_replaces_it(tmp_path, pages):
    from engine.config.schema import CarrierPage

    ws, cfg, store = make_env(tmp_path)
    try:
        mine = CarrierPage(id=CARRIER["id"], words=CARRIER["words"], page="mine.example.com/{number}")
        cfg.ui.today.delivery_carriers_extra = [mine]
        added = store.plugins.delivery_carriers()
        assert delivery_tracking.page_for(cfg, NAME, "7", added) == f"{WEB}mine.example.com/7"
        assert {c.id for c in store.plugins.delivery_carriers()} == {c["id"] for c in CARRIERS}
    finally:
        store.close()


# ---- the lookup ------------------------------------------------------------------------------------------------------


def test_a_page_with_the_day_dates_the_delivery_and_the_page_is_outside_content(env):
    ws, cfg, store, pages = env
    entry = undated(ws, cfg, store)
    assert entry.data["delivery"]["dated"] is False
    set_responder(answer(STATES))
    [request] = run(ws, cfg, store)
    assert pages.asked == [WEB + CARRIER["page"].replace("{number}", TRACKING_A)]
    assert request.data["about"] == {"kind": "event", "id": entry.id}
    assert "<script" not in request.data["note"] and "var x" not in request.data["note"]
    assert STATES in request.data["note"]
    dated = only(store)
    assert dated.id == entry.id  # the one entry, not a second
    assert dated.data["start"] == DAY and dated.data["delivery"]["dated"] is True
    assert store.read().get("request", request.id).data["state"] in ("done", "review")


def test_the_assistant_sees_the_page_as_outside_content_and_the_parcel_beside_it(env):
    from datetime import date

    from engine.packet import build

    ws, cfg, store, pages = env
    undated(ws, cfg, store)
    assert store.plugins.run_job("parcels/lookup", datetime.now(UTC)) == "ok"
    [request] = waiting(store)
    packet = build(ws, store, cfg, request.id, date(2026, 11, 16))
    assert '<untrusted source="note">' in packet.task.request and STATES in packet.task.request
    assert TRACKING_A in packet.task.request  # the parcel part, so the answer can name the one entry
    assert packet.untrusted_material or request.data["origin"] != "pm"


def test_a_page_with_no_day_leaves_the_delivery_undated(env):
    ws, cfg, store, pages = env
    pages.answer = httpx.Response(200, text=NO_DAY)
    entry = undated(ws, cfg, store)
    set_responder(lambda task: json.dumps({"summary": "The page states no day.", "ops": []}))
    run(ws, cfg, store)
    left = only(store)
    assert left.id == entry.id and left.data["delivery"]["dated"] is False
    assert left.data["start"] == entry.data["start"]


def test_a_page_that_only_works_with_scripts_is_not_sent_to_the_assistant(env):
    ws, cfg, store, pages = env
    pages.answer = httpx.Response(200, text=SCRIPTS_ONLY)
    undated(ws, cfg, store)
    assert run(ws, cfg, store) == []
    assert waiting(store) == [] and only(store).data["delivery"]["dated"] is False


@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
def test_a_page_that_refuses_the_read_leaves_the_delivery_undated(env, status):
    ws, cfg, store, pages = env
    pages.answer = httpx.Response(status, text="Access denied")
    undated(ws, cfg, store)
    assert run(ws, cfg, store) == []
    assert only(store).data["delivery"]["dated"] is False


def test_no_connection_leaves_the_delivery_undated_and_the_job_ok(env, monkeypatch):
    ws, cfg, store, pages = env

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(net_module, "TRANSPORT", httpx.MockTransport(offline))
    undated(ws, cfg, store)
    assert run(ws, cfg, store) == []
    assert only(store).data["delivery"]["dated"] is False
    assert store.plugins.active("parcels")


def test_a_day_that_is_not_in_the_pages_words_is_refused(env):
    ws, cfg, store, pages = env
    entry = undated(ws, cfg, store)
    set_responder(answer("Estimated delivery: Friday, November 20", "2026-11-20"))
    [request] = run(ws, cfg, store)
    left = only(store)
    assert left.id == entry.id and left.data["delivery"]["dated"] is False
    applied = [o for c in store.read().list("changeset") for o in c.data["ops"] if o["op"]["op"] == "event.add"]
    assert applied and all(o["status"] != "applied" for o in applied[-1:])
    assert request.id


def test_the_lookup_stops_once_the_delivery_is_dated_or_arrived(env):
    ws, cfg, store, pages = env
    undated(ws, cfg, store)
    set_responder(answer(STATES))
    run(ws, cfg, store)
    assert len(pages.asked) == 1 and only(store).data["delivery"]["dated"] is True
    assert store.plugins.run_job("parcels/lookup", datetime.now(UTC)) == "ok"
    assert len(pages.asked) == 1  # dated: not read again
    # A delivery that arrived with no day is dated by the day it arrived, and is not read either.
    apply(
        (ws, cfg, store),
        [delivery_op("Delivered", tracking="ARR-1", carrier=NAME, order="ORD-ARR", status="arrived")],
    )
    assert store.plugins.run_job("parcels/lookup", datetime.now(UTC)) == "ok"
    assert len(pages.asked) == 1


def test_a_parcel_being_read_is_not_queued_twice_and_one_with_no_known_carrier_is_not_read(env):
    ws, cfg, store, pages = env
    undated(ws, cfg, store)
    undated(ws, cfg, store, tracking="OTHER-1", carrier="A Carrier Nobody Listed")
    assert store.plugins.run_job("parcels/lookup", datetime.now(UTC)) == "ok"
    assert store.plugins.run_job("parcels/lookup", datetime.now(UTC)) == "ok"
    assert len(waiting(store)) == 1 and len(pages.asked) == 1


def test_a_carrier_whose_host_the_add_on_does_not_declare_is_not_read(env):
    from engine.config.schema import CarrierPage

    ws, cfg, store, pages = env
    cfg.ui.today.delivery_carriers_extra = [
        CarrierPage(id="mine", words=["Mine"], page="elsewhere.example.com/{number}")
    ]
    undated(ws, cfg, store, tracking="MINE-1", carrier="Mine Couriers")
    assert run(ws, cfg, store) == []
    assert pages.asked == []


# ---- how often, and how many ---------------------------------------------------------------------------------------


def test_a_parcel_is_read_as_often_as_the_setting_says_and_no_more(tmp_path, pages):
    for reads, minutes in ((2, 720), (4, 360), (1, 1440)):
        ws, cfg, store = make_env(tmp_path / str(reads), plugin_settings={"reads_per_day": reads})
        try:
            assert store.plugins.job_settings("parcels/lookup") == (True, minutes)
        finally:
            store.close()


def test_one_run_reads_no_more_parcels_than_the_setting_allows(tmp_path, pages):
    ws, cfg, store = make_env(tmp_path, plugin_settings={"max_parcels_per_run": 2})
    try:
        for n in range(4):
            undated(ws, cfg, store, tracking=f"TRK-{n}")
        assert store.plugins.run_job("parcels/lookup", datetime.now(UTC)) == "ok"
        assert len(pages.asked) == 2
    finally:
        store.close()


def test_the_page_text_drops_scripts_and_markup_and_is_cut_at_the_limit():
    import importlib.util

    spec = importlib.util.spec_from_file_location("parcels_under_test", PLUGIN / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.page_text("<p>One &amp; two</p><style>p{}</style><div>Three<br>Four</div><script>no()</script>", 100)
    assert text.splitlines() == ["One & two", "Three", "Four"]
    assert module.page_text("A" * 50, 10) == "A" * 10
    assert module.page_text("", 10) == ""


# ---- what the core gives an add-on that ships carriers or reads a page ---------------------------------------------


def scratch(tmp_path, carriers_text: str, *, network: list[str] | None = None, job: bool = False):
    """A made-up add-on that ships a carriers file (and, with `job`, a job that reads one address)."""
    ws = init_workspace(tmp_path / "ws", template=DEMO_B, git=False)
    root = ws.root / "plugins" / "scratch"
    root.mkdir(parents=True)
    (root / "carriers.yaml").write_text(carriers_text)
    manifest = {
        "name": "scratch",
        "version": "0.1.0",
        "plugin_api": ">=0.3,<0.4",
        "description": "Ships carriers",
        "entry": "scratch:register",
        "config_schema": "scratch:Config",
        "provides": {"delivery_carriers": ["carriers.yaml"], **({"jobs": ["scratch/look"]} if job else {})},
        "requires": {"network": network or []},
    }
    (root / "plugin.yaml").write_text(yaml.safe_dump(manifest))
    (root / "scratch.py").write_text(
        "from engine.plugin_api import Settings\n"
        "SEEN = []\n"
        "class Config(Settings):\n    pass\n"
        "def look(context):\n"
        "    SEEN.append(context.web)\n"
        "    if context.web is not None:\n"
        f"        SEEN.append(context.web.get('{WEB}pages.example.com/x').status)\n"
        "def register(registrar):\n"
        + ("    registrar.job('scratch/look', every_minutes=60, run=look)\n" if job else "    pass\n")
    )
    path = ws.config_dir / "workspace.yaml"
    settings = yaml.safe_load(path.read_text())
    settings["plugins"]["enabled"] = [*settings["plugins"]["enabled"], "scratch"]
    path.write_text(yaml.safe_dump(settings))
    cfg = load_config(ws.config_dir, env={})
    return ws, cfg, Store(ws.db_path, cfg=cfg)


def test_an_entry_in_an_add_ons_carriers_file_that_is_not_a_name_and_a_page_is_left_out_and_noted(tmp_path):
    text = (
        "carriers:\n"
        "  - {id: good, words: [Good], page: 'good.example.com/{number}'}\n"
        "  - {id: no-number, words: [Bad], page: 'bad.example.com/track'}\n"
        f"  - {{id: scheme, words: [Bad], page: '{WEB}bad.example.com/{{number}}'}}\n"
    )
    ws, cfg, store = scratch(tmp_path, text)
    try:
        ids = [c.id for c in store.plugins.delivery_carriers()]
        assert "good" in ids and "no-number" not in ids and "scheme" not in ids
        assert any("left out" in note for note in store.plugins.status["scratch"].notes)
    finally:
        store.close()


def test_a_carriers_file_outside_the_plugin_or_not_yaml_is_refused_by_the_manifest():
    from pydantic import ValidationError

    from engine.plugin_manifest import Provides

    for bad in ("/etc/carriers.yaml", "../carriers.yaml", "carriers.txt"):
        with pytest.raises(ValidationError):
            Provides(delivery_carriers=[bad])


def test_a_job_gets_a_web_client_for_its_declared_hosts_only_and_a_handler_gets_none(tmp_path, pages):
    import sys

    pages.answer = httpx.Response(200, text="ok")
    ws, cfg, store = scratch(tmp_path, "carriers: []\n", network=["pages.example.com"], job=True)
    try:
        assert store.plugins.active("scratch"), store.plugins.status["scratch"].reason
        assert store.plugins.run_job("scratch/look") == "ok"
        seen = next(m for n, m in sys.modules.items() if n.endswith("scratch") and hasattr(m, "SEEN")).SEEN
        assert seen[0] is not None and seen[1] == 200
        assert pages.asked == [f"{WEB}pages.example.com/x"]
    finally:
        store.close()


def test_a_job_of_an_add_on_with_no_hosts_has_no_web_client(tmp_path, pages):
    import sys

    ws, cfg, store = scratch(tmp_path, "carriers: []\n", network=[], job=True)
    try:
        assert store.plugins.run_job("scratch/look") == "ok"
        seen = next(m for n, m in sys.modules.items() if n.endswith("scratch") and hasattr(m, "SEEN")).SEEN
        assert seen == [None]
    finally:
        store.close()
