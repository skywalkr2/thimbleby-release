"""Smoke test for the AI setup (design 6.16): one small live call per configured tier and account, with the exact
parameters the work will use, so a setting a model refuses is found before real work fails.

The result is kept with a fingerprint of `ai.yaml`, so the server can say when the settings changed since the last test.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import UTC, datetime
from functools import partial
from typing import Any
from urllib.parse import urlsplit

from engine.ai import check_cost, learning_check, spending
from engine.ai.adapters import make_adapter
from engine.ai.calibration import SAMPLE_INSTRUCTIONS, SAMPLE_REQUEST, estimate_tokens
from engine.ai.task import (
    NO_WORK_KINDS,
    RETIRED_PLAIN,
    UNSUPPORTED_ADVICE,
    UNSUPPORTED_PLAIN,
    AiError,
    AiTask,
    CountNotOffered,
    IdentityUnknown,
    ModelInfo,
    provider_reason,
    work_in_words,
)
from engine.config import Config, load_config
from engine.secrets import SecretError, describe_secret, resolve_secret
from engine.state_file import write_whole
from engine.storage import Store, WriteContext
from engine.workspace import Workspace

STATUS_FILE = "ai-test.json"
_REQUEST = 'Reply with exactly this JSON and nothing else: {"ok": true}'


@dataclass
class SmokeResult:
    tier: str
    account: str
    main: bool
    ok: bool
    detail: str
    seconds: float = 0.0
    key_source: str | None = None
    provider: str = ""  # the account's short name
    answered: bool = False  # the account's call went through, whatever it said
    offline: bool = False  # no connection could be made at all: the test says nothing about the account
    ref: str = ""  # the "account/model" the result is about
    part: str = "call"  # call (one kind of work's parameters), lockdown, learning, identity or calibration
    params: list[Any] = field(default_factory=list)  # for a call: the kind of work, temperature and most output
    identity: dict[str, str] | None = None  # for identity: {account, how_read}, or {unknown: the reason}
    error_kind: str = ""  # when the call failed: the kind the call itself gave (never read from the account's words)
    error_detail: str = ""  # when the call failed: the service's own error text, for a report of the failure
    # For a calibration: what the check measured for the estimates (a counted sample, and the input tokens the check's
    # first call reported with what its own text counts).
    calibration: dict[str, Any] | None = None


def _params_for_tier(cfg: Config, tier: str) -> list[tuple[Any, ...]]:
    """(task kind, temperature, max_output) for every task kind that runs on this tier, directly or by escalation,
    with the tier's effort added as a fourth part when it has one (a tier without one keeps the three parts)."""
    uses = [(k, t.temperature, t.max_output) for k, t in cfg.ai.tasks.items() if t.tier == tier]
    if not uses:
        uses = [
            (k, t.temperature, t.max_output)
            for k, t in cfg.ai.tasks.items()
            if cfg.ai.tiers.get(t.tier) and cfg.ai.tiers[t.tier].escalate_to == tier
        ]
    effort = cfg.ai.tiers[tier].effort if tier in cfg.ai.tiers else None
    return [(*use, effort) if effort else use for use in uses or [("smoke", 0.0, 256)]]


#: What a check's model calls are recorded as: the kind of work, and the tier, so every report of the runs names them.
CHECK_TASK = CHECK_TIER = spending.ACCOUNT_CHECK
_SYSTEM = WriteContext(actor="engine", trust="trusted", op="run.record")


