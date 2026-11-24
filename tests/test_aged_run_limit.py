"""A workspace with months of history still gets its everyday runs under the default per-run limit (S-0782).

The packets of the everyday kinds of work are measured on a demo with about three months of made-up history, priced on
the model each tier of an account's recommended setup takes (the newest of the preset's family at the shipped price) and
on the cheapest priced model, and held against the limit a new workspace starts with. The history is doubled before the
check, so the limit has room for a workspace twice as old."""

from __future__ import annotations

import pytest

from engine import tasks
from engine.ai import shipped_prices
from engine.config.schema import Budgets
from engine.setup import known_endpoints
from engine.storage import Store
from engine.workspace import init_workspace
from tests.aged_workspace import age, everyday_requests, packet_tokens
from tests.conftest import DEMO_A

#: How many times the measured history the limit must still hold for.
ROOM_TO_GROW = 2


def models_by_tier(service: str, presets: dict[str, dict[str, str]]) -> dict[str, tuple[float, float]]:
    """The (input, output) price per million tokens of the model each preset tier takes: the newest of its family."""
    table = shipped_prices._table()[service]["models"]
    found = {}
    for tier, preset in presets.items():
        of_family = [m for m in table if preset["family"] in str(m["family"]).casefold()]
        newest = max(of_family, key=lambda m: shipped_prices._version(m["version"]))
        found[tier] = (float(newest["input"]), float(newest["output"]))
    return found


def cheapest(service: str) -> tuple[float, float]:
    return min(
        ((float(m["input"]), float(m["output"])) for m in shipped_prices._table()[service]["models"]),
        key=lambda price: price[0] + price[1],
    )


def cost(tokens: int, answer: int, price: tuple[float, float]) -> float:
    return (tokens * price[0] + answer * price[1]) / 1e6


@pytest.fixture(scope="module")
def aged(tmp_path_factory):
    ws = init_workspace(tmp_path_factory.mktemp("aged") / "ws", template=DEMO_A, git=False)
    cfg = ws.config(env={})
    store = Store(ws.db_path, cfg=cfg)
    age(ws, store, cfg)
    requests = everyday_requests(ws, store, cfg)
    yield cfg, store, packet_tokens(ws, store, cfg, requests)
    store.close()


def services_with_presets() -> list[tuple[str, dict[str, dict[str, str]]]]:
    priced = shipped_prices._table()
    return [(e["id"], e["tier_presets"]) for e in known_endpoints() if e["tier_presets"] and e["id"] in priced]


def test_the_default_limit_holds_every_everyday_run_on_an_aged_workspace_on_every_preset_model(aged):
    cfg, store, sizes = aged
    limit = Budgets().per_run_usd
    found = services_with_presets()
    assert found, "no service with a recommended setup has a shipped price to measure on"
    over = []
    for service, presets in found:
        prices = {**models_by_tier(service, presets), "cheapest": cheapest(service)}
        for kind, tokens in sizes.items():
            answer = tasks.settings(cfg, store.plugins.task_kind(kind)).expected_output
            for tier, price in prices.items():
                spent = cost(tokens * ROOM_TO_GROW, answer, price)
                if spent > limit:
                    over.append(f"{service} {kind} on {tier}: ${spent:.3f} of ${limit:.2f}")
    assert not over, over


def test_the_workspaces_start_with_the_default_limit_or_more(aged):
    cfg, _, _ = aged
    assert cfg.ai.budgets.per_run_usd >= Budgets().per_run_usd
