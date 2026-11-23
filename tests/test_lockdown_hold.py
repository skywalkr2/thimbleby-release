"""An AI program that fails its lock-down check is held, main or backup (design 6.16): its waiting work stays queued
with nothing counted, Today says why and what to do in one line, and it goes on by itself once a check passes. Built on
the silent-stops tests' workspace, worker and scripted provider."""

from __future__ import annotations

from engine.ai.adapters.stub import set_responder
from engine.ai.pauses import NO_RESET, Pauses, held_unsafe, pauses_path, unsafe_reason
from engine.ai.router import Router
from engine.ai.smoke import SmokeResult, lift_pauses
from engine.legacy_names import private_dir
from engine.today_queue import queue
from engine.worker import release_account, release_paused
from tests.test_silent_stops import (  # noqa: F401  (the fixtures and helpers)
    ANSWER,
    TASK,
    Scripted,
    account_of,
    adapters_by_account,
    data,
    env,
    hand,
    worker_of,
)

WHY = "It was able to run commands on this computer, which it must not be allowed to do"


def failed_check(cfg, ok: bool = False) -> list[SmokeResult]:
    account = account_of(cfg)
    ref = f"{account}/default"
    return [
        SmokeResult("routine", f"{ref} (call)", True, True, "answered", provider=account, ref=ref, answered=True),
        SmokeResult(
            "routine",
            f"{ref} (lockdown: shell)",
            True,
            ok,
            WHY if not ok else "stopped",
            provider=account,
            ref=ref,
            part="lockdown",
        ),
    ]


def test_a_failed_lockdown_check_holds_the_account_even_though_its_call_answered(env):  # noqa: F811
    ws, cfg, store, clock = env
    lift_pauses(ws, failed_check(cfg))
    account = account_of(cfg)
    assert Pauses(pauses_path(store), clock).until(account) == NO_RESET
    assert unsafe_reason(private_dir(store.path.parent), account) == WHY


def test_the_main_account_with_a_failed_check_runs_nothing_and_the_work_stays_queued_uncounted(env):  # noqa: F811
    ws, cfg, store, clock = env
    provider = Scripted(ANSWER)
    set_responder(provider)
    lift_pauses(ws, failed_check(cfg))
    request = hand(env)
    worker_of(env).run_pending()
    waiting = data(env, request)
    assert provider.calls == 0, "a held account is never called"
    assert waiting["state"] == "queued" and waiting["retries"] == 0 and waiting["cause"]["kind"] == "paused"
    assert "can't be used safely yet" in waiting["waiting"] and WHY in waiting["waiting"]


def test_today_shows_one_line_with_the_reason_and_the_way_out(env):  # noqa: F811
    ws, cfg, store, clock = env
    set_responder(Scripted(ANSWER))
    lift_pauses(ws, failed_check(cfg))
    hand(env)
    hand(env, "Another input about the covers.")
    worker_of(env).run_pending()
    [line] = [x for x in queue(ws, store, cfg, clock()) if x.kind == "paused"]
    assert line.count == 2 and line.account == account_of(cfg)
    assert WHY in line.waiting and "check it again" in line.waiting


def test_changing_the_accounts_never_lets_a_held_account_go(env):  # noqa: F811
    ws, cfg, store, clock = env
    lift_pauses(ws, failed_check(cfg))
    release_paused(store)
    assert Pauses(pauses_path(store), clock).until(account_of(cfg)) == NO_RESET


def test_a_passing_check_lets_the_work_run_with_nothing_lost_and_no_attempts_counted(env):  # noqa: F811
    ws, cfg, store, clock = env
    provider = Scripted(ANSWER)
    set_responder(provider)
    lift_pauses(ws, failed_check(cfg))
    request = hand(env)
    worker = worker_of(env)
    worker.run_pending()
    assert data(env, request)["state"] == "queued"
    clock.move(hours=5)
    assert worker.run_pending() == 0 and provider.calls == 0, "time alone never lets a held account go"
    freed = lift_pauses(ws, failed_check(cfg, ok=True))
    assert freed == {account_of(cfg)} and held_unsafe(private_dir(store.path.parent)) == {}
    assert release_account(store, freed) == 1
    assert worker.run_pending() == 1 and provider.calls == 1
    done = data(env, request)
    assert done["state"] == "review" and done["retries"] == 0 and done["cause"] is None


def test_a_backup_with_a_failed_check_is_held_too_and_the_main_keeps_working(env):  # noqa: F811
    ws, cfg, store, clock = env
    main = account_of(cfg)
    backup = "backup-agent"
    lift_pauses(ws, failed_check(cfg, ok=True))
    lift_pauses(
        ws,
        [
            SmokeResult(
                "routine",
                f"{backup}/x (lockdown: shell)",
                False,
                False,
                WHY,
                provider=backup,
                ref=f"{backup}/x",
                part="lockdown",
            )
        ],
    )
    assert held_unsafe(private_dir(store.path.parent)) == {backup: WHY}
    assert Pauses(pauses_path(store), clock).until(backup) == NO_RESET
    answered = Scripted(ANSWER)
    Router(cfg, store, env={}, now=clock, adapter_factory=adapters_by_account(cfg, {main: answered})).call(
        TASK, request_id="REQ-1"
    )
    assert answered.calls == 1