class _Spending:
    """Passes a check's model calls through the spending boundary (`engine/ai/spending.py`), like any other paid call.
    The whole check is admitted before its first call, with about what its calls cost held while it runs; each call
    that was answered, or that may have reached the service and got no answer, is recorded as a run of the kind
    `CHECK_TASK` with its cost, and its share of what is held is given back. Without a store nothing is counted."""

    def __init__(self, cfg: Config, store: Any, now: Callable[[], datetime] | None = None):
        self.cfg, self.store = cfg, store
        self.now = now or (lambda: datetime.now(UTC))
        self.hold: spending.Hold | None = None
        self._catalogs: Any = None

    def prices(self, provider: str, settings: Any, model_key: str, model_id: str) -> tuple[float, float] | None:
        """The model's price per million tokens read and written: the settings', then the kept catalog's (nothing is
        fetched), then the price the app ships for its kind of service. None when none is known."""
        price = self.cfg.ai.prices.get(f"{provider}/{model_key}")
        if price is not None:
            return price.input_per_million, price.output_per_million
        if self._catalogs is None:
            from engine.ai.catalog import Catalogs
            from engine.legacy_names import private_dir

            self._catalogs = Catalogs(
                private_dir(self.store.path.parent) / "ai-catalog.json", self.cfg.ai.catalog_refresh_hours
            )
        info = self._catalogs.model(provider, model_id, lambda: {})
        if info is not None and info.input_per_million is not None and info.output_per_million is not None:
            return info.input_per_million, info.output_per_million
        from engine.ai.shipped_prices import price_for

        known = price_for(getattr(settings, "kind", None), model_id)
        return (known["input"], known["output"]) if known is not None else None

    def of_call(self, provider: str, settings: Any, model_key: str, model_id: str, calls: int = 1) -> float | None:
        """About what `calls` of the check's small calls cost on this model, as the estimate shown before a check
        counts them; None when its price isn't known."""
        found = self.prices(provider, settings, model_key, model_id)
        if found is None:
            return None
        read, write = found
        return calls * (check_cost.CALL_INPUT_TOKENS * read + check_cost.CALL_OUTPUT_TOKENS * write) / 1e6

    def admit(self, refs: list[tuple[str, int]]) -> None:
        """Admit the whole check: `refs` is every "account/model" it calls with how many small calls it makes there.
        Raises `BudgetReached` when the limits have no room for it; nothing is sent then."""
        if self.store is None:
            return
        total = 0.0
        for ref, calls in refs:
            provider, _, model_key = ref.partition("/")
            settings = self.cfg.ai.providers[provider]
            total += self.of_call(provider, settings, model_key, settings.models.get(model_key, model_key), calls) or 0
        self.hold = spending.admit(self.store, self.cfg.ai.budgets, CHECK_TASK, total, self.now())

    def close(self) -> None:
        spending.release(self.hold)
        self.hold = None

    def call(self, ref: str, settings: Any, model_id: str, task: AiTask, run: Callable[[], Any], calls: int = 1) -> Any:
        """Make one of the check's model calls and count it. The answer, or the call's own error, comes back as it
        was."""
        if self.store is None:
            return run()
        provider, _, model_key = ref.partition("/")
        estimate = self.of_call(provider, settings, model_key, model_id, calls)
        started, clock = self.now(), time.monotonic()
        try:
            reply = run()
        except AiError as err:
            reached = err.kind in spending.MAY_HAVE_REACHED and err.sent
            if reached and estimate:
                self._record(provider, model_id, task, started, clock, estimate, None, err, estimate)
            else:
                spending.reduce(self.hold, estimate or 0.0)
            raise
        except BaseException:
            spending.reduce(self.hold, estimate or 0.0)
            raise
        cost, basis = reply.cost_usd, None
        found = self.prices(provider, settings, model_key, model_id)
        if cost is None and found is not None and reply.input_tokens is not None and reply.output_tokens is not None:
            cost = (reply.input_tokens * found[0] + reply.output_tokens * found[1]) / 1e6
        if cost is None and estimate:
            cost, basis = estimate, spending.ESTIMATED
        self._record(provider, model_id, task, started, clock, estimate, reply, None, cost, basis)
        return reply

    def _record(
        self,
        provider: str,
        model_id: str,
        task: AiTask,
        started: datetime,
        clock: float,
        estimate: float | None,
        reply: Any,
        err: AiError | None,
        cost: float | None,
        basis: str | None = spending.MAYBE_CHARGED,
    ) -> None:
        data = {
            "request": None,
            "task": CHECK_TASK,
            "provider": provider,
            "model": (reply.model_served if reply is not None else None) or model_id,
            "tier": CHECK_TIER,
            "input_chars": task.size,
            "output_chars": len(reply.text) if reply is not None else 0,
            "input_tokens": reply.input_tokens if reply is not None else None,
            "output_tokens": reply.output_tokens if reply is not None else None,
            "cached_input_tokens": reply.cached_input_tokens if reply is not None else None,
            "cost_usd": cost,
            "cost_basis": basis,
            "seconds": round(time.monotonic() - clock, 3),
            "outcome": "ok" if reply is not None else "error",
            "error_kind": err.kind if err is not None else None,
            "error_detail": err.detail if err is not None else None,
            "started_at": started.isoformat(),
        }
        spending.settle(self.store, self.hold, data, _SYSTEM, part=estimate or 0.0)


