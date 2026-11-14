"""Sign-ins on this computer (design 11.4, "A session is not the install token").

The install token is made new at each start and does one thing: it opens a session. A session is a random value the
page keeps in its own storage (so it never leaves the address and port it was made for) and sends as a bearer header on
each call. Only a hash of each session is kept on disk, with when it ends, so a restart the person chose does not sign
them out and a copy of the file can sign in nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from engine.state_file import changing, write_whole

FILE = "sessions.json"
#: The most sessions kept; opening one more ends the oldest.
MAX_SESSIONS = 20


def _hash(session: str) -> str:
    return hashlib.sha256(session.encode("utf-8")).hexdigest()


class Sessions:
    def __init__(self, folder: Path, lifetime_days: int) -> None:
        self.path = Path(folder) / FILE
        self.lifetime = lifetime_days * 86400
        self._pinned: set[str] = set()
        self._read: tuple[tuple[int, int], dict] | None = None

    def pin(self, session: str) -> None:
        """Count a value as a session for as long as this program runs, without keeping it on disk or ever ending it.
        For the test harnesses, which send one fixed value as the bearer; the product never calls it."""
        self._pinned.add(_hash(session))

    def _load(self, now: float) -> dict[str, float]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            h: float(end)
            for h, end in data.items()
            if isinstance(h, str) and isinstance(end, (int, float)) and end > now
        }

    def _save(self, kept: dict[str, float]) -> None:
        write_whole(self.path, json.dumps(kept), mode=0o600)

    def admit(self, session: str, now: float | None = None) -> None:
        """Keep a session value as signed in until it ends, on disk as a hash."""
        now = time.time() if now is None else now
        with changing(self.path):
            kept = self._load(now)
            kept[_hash(session)] = now + self.lifetime
            for old in sorted(kept, key=kept.__getitem__)[: max(0, len(kept) - MAX_SESSIONS)]:
                del kept[old]
            self._save(kept)

    def open(self, now: float | None = None) -> str:
        """Make a new session and keep it; the value is returned once and never stored."""
        session = secrets.token_urlsafe(32)
        self.admit(session, now)
        return session

    def valid(self, session: str, now: float | None = None) -> bool:
        """Whether the value is a session that has not ended."""
        now = time.time() if now is None else now
        wanted = _hash(session)
        if wanted in self._pinned:
            return True
        with changing(self.path):
            return any(hmac.compare_digest(wanted, h) for h in self._load(now))

    def close(self, session: str) -> None:
        with changing(self.path):
            kept = self._load(time.time())
            if kept.pop(_hash(session), None) is not None:
                self._save(kept)
