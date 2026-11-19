"""What a provider actually charged, read as a report per UTC day and set beside the app's own figure (design 6.16,
"What a provider actually charged").

An account whose adapter offers `cost_report`, that has a billing key and a `cost_report_hours` above zero, is asked for
the last `ai.cost_report_days` days every that many hours, in the scheduled-jobs pass, never inside a send. Each day is
kept in the workspace's private folder beside the calibration (overwritten by each read, dropped after the configured
days). Nothing here limits or prices a run: limits and estimates keep the app's own figure.

- `compare` sets each kept day beside the app's own total for the same UTC day (and its split per kind of work);
- `gap` finds the days whose real cost is above the app's by more than both configured margins, on settled days narrowed
  to the account's own key; Today has one line for them, and Not now is remembered for exactly those days;
- three reads in a row that fail are a Today line that says why and what to do.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from engine.ai.adapters import ADAPTERS, make_adapter
from engine.ai.task import NO_WORK_KINDS, AiError
from engine.config import Config
from engine.legacy_names import private_dir
from engine.secrets import SecretError, resolve_secret
from engine.state_file import changing, write_whole

STATE_FILE = "ai-cost-report.json"
#: How many reads in a row must fail before Today says so.
FAILURES_BEFORE_LINE = 3

#: What to tell the person for each kind of failed read, and what to do about it. The service's words are never read.
PROBLEMS: dict[str, str] = {
    "auth": "The service didn't accept the billing key. Add it again, or set the hours to 0 to stop asking.",
    "no_key": "The billing key can't be found. Add it again, or set the hours to 0 to stop asking.",
    "quota": "The service wouldn't give the report for the account's billing. Check the account there.",
    "rate_limited": "The service asked to slow down, and kept asking. It is tried again at the next time.",
    "provider_down": "The service didn't answer. It is tried again at the next time.",
    "timeout": "The service took too long to answer. It is tried again at the next time.",
    "offline": "This computer couldn't reach the service. It is tried again at the next time.",
    "invalid_output": "The service's report came back in a form this app doesn't read. Tell the maintainers.",
    "other": "The report can't be read for this account.",
}


def path_of(store: Any) -> Path:
    return private_dir(store.path.parent) / STATE_FILE


def read(store: Any) -> dict[str, Any]:
    """The kept state: `accounts` (name -> `days`, `read_at`, `partial`, `tried_at`, `failures`, `failed`) and `not_now`
    (name -> the signature of the days put off)."""
    try:
        data = json.loads(path_of(store).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {
        "accounts": data.get("accounts") if isinstance(data.get("accounts"), dict) else {},
        "not_now": data.get("not_now") if isinstance(data.get("not_now"), dict) else {},
    }


def _write(store: Any, data: dict[str, Any]) -> None:
    write_whole(path_of(store), json.dumps(data, sort_keys=True, indent=2) + "\n")


def offers_report(cfg: Config, account: str) -> bool:
    """Whether this account's adapter has a cost report (a capability of the adapter, never a guess from its address)"""
    provider = cfg.ai.providers.get(account)
    return provider is not None and hasattr(ADAPTERS.get(provider.adapter), "cost_report")


def is_on(cfg: Config, account: str) -> bool:
    """Whether the account is read: its adapter offers a report, it has the billing key and the hours are set."""
    provider = cfg.ai.providers.get(account)
    return (
        provider is not None
        and offers_report(cfg, account)
        and bool(provider.billing_auth)
        and provider.cost_report_hours > 0
    )


def _at(text: str) -> datetime:
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def due(store: Any, cfg: Config, now: datetime) -> list[str]:
    """The accounts to read now: on, and last tried at least `cost_report_hours` ago."""
    accounts = read(store)["accounts"]
    found = []
    for name in cfg.ai.providers:
        if not is_on(cfg, name):
            continue
        tried = (accounts.get(name) or {}).get("tried_at")
        if tried is None or now - _at(tried) >= timedelta(hours=cfg.ai.providers[name].cost_report_hours):
            found.append(name)
    return found


def problem_text(kind: str) -> str:
    return PROBLEMS.get(kind, PROBLEMS["other"])