def check_calls(cfg: Config) -> list[tuple[str, int]]:
    """Every "account/model" a whole check calls, with how many small calls it makes there: one per kind of work and
    tier, and the round-trip that tests learning once per account and model."""
    found: dict[str, int] = {}
    for tier_name, tier in cfg.ai.tiers.items():
        for ref in [tier.use, *tier.fallback] if tier.use else []:
            first = ref not in found
            found[ref] = found.get(ref, 0) + len(_params_for_tier(cfg, tier_name))
            if first:
                found[ref] += check_cost.EXTRA_CALLS
    return list(found.items())


def smoke_test(
    cfg: Config,
    env: Mapping[str, str],
    adapter_factory: Callable[[str, Any, str | None], Any] = make_adapter,
    store: Any = None,
) -> list[SmokeResult]:
    """One small call per tier, account and kind of work with its exact parameters, the lockdown check for a
    command-line agent, and the learning round-trip, each account's once. With a `store`, the round-trip's proposal is
    also tried against the app's own checks, and the check's calls count in the person's spending: the whole check is
    admitted against the spending limits before anything is sent (`BudgetReached` when they have no room for it), and
    each call is recorded as a run."""
    counted = _Spending(cfg, store)
    counted.admit(check_calls(cfg))
    try:
        return _smoke_test(cfg, env, adapter_factory, store, counted)
    finally:
        counted.close()


def _smoke_test(
    cfg: Config,
    env: Mapping[str, str],
    adapter_factory: Callable[[str, Any, str | None], Any],
    store: Any,
    counted: _Spending,
) -> list[SmokeResult]:
    results: list[SmokeResult] = []
    locked: set[str] = set()
    refused: dict[str, AiError | None] = {}  # account -> the refusal its model list gave, looked up once each
    listed: dict[str, dict[str, ModelInfo]] = {}  # account -> what its service lists per model, read once each
    for tier_name, tier in cfg.ai.tiers.items():
        if not tier.use:
            results.append(SmokeResult(tier_name, "", True, False, "no AI account is set up for this tier"))
            continue
        for position, ref in enumerate([tier.use, *tier.fallback]):
            provider_name, _, model_key = ref.partition("/")
            settings = cfg.ai.providers[provider_name]
            model_id = settings.models.get(model_key, model_key)
            first_report: dict[str, int] | None = None  # the first call's reported input tokens, for the overhead
            if provider_name not in refused:
                refused[provider_name] = _refused_on_listing(settings, env, adapter_factory)
            refusal = refused[provider_name]
            for kind, temperature, max_output, *effort in _params_for_tier(cfg, tier_name):
                task = AiTask(
                    kind,
                    "This is a connection test.",
                    "",
                    _REQUEST,
                    {},
                    temperature,
                    max_output,
                    effort=tier.effort,
                    thinking=getattr(tier, "thinking", "default"),
                )
                start = time.monotonic()
                key_source = None
                answered = no_network = False
                failed_kind = raw_detail = ""
                try:
                    if refusal is not None:
                        raise refusal
                    secret = resolve_secret(settings.auth, env)
                    adapter = adapter_factory(settings.adapter, settings, secret)
                    if getattr(adapter, "reads_capabilities", False):
                        if provider_name not in listed:
                            listed[provider_name] = adapter.catalog()
                        task = replace(task, model_info=listed[provider_name].get(model_id))
                    reply = counted.call(ref, settings, model_id, task, partial(adapter.run, task, model_id))
                    detail = "answered" if _is_ok(reply.text) else "answered, but not with the requested JSON"
                    if first_report is None and reply.input_tokens is not None:
                        first_report = {"reported": reply.input_tokens, "text": estimate_tokens(task.size)}
                    notes = adapter.capability_notes(task) if hasattr(adapter, "capability_notes") else []
                    if notes:
                        detail += "; " + "; ".join(notes)
                    ok = answered = True
                except SecretError as err:
                    ok, detail, key_source = False, f"key not found: {err}", describe_secret(settings.auth)
                except AiError as err:
                    ok, detail, failed_kind = False, _problem(err, where_of(settings), model_id, tier_name), err.kind
                    raw_detail = err.detail
                    no_network = err.kind == "offline"
                    if err.kind in ("auth", "no_key"):
                        key_source = describe_secret(settings.auth)
                except ValueError as err:
                    ok, detail = False, str(err)
                shown_effort = f", effort {tier.effort}" if tier.effort else ""
                shown_effort += ", thinking off" if getattr(tier, "thinking", "default") == "off" else ""
                label = f"{ref} ({kind}, temperature {temperature}, max output {max_output}{shown_effort})"
                results.append(
                    SmokeResult(
                        tier_name,
                        label,
                        position == 0,
                        ok,
                        detail,
                        time.monotonic() - start,
                        key_source,
                        provider_name,
                        answered,
                        no_network,
                        ref,
                        "call",
                        [kind, temperature, max_output, *effort],
                        error_kind=failed_kind,
                        error_detail=raw_detail,
                    )
                )
            if ref not in locked:
                locked.add(ref)
                results.extend(_lockdown(tier_name, ref, position == 0, settings, model_id, env, adapter_factory))
                results.extend(_identity(tier_name, ref, position == 0, settings, env, adapter_factory))
                # Calibrate only an account that answered: an offline or refused check measures nothing.
                if refusal is None and answered:
                    results.extend(
                        _calibration(
                            tier_name, ref, position == 0, settings, model_id, env, adapter_factory, first_report
                        )
                    )
                if refusal is None:
                    results.append(
                        _learning(
                            tier_name, ref, position == 0, cfg, settings, model_id, env, adapter_factory, store, counted
                        )
                    )
                else:  # no call for work is sent with a key the service refused
                    results.append(
                        SmokeResult(
                            tier_name,
                            f"{ref} (learning round-trip)",
                            position == 0,
                            False,
                            _problem(refusal, where_of(settings)),
                            provider=provider_name,
                            ref=ref,
                            part="learning",
                            error_kind=refusal.kind,
                        )
                    )
    return results


