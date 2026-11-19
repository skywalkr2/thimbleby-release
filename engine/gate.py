"""One gate per sign-in, account and service host: every request the core's web client makes to an account's service
passes it, whichever part of the app asks and whichever thread it runs on. The gate paces requests (a minimum gap
between them) and, once the service asks to wait, holds every request until the time it gave, sending nothing. Each
wait halves the pace (to a floor); quiet time raises it again, slowly, to the pace the add-on declared.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from engine.connectors import ConnectorError

#: The most refusals and waits a gate keeps for the reading check to show.
_KEPT = 100


def reason_code(err: ConnectorError) -> str:
    """A refusing answer's reason as a code, never the service's own words: the error's kind and, when the add-on gave
    one, its short reason code."""
    return f"{err.kind}:{err.reason}" if err.reason else err.kind


@dataclass(frozen=True)
class Refusal:
    """One refusing answer the gate saw: its status and reason code, the wait the service asked for, and when."""

    status: int | None
    reason: str
    wait_seconds: float | None
    at: float
    until: float | None


@dataclass
class Counts:
    """What a gate has done: requests it let through (every one went out, whatever the answer), requests it stopped
    before sending (a held gate, or a turn too far off), the seconds it made requests wait for their turn, and the
    refusals and waits the service gave."""

    sent: int = 0
    held: int = 0
    paced_seconds: float = 0.0
    refusals: list[Refusal] = field(default_factory=list)


@dataclass(frozen=True)
class GateSettings:
    """The numbers a gate runs on (the `watch.gate_*` settings)."""

    default_per_second: float = 2.0
    floor_per_second: float = 0.1
    wait_seconds: float = 5.0
    throttle_seconds: float = 60.0
    recover_seconds: float = 300.0
    recover_factor: float = 1.5

    @classmethod
    def from_watch(cls, watch: object) -> GateSettings:
        return cls(
            default_per_second=float(watch.gate_default_per_second),  # type: ignore[attr-defined]
            floor_per_second=float(watch.gate_floor_per_second),  # type: ignore[attr-defined]
            wait_seconds=float(watch.gate_wait_seconds),  # type: ignore[attr-defined]
            throttle_seconds=float(watch.gate_throttle_seconds),  # type: ignore[attr-defined]
            recover_seconds=float(watch.gate_recover_minutes) * 60,  # type: ignore[attr-defined]
            recover_factor=float(watch.gate_recover_factor),  # type: ignore[attr-defined]
        )


class Gate:
    """The allowance for one (sign-in, account, host). Thread-safe; the clock and the sleep are injected for tests."""

    def __init__(
        self,
        settings: GateSettings,
        declared_per_second: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self.declared = max(declared_per_second or settings.default_per_second, settings.floor_per_second)
        self.rate = self.declared
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._closed_until = 0.0
        self._changed_at = clock()
        self.counts = Counts()
        self.wall: Callable[[], float] = time.time

    def _recover(self, now: float) -> None:
        if self.rate >= self.declared or self.settings.recover_seconds <= 0:
            return
        periods = int((now - self._changed_at) // self.settings.recover_seconds)
        if periods > 0:
            self.rate = min(self.declared, self.rate * self.settings.recover_factor**periods)
            self._changed_at += periods * self.settings.recover_seconds

    def acquire(self) -> None:
        """Wait for this request's slot, within the configured bound. Raises `throttled` with the time left when the
        gate is closed by a wait the service asked for, or when the slot is further off than the bound; nothing is
        sent then."""
        with self._lock:
            now = self.clock()
            if now < self._closed_until:
                self.counts.held += 1
                raise self._refusal(self._closed_until - now, "the service asked to wait")
            self._recover(now)
            slot = max(now, self._next_slot)
            wait = slot - now
            if wait > self.settings.wait_seconds:
                self.counts.held += 1
                raise self._refusal(wait, "too many requests at once for this account")
            self._next_slot = slot + 1.0 / self.rate
            self.counts.sent += 1
            self.counts.paced_seconds += max(wait, 0.0)
        if wait > 0:
            self.sleep(wait)
            # The service may have asked to wait while this request slept for its slot (another request of the account
            # was refused): it is not sent then, whatever the turn it was given.
            with self._lock:
                left = self._closed_until - self.clock()
                if left > 0:
                    self.counts.sent -= 1
                    self.counts.held += 1
                    raise self._refusal(left, "the service asked to wait")

    @staticmethod
    def _refusal(left: float, detail: str) -> ConnectorError:
        return ConnectorError("throttled", detail, retry_after=max(1.0, left), reason="gate")

    def close(self, wait: float | None, status: int | None = None, reason: str = "throttled") -> None:
        """The service asked to wait `wait` seconds (the configured default when it gave none): nothing is sent until
        then. A wait that comes while the gate is closed already for as long (the same answer seen twice) changes
        nothing; any other halves the pace, to the floor. The answer's status and reason code are kept with the count
        of refusals."""
        seconds = self.settings.throttle_seconds if wait is None else max(wait, 0.0)
        with self._lock:
            now = self.clock()
            until = now + seconds
            at = self.wall()
            self.counts.refusals.append(Refusal(status, reason, wait, at, at + seconds))
            del self.counts.refusals[:-_KEPT]
            if now < self._closed_until:
                self._closed_until = max(self._closed_until, until)
                return
            self.rate = max(self.settings.floor_per_second, self.rate / 2)
            self._changed_at = now
            self._closed_until = until
            self._next_slot = max(self._next_slot, until)

    def mark(self) -> tuple[int, int, float, int]:
        """Where the counts stand now, for `since`: sent, held, paced seconds and how many refusals are kept."""
        with self._lock:
            c = self.counts
            return c.sent, c.held, c.paced_seconds, len(c.refusals)

    def since(self, mark: tuple[int, int, float, int]) -> Counts:
        """What the gate did after `mark` was taken."""
        with self._lock:
            c = self.counts
            sent, held, paced, kept = mark
            return Counts(c.sent - sent, c.held - held, c.paced_seconds - paced, list(c.refusals[kept:]))

    def closed_for(self) -> float:
        """Seconds the gate stays closed, 0 when it is open."""
        with self._lock:
            return max(0.0, self._closed_until - self.clock())


_lock = threading.Lock()
_gates: dict[tuple[str, str, str], Gate] = {}


def gate_for(
    sign_in: str,
    account: str,
    host: str,
    settings: GateSettings,
    declared_per_second: float | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Gate:
    """The one gate for a sign-in's account and host, made on first use and shared by everything after."""
    key = (sign_in, account.lower(), host.lower())
    with _lock:
        gate = _gates.get(key)
        if gate is None:
            gate = _gates[key] = Gate(settings, declared_per_second, clock or time.monotonic, sleep or time.sleep)
        else:
            gate.settings = settings
        return gate


def account_gates(sign_in: str, account: str) -> list[Gate]:
    """Every gate of one sign-in's account, whatever the host (the ones made so far)."""
    with _lock:
        return [g for (name, who, _host), g in sorted(_gates.items()) if name == sign_in and who == account.lower()]


def reset() -> None:
    """Forget every gate (tests, and a workspace that is closed)."""
    with _lock:
        _gates.clear()


class Gates:
    """The gates a web client passes: one per host, for one sign-in's account."""

    def __init__(
        self,
        sign_in: str,
        account: str,
        settings: GateSettings,
        declared_per_second: float | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self._args = (sign_in, account, settings, declared_per_second, clock, sleep)

    def for_host(self, host: str) -> Gate:
        sign_in, account, settings, declared, clock, sleep = self._args
        return gate_for(sign_in, account, host, settings, declared, clock, sleep)

    def all(self) -> list[Gate]:
        """The gates this account has so far, for every host it reached."""
        return account_gates(self._args[0], self._args[1])