def check(
    settings: Any,
    billing_secret: str | None,
    secret: str | None = None,
    *,
    now: datetime | None = None,
    factory: Callable[..., Any] | None = None,
) -> str | None:
    """One small report read with this billing key, for when it is added: None when it worked, else the problem in plain
    words. Nothing is kept."""
    now = now or datetime.now(UTC)
    factory = factory or make_adapter
    try:
        adapter = factory(settings.adapter, settings, secret, billing_secret)
        if not hasattr(adapter, "cost_report"):
            return "This kind of account has no report to read."
        today = now.astimezone(UTC).date()
        adapter.cost_report(today - timedelta(days=1), today, pages=1, now=now)
    except AiError as err:
        return problem_text(err.kind)
    return None


def run(
    ws: Any,
    store: Any,
    cfg: Config,
    env: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
    factory: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Read every account that is due, once each. Returns the accounts read. A failed read is counted and kept with its
    kind; one account failing never stops the others."""
    env = os.environ if env is None else env
    now = now or datetime.now(UTC)
    factory = factory or make_adapter
    read_accounts: list[str] = []
    for name in due(store, cfg, now):
        provider = cfg.ai.providers[name]
        try:
            billing = resolve_secret(provider.billing_auth, env)
            try:
                secret = resolve_secret(provider.auth, env)
            except SecretError:
                secret = None  # the report doesn't use the key that runs models
            adapter = factory(provider.adapter, provider, secret, billing)
            today = now.astimezone(UTC).date()
            readout = adapter.cost_report(
                today - timedelta(days=cfg.ai.cost_report_days - 1),
                today,
                pages=cfg.ai.cost_report_pages,
                sleep=sleep,
                now=now,
            )
        except SecretError:
            _failed(store, name, now, "no_key", None)
            continue
        except AiError as err:
            _failed(store, name, now, err.kind, err.retry_after)
            continue
        _keep(store, cfg, name, now, readout)
        read_accounts.append(name)
    return read_accounts


def _keep(store: Any, cfg: Config, account: str, now: datetime, readout: Any) -> None:
    oldest = now.astimezone(UTC).date() - timedelta(days=cfg.ai.cost_report_days - 1)
    with changing(path_of(store)):
        data = read(store)
        row = data["accounts"].get(account) or {}
        days = {k: v for k, v in (row.get("days") or {}).items() if date.fromisoformat(v["day"]) >= oldest}
        for found in readout.days:
            if found.day < oldest:
                continue
            days[f"{found.day.isoformat()}/{found.currency}"] = {
                "day": found.day.isoformat(),
                "amount": str(found.amount),
                "currency": found.currency,
                "scope": found.scope,
                "read_at": found.read_at.isoformat(),
                "open": found.open,
            }
        data["accounts"][account] = {
            "days": days,
            "read_at": now.isoformat(),
            "tried_at": now.isoformat(),
            "partial": bool(readout.partial),
            "failures": 0,
            "failed": None,
        }
        _write(store, data)


def _failed(store: Any, account: str, now: datetime, kind: str, wait: float | None) -> None:
    with changing(path_of(store)):
        data = read(store)
        row = dict(data["accounts"].get(account) or {})
        # A throttle's asked-for wait moves the next try; any other failure is tried again at the account's own hours.
        tried = now if not wait else now + timedelta(seconds=wait)
        row.update(
            tried_at=tried.isoformat(),
            failures=int(row.get("failures") or 0) + 1,
            failed={"kind": kind if kind in PROBLEMS else "other", "at": now.isoformat()},
        )
        data["accounts"][account] = row
        _write(store, data)


def forget(store: Any, account: str) -> None:
    """Drop what is kept for an account (it was removed, or its report turned off for good)."""
    with changing(path_of(store)):
        data = read(store)
        data["accounts"].pop(account, None)
        data["not_now"].pop(account, None)
        _write(store, data)


# ---- the app's own figure and the comparison -------------------------------------------------------------------------


def app_figures(store: Any, account: str, oldest: date) -> dict[date, dict[str, float]]:
    """What the app worked out for the account's runs per UTC day since `oldest`, split by kind of work: day -> task ->
    US dollars (a run with no cost counts nothing)."""
    out: dict[date, dict[str, float]] = {}
    for stored in store.read().since("run", "started_at", oldest.isoformat()):
        run = stored.data
        if run.get("provider") != account or run.get("error_kind") in NO_WORK_KINDS or run.get("no_work"):
            continue
        day = _at(run["started_at"]).astimezone(UTC).date()
        if day < oldest:
            continue
        task = str(run.get("task") or "")
        by_task = out.setdefault(day, {})
        by_task[task] = by_task.get(task, 0.0) + float(run.get("cost_usd") or 0.0)
    return out


@dataclass(frozen=True)
class DayRow:
    """One UTC day of an account: the provider's figure (None when not reported yet, never 0) beside the app's."""

    day: date
    reported: bool
    amount: Decimal | None
    currency: str | None
    scope: str | None
    read_at: datetime | None
    open: bool
    app_usd: float
    by_task: dict[str, float] = field(default_factory=dict)
    gap: bool = False


def compare(store: Any, cfg: Config, account: str, now: datetime) -> list[DayRow]:
    """Every UTC day of the kept window, newest first, with the provider's figure beside the app's own total. A day the
    provider hasn't reported shows no figure (`reported` false). A report in another currency is shown but never
    compared. `gap` marks the days that Today's line counts."""
    kept = (read(store)["accounts"].get(account) or {}).get("days") or {}
    today = now.astimezone(UTC).date()
    oldest = today - timedelta(days=cfg.ai.cost_report_days - 1)
    app = app_figures(store, account, oldest)
    reported: dict[date, dict[str, Any]] = {}
    for item in kept.values():
        day = date.fromisoformat(item["day"])
        if day >= oldest:
            reported.setdefault(day, item)
    rows = []
    for day in sorted(set(app) | set(reported), reverse=True):
        item = reported.get(day)
        total = round(sum(app.get(day, {}).values()), 6)
        amount = Decimal(item["amount"]) if item else None
        rows.append(
            DayRow(
                day=day,
                reported=item is not None,
                amount=amount,
                currency=item["currency"] if item else None,
                scope=item["scope"] if item else None,
                read_at=_at(item["read_at"]) if item else None,
                open=bool(item["open"]) if item else day >= today,
                app_usd=total,
                by_task=dict(app.get(day, {})),
                gap=bool(item) and _is_gap(cfg, item, total, day, today),
            )
        )
    return rows


def _is_gap(cfg: Config, item: Mapping[str, Any], app_usd: float, day: date, today: date) -> bool:
    """A settled day (over, and older than `cost_gap_settle_days`), narrowed to the account's key, in US dollars, whose
    real cost is above the app's by more than both margins."""
    if item["scope"] != "key" or item["currency"] != "USD" or day >= today:
        return False
    if (today - day).days <= cfg.ai.cost_gap_settle_days:
        return False
    real = float(Decimal(item["amount"]))
    over = real - app_usd
    return over > cfg.ai.cost_gap_usd and over > app_usd * cfg.ai.cost_gap_percent / 100


@dataclass(frozen=True)
class Gap:
    """The days of one account whose real cost is above the app's, for one Today line."""

    account: str
    days: list[date]
    provider_usd: float
    app_usd: float

    @property
    def signature(self) -> str:
        return ",".join(d.isoformat() for d in sorted(self.days))


def gaps(store: Any, cfg: Config, now: datetime) -> list[Gap]:
    """One `Gap` per account that has any, left out where the person said Not now about exactly these days."""
    put_off = read(store)["not_now"]
    found = []
    for account in sorted(cfg.ai.providers):
        if not is_on(cfg, account):
            continue
        rows = [r for r in compare(store, cfg, account, now) if r.gap]
        if not rows:
            continue
        gap = Gap(
            account=account,
            days=[r.day for r in rows],
            provider_usd=round(sum(float(r.amount or 0) for r in rows), 2),
            app_usd=round(sum(r.app_usd for r in rows), 2),
        )
        if put_off.get(account) != gap.signature:
            found.append(gap)
    return found


def not_now(store: Any, cfg: Config, account: str, now: datetime) -> bool:
    """Put off the line for exactly the days it counts now; a new day in the gap brings it back."""
    live = next((g for g in gaps(store, cfg, now) if g.account == account), None)
    if live is None:
        return False
    with changing(path_of(store)):
        data = read(store)
        data["not_now"][account] = live.signature
        _write(store, data)
    return True


@dataclass(frozen=True)
class Failing:
    account: str
    kind: str
    since: datetime


def failing(store: Any, cfg: Config) -> list[Failing]:
    """The accounts whose last `FAILURES_BEFORE_LINE` reads in a row failed, while the report is still on."""
    found = []
    for name, row in sorted(read(store)["accounts"].items()):
        failed = row.get("failed") if isinstance(row, dict) else None
        if is_on(cfg, name) and int(row.get("failures") or 0) >= FAILURES_BEFORE_LINE and isinstance(failed, dict):
            found.append(Failing(name, str(failed.get("kind") or "other"), _at(failed["at"])))
    return found