def _refused_on_listing(
    settings: Any, env: Mapping[str, str], adapter_factory: Callable[[str, Any, str | None], Any]
) -> AiError | None:
    """For an account whose service answers a refused key with a status that means any bad request when it is sent
    work (`key_refused_status_on_models`), the model list is asked for first, as the setup screen does: that is where
    the status tells a refused key. Returns the refusal, or None when the key was not refused there, when the list
    failed for any other reason (the call for work then says what is wrong) or when the account has no such setting.
    One request at most."""
    if not getattr(settings, "key_refused_status_on_models", None):
        return None
    try:
        adapter = adapter_factory(settings.adapter, settings, resolve_secret(settings.auth, env))
        if not hasattr(adapter, "list_models"):
            return None
        adapter.list_models()
    except AiError as err:
        return err if err.kind == "auth" else None
    except (SecretError, ValueError):
        return None
    return None


#: What a failed test call means, in plain words, by the kind of failure.
PROBLEMS = {
    "auth": "It isn't signed in, or the key was refused",
    "unsupported": UNSUPPORTED_PLAIN,
    "no_key": "The key wasn't found",
    "quota": "The account is out of credit or at its plan's limit",
    "rate_limited": "The account asked to wait; try again shortly",
    "timeout": "It didn't answer in time",
    "provider_down": "It couldn't be reached",
    "offline": "There is no network connection to reach it",
    "invalid_output": "Its answer couldn't be read",
    "no_output": "It finished without giving an answer",
    "no_work": "It started but did nothing; it may be signed out",
    "refused": "It refused the request",
    "model_retired": "The model is no longer offered by this service",
    "no_allowed_model": "The service's privacy or guardrail settings for this account allow no model to answer",
}
#: Failures whose plain words say it all: the service's own words (often a whole error body, or a program's terminal
#: warnings) are not shown beside them.
PLAIN_ONLY = frozenset({"unsupported", "no_allowed_model", "quota"})
#: What to do about them.
NO_ALLOWED_MODEL_ADVICE = "Change those settings at the service, or pick another model"


