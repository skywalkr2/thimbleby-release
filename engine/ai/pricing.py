"""What an account's cost is, and when a run on it waits for the person's go (design 6.16, "Waiting for a go").

A model's cost is one of three. *Priced*: the adapter's `models()` or `ai.prices` gives it a price. *Flat*: a
subscription or a model on the person's own computer, where a run costs the person nothing more; the account says so
itself (`flat_rate`), or its kind declares it (a command-line agent, the stand-in, a server on this computer).
*Unknown*: anything else. An unknown price is never counted as nothing: a run on it waits for the person's go every
time, until they give the model a price (`ai.prices`) or say the account is flat. A flat account asks only when
`ai.budgets.confirm_unpriced` is on.
"""

from __future__ import annotations

from typing import Any

PRICED = "priced"
FLAT = "flat"
UNKNOWN = "unknown"

#: The adapters whose accounts cost nothing per run by what they are: a command-line agent runs on the person's own
#: subscription, and the stand-in used for trying the app and for tests calls no service at all.
FLAT_ADAPTERS = ("cli-agent", "stub")


def is_flat(cfg: Any, provider: str) -> bool:
    """Whether the account is flat-rate: the person said so, or its adapter or its kind in the catalog declares it."""
    settings = cfg.ai.providers.get(provider)
    if settings is None:
        return False
    if settings.flat_rate is not None:  # the person's own answer wins over what the kind declares
        return settings.flat_rate
    if settings.adapter in FLAT_ADAPTERS:
        return True
    if not settings.kind:
        return False
    from engine.setup import known_endpoints

    return any(e["id"] == settings.kind and e.get("local") for e in known_endpoints())


def state_of(cfg: Any, provider: str, price: float | None) -> str:
    """`priced` when a price is known, else `flat` or `unknown` by the account."""
    if price is not None:
        return PRICED
    return FLAT if is_flat(cfg, provider) else UNKNOWN


def go_needed(cfg: Any, state: str | None) -> bool:
    """Whether a run whose cost is in this state waits for the person's go for want of a price: always when unknown, and
    when flat only if the person asked to be asked about those too. A priced run, or none no account takes, never does
    (the amount to ask above covers a priced one)."""
    if state == UNKNOWN:
        return True
    return state == FLAT and cfg.ai.budgets.confirm_unpriced


def allowed_without_price(cfg: Any, state: str, go_given: bool) -> bool:
    """Whether a call on an account in this state may be made: with a go given for an unpriced run any may; without one,
    a flat account only when the person didn't ask to be asked about those, and an unknown one never."""
    if state == PRICED or go_given:
        return True
    return state == FLAT and not cfg.ai.budgets.confirm_unpriced


def covered_by_the_persons_go(cfg: Any) -> Any:
    """Make every account of a practice workspace one a run may use without waiting for a go for want of a price. A
    practice run is the person's own command (an evaluation, the check after switching accounts), with its cost shown
    to them first, so the go has been given; the practice workspace is thrown away, never the person's own settings."""
    for settings in cfg.ai.providers.values():
        settings.flat_rate = True
    return cfg