def tier_summary(results: list[SmokeResult]) -> tuple[list[str], bool]:
    """What the test means for each kind of work, one line per tier whose main account failed, and whether every tier
    can run: a tier whose main account failed still runs when a backup passed every part of its check."""
    lines, every = [], True
    for tier in dict.fromkeys(r.tier for r in results):
        mine = [r for r in results if r.tier == tier]
        if all(r.ok for r in mine if r.main):
            continue
        backups: dict[str, bool] = {}
        for r in mine:
            if not r.main:
                ref = r.ref or r.account.split(" ", 1)[0]
                backups[ref] = backups.get(ref, True) and r.ok
        standing = next((ref for ref, ok in backups.items() if ok), None)
        if standing is not None:
            lines.append(f"{tier}: the main account didn't answer; {standing} stands in until it does.")
        else:
            every = False
            lines.append(f"{tier} can't run: no account for it answered. See the lines above, then test again.")
    return (lines or ["All tiers answered."]), every


#: Failures of the connection itself: their detail is this computer's own error text, not the account's words, so it is
#: never shown; the line says what to do instead.
TRANSPORT_KINDS = frozenset({"provider_down", "offline", "timeout"})

#: What to do about a connection failure, by where the account lives: a service on this computer or the local network,
#: a hosted service (its address is the app's own, so there is nothing to check but the internet), or a program the app
#: starts. `local` is the wording used when nothing is known about the account.
TRANSPORT_HINTS = {
    "local": {
        "provider_down": "Check the address, or start it if it runs on this computer",
        "offline": "Check this computer's network connection",
    },
    "hosted": {
        "provider_down": "Check your internet connection, and try again in a few minutes if it keeps failing",
        "offline": "Check your internet connection",
    },
    "program": {
        "provider_down": "Check this computer's network connection",
        "offline": "Check this computer's network connection",
    },
}


def where_of(settings: Any) -> str:
    """Where an account lives, from its settings alone: "program" (no address: a command-line agent), "local" (an
    address on this computer or its own network) or "hosted" (any other address)."""
    address = getattr(settings, "base_url", None)
    if not address:
        return "program"
    host = (urlsplit(address).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return "local"
    try:
        found = ipaddress.ip_address(host)
    except ValueError:
        return "hosted"
    return "local" if found.is_loopback or found.is_private or found.is_link_local else "hosted"


def _problem(err: AiError, where: str = "local", model: str = "", tier: str = "") -> str:
    """A failed test call in plain words: what it means, the account's own words for it, and what to do. `where` is
    where the account lives (`where_of`), so a hosted service never gets the advice for a local one."""
    if err.kind == "model_retired":
        return f"{RETIRED_PLAIN.format(work=work_in_words(tier))}."
    reason = "" if err.kind in TRANSPORT_KINDS or err.kind in PLAIN_ONLY else provider_reason(err.detail)
    if model and reason:
        # The service's own words may name the model, which the person is never shown.
        reason = reason.replace(model, "the model")
    plain = PROBLEMS.get(err.kind, "It stopped with an error")
    detail = f"{plain} ({reason})" if reason else plain
    hint = err.hint or (
        UNSUPPORTED_ADVICE
        if err.kind == "unsupported"
        else NO_ALLOWED_MODEL_ADVICE
        if err.kind == "no_allowed_model"
        else TRANSPORT_HINTS.get(where, TRANSPORT_HINTS["local"]).get(err.kind)
    )
    return f"{detail}. {hint.rstrip('.')}." if hint else f"{detail}."


def _lockdown(
    tier: str,
    ref: str,
    main: bool,
    settings: Any,
    model_id: str,
    env: Mapping[str, str],
    adapter_factory: Callable[[str, Any, str | None], Any],
) -> list[SmokeResult]:
    """For an agent account, its lockdown test: one result per probe (design 6.16). Other accounts have none."""
    try:
        adapter = adapter_factory(settings.adapter, settings, resolve_secret(settings.auth, env))
    except (SecretError, AiError, ValueError):
        return []  # the connection test above already says why
    if not hasattr(adapter, "lockdown_test"):
        return []
    start = time.monotonic()
    checks = adapter.lockdown_test(model_id)
    seconds = time.monotonic() - start
    return [
        SmokeResult(
            tier,
            f"{ref} (lockdown: {c.name})",
            main,
            c.ok,
            c.detail,
            seconds,
            provider=ref.partition("/")[0],
            ref=ref,
            part="lockdown",
        )
        for c in checks
    ]


def _identity(
    tier: str,
    ref: str,
    main: bool,
    settings: Any,
    env: Mapping[str, str],
    adapter_factory: Callable[[str, Any, str | None], Any],
) -> list[SmokeResult]:
    """For an agent account, which sign-in it runs as, read from the program (design 6.16). Not being able to tell is
    said as it is and is no failure of the account's check; an account that isn't an agent has no result."""
    try:
        adapter = adapter_factory(settings.adapter, settings, resolve_secret(settings.auth, env))
    except (SecretError, AiError, ValueError):
        return []  # the connection test above already says why
    reader = getattr(adapter, "identity", None)
    start = time.monotonic()
    found = reader() if callable(reader) else None
    if found is None:
        return []
    if isinstance(found, IdentityUnknown):
        detail, said = f"can't tell which sign-in it uses: {found.reason}", {"unknown": found.reason}
    else:
        detail, said = f"runs as {found.account}", {"account": found.account, "how_read": found.how_read}
    return [
        SmokeResult(
            tier,
            f"{ref} (identity)",
            main,
            True,
            detail,
            time.monotonic() - start,
            provider=ref.partition("/")[0],
            ref=ref,
            part="identity",
            identity=said,
        )
    ]


def _calibration(
    tier: str,
    ref: str,
    main: bool,
    settings: Any,
    model_id: str,
    env: Mapping[str, str],
    adapter_factory: Callable[[str, Any, str | None], Any],
    first_report: dict[str, int] | None,
) -> list[SmokeResult]:
    """How this account counts, for the estimates (design 6.16): where the adapter can count a request without running
    it, one count of a fixed sample gives the ratio of real tokens to the app's own count; where the adapter adds its
    own text to every request, the check's first call gives the fixed overhead. Nothing here is a failure of the
    account: an adapter that can't count, or a count that fails, leaves the ratio at 1, and says so."""
    try:
        adapter = adapter_factory(settings.adapter, settings, resolve_secret(settings.auth, env))
    except (SecretError, AiError, ValueError):
        return []  # the connection test above already says why
    start = time.monotonic()
    measured: dict[str, Any] = {"model": model_id}
    said: list[str] = []
    counter = getattr(adapter, "count_tokens", None)
    if callable(counter):
        sample = AiTask("calibration", SAMPLE_INSTRUCTIONS, "", SAMPLE_REQUEST, {})
        try:
            measured["counted"] = int(counter(sample, model_id))
            measured["sample_chars"] = sample.size
            said.append("counted a sample")
        except CountNotOffered:
            said.append("the service's count isn't offered, so the app's own count is used")
        except AiError as err:
            said.append(f"the count request failed ({err.kind}), so the app's own count is used")
    else:
        said.append("this account doesn't count a request without running it")
    if getattr(adapter, "adds_overhead", False):
        if first_report is None:
            said.append("the program didn't report how much it read, so no fixed overhead is known")
        else:
            measured.update(reported=first_report["reported"], text_tokens=first_report["text"])
            said.append("measured the program's fixed overhead")
    return [
        SmokeResult(
            tier,
            f"{ref} (estimates)",
            main,
            True,
            "; ".join(said),
            time.monotonic() - start,
            provider=ref.partition("/")[0],
            ref=ref,
            part="calibration",
            calibration=measured,
        )
    ]


def _learning(
    tier: str,
    ref: str,
    main: bool,
    cfg: Config,
    settings: Any,
    model_id: str,
    env: Mapping[str, str],
    adapter_factory: Callable[[str, Any, str | None], Any],
    store: Any,
    counted: _Spending | None = None,
) -> SmokeResult:
    """The learning round-trip for one account: one call with a tiny fixed correction, expecting one proposal back that
    the app accepts. The account's own call failing is said as it is; an answer that doesn't pass says which part."""
    provider = ref.partition("/")[0]
    label = f"{ref} (learning round-trip)"
    start = time.monotonic()
    answered = no_network = False
    failed_kind = raw_detail = ""
    try:
        adapter = adapter_factory(settings.adapter, settings, resolve_secret(settings.auth, env))
        task = learning_check.task(cfg)
        counted = counted or _Spending(cfg, None)
        reply = counted.call(ref, settings, model_id, task, lambda: adapter.run(task, model_id), check_cost.EXTRA_CALLS)
        answered = True
        why = learning_check.problem(reply.text, cfg, store)
        ok, detail = why is None, learning_check.PASSED if why is None else why
    except SecretError as err:
        ok, detail = False, f"key not found: {err}"
    except AiError as err:
        ok, detail, failed_kind = False, _problem(err, where_of(settings)), err.kind
        raw_detail = err.detail
        no_network = err.kind == "offline"
    except ValueError as err:
        ok, detail = False, str(err)
    return SmokeResult(
        tier,
        label,
        main,
        ok,
        detail,
        time.monotonic() - start,
        provider=provider,
        answered=answered,
        offline=no_network,
        ref=ref,
        part="learning",
        error_kind=failed_kind,
        error_detail=raw_detail,
    )


def _is_ok(text: str) -> bool:
    try:
        return json.loads(text.strip().strip("`").removeprefix("json").strip()) == {"ok": True}
    except ValueError:
        return False


def ai_fingerprint(ws: Workspace, cfg: Config | None = None) -> str:
    """What the connection test depends on, as it is set up now: for each tier that has an account, the account in use
    and its backups (each one's address, key reference, model and agent), how the tier asks (effort, thinking) and the
    parameters of its kinds of work. Labels, budgets, accounts nothing uses and who may see what are not part of it:
    changing them changes nothing the test answered, so it is not asked again for them."""
    from engine.ai.checked import account_fingerprint

    cfg = cfg or load_config(ws.config_dir, env={})
    parts = []
    for name in sorted(cfg.ai.tiers):
        tier = cfg.ai.tiers[name]
        if not tier.use:
            continue
        parts.append(
            [
                name,
                [[ref, account_fingerprint(cfg, ref)] for ref in [tier.use, *tier.fallback]],
                tier.effort,
                getattr(tier, "thinking", "default"),
                [list(p) for p in _params_for_tier(cfg, name)],
            ]
        )
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def inconclusive(results: list[SmokeResult]) -> bool:
    """Whether the test found no network and nothing else wrong: every failure is a missing connection. Such a test
    says nothing about the accounts, so it is neither kept as a failure nor counted toward one."""
    failed = [r for r in results if not r.ok]
    return bool(failed) and all(r.offline for r in failed)


def record(ws: Workspace, results: list[SmokeResult], cfg: Config | None = None) -> None:
    """Keep a test's result, with what it was a test of (`cfg`, else the settings on disk). A test that only found no
    network is not kept: the last real result stands."""
    if inconclusive(results):
        return
    passed = tier_summary(results)[1]
    data = {
        "fingerprint": ai_fingerprint(ws, cfg),
        "passed": passed,
        "at": datetime.now(UTC).isoformat(),
        "results": [asdict(r) for r in results],
    }
    write_whole(ws.private_dir / STATUS_FILE, json.dumps(data, indent=2) + "\n")


def lift_pauses(ws: Workspace, results: list[SmokeResult]) -> None:
    """An account whose test call was answered is not out of its usage limit any more: its pause is lifted."""
    from engine.ai.pauses import Pauses

    pauses = Pauses(ws.private_dir / "ai-pauses.json")
    for account in {r.provider for r in results if r.answered and r.provider}:
        pauses.clear(account)


def untested_since_change(ws: Workspace, cfg: Config | None = None) -> bool:
    """True when what the assistant's work runs on has no passing test: the last whole test passed for the accounts and
    tiers as they are now, or else every account in use (each tier's main) passed its own check as it is set up now, as
    a Test on its own row in Settings makes it. A change that touches neither (a backup account added or taken away, a
    label, a budget) leaves it tested."""
    cfg = cfg or load_config(ws.config_dir, env={})
    data = last_test(ws)
    if data is not None and can_run(data) and data.get("fingerprint") == ai_fingerprint(ws, cfg):
        return False
    return not _mains_answered(ws, cfg)


def _mains_answered(ws: Workspace, cfg: Config, since: str | None = None) -> bool:
    """Whether every account a tier uses passed its latest check as set up now (at or after `since`), and some does."""
    from engine.ai.checked import answered

    uses = [tier.use for tier in cfg.ai.tiers.values() if tier.use]
    return bool(uses) and all(answered(ws, cfg, ref, since) for ref in uses)


def can_run(test: dict[str, Any]) -> bool:
    """Whether a recorded test left every tier able to run: its main account answered, or a backup passed every part
    of its check and stands in. Read from the results, so a test kept before backups counted reads the same way."""
    results = test.get("results")
    if not isinstance(results, list) or not results:
        return bool(test.get("passed"))
    names = {f.name for f in fields(SmokeResult)}
    try:
        parsed = [SmokeResult(**{k: v for k, v in r.items() if k in names}) for r in results]
    except (TypeError, AttributeError):
        return bool(test.get("passed"))
    return tier_summary(parsed)[1]


def last_test(ws: Workspace) -> dict[str, Any] | None:
    """The last recorded smoke test, or None when there never was one or the file can't be read."""
    path = ws.private_dir / STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


DETAIL_LIMIT = 200


def ai_state(ws: Workspace, cfg: Config, store: Store) -> tuple[str, str | None]:
    """Whether the assistant can do its work: "not_set_up" (no account for any tier), "failing" (the last connection
    test failed for the current settings, or the latest request ended with the account refusing its key),
    "stand_in" (every tier uses the built-in stand-in, which only files notes), "untested" (settings changed since the
    last passing test), or "ok". The detail is the provider's own reason."""
    if not any(tier.use for tier in cfg.ai.tiers.values()):
        return "not_set_up", None
    if stand_in(cfg):
        return "stand_in", None
    test = last_test(ws)
    current = test is not None and test.get("fingerprint") == ai_fingerprint(ws, cfg)
    # A test of the account on its own that passed after the failing whole test clears the failure.
    mended = test is not None and _mains_answered(ws, cfg, since=str(test.get("at", "")))
    if test is not None and current and not can_run(test) and not mended:
        failed = [r for r in test.get("results", []) if not r.get("ok") and not r.get("offline")]
        pick = next((r for r in failed if r.get("main")), failed[0] if failed else None)
        if failed or not test.get("results"):
            return "failing", (str(pick.get("detail", ""))[:DETAIL_LIMIT] or None) if pick else None
    # A call that found no network or did no work says nothing about the account: it never hides or makes a failure.
    # A check's own calls are runs too, and say nothing here: the kept test results speak for a check.
    runs = sorted(
        (
            run
            for run in store.read().list("run")
            if run.data.get("error_kind") not in NO_WORK_KINDS and run.data.get("task") != CHECK_TASK
        ),
        key=lambda run: run.data.get("started_at", ""),
    )
    if runs and runs[-1].data.get("outcome") == "error" and runs[-1].data.get("error_kind") in ("auth", "unsupported"):
        latest = runs[-1].data
        passed_since = bool(test and can_run(test) and current and str(test.get("at", "")) >= latest["started_at"])
        if not passed_since:
            return "failing", (provider_reason(latest.get("error_detail") or "")[:DETAIL_LIMIT] or None)
    if untested_since_change(ws, cfg):
        return "untested", None
    return "ok", None


def stand_in(cfg: Config) -> bool:
    """True when every account the tiers use is the built-in stand-in, which only files notes."""
    return all(cfg.ai.providers[ref.partition("/")[0]].adapter == "stub" for ref in _accounts_in_use(cfg))


def _accounts_in_use(cfg: Config) -> list[str]:
    """Every provider/model a tier uses or falls back to."""
    return [ref for tier in cfg.ai.tiers.values() for ref in ([tier.use] if tier.use else []) + list(tier.fallback)]


def account_test(
    cfg: Config,
    env: Mapping[str, str],
    name: str,
    adapter_factory: Callable[[str, Any, str | None], Any] = make_adapter,
    *,
    tier: str | None = None,
    model: str | None = None,
    store: Any = None,
) -> list[SmokeResult]:
    """Test one account, whether or not any kind of work uses it yet: one small call (and the lockdown check for a
    command-line agent, and the learning round-trip), reported under the tier name "account". The model is the one
    named, else the account's first. With a `tier`, the call uses that tier's kinds of work and their exact parameters,
    which is what makes the result count for a place in that tier's fallback chain."""
    from dataclasses import replace

    from engine.config.schema import TierSettings

    provider = cfg.ai.providers.get(name)
    if provider is None or not provider.models:
        return [SmokeResult("account", name, True, False, "this account has no model to test")]
    chosen = model if model in provider.models else next(iter(provider.models))
    named = tier if tier is not None and tier in cfg.ai.tiers else "account"
    ai = cfg.ai.model_copy(update={"tiers": {named: TierSettings(use=f"{name}/{chosen}")}})
    found = smoke_test(replace(cfg, files={**cfg.files, "ai": ai}), env, adapter_factory, store)
    return [replace(r, tier="account") for r in found]
