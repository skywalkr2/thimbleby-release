"""The private content log: lines that can hold what the assistant or a service said (an agent's printed output when it
was stopped, an unreadable answer's parse error, a refused change's reason). They go to their own file beside the app's
log (`engine.app_log`), masked the same way, and never into the app's log, whose end a problem report offers to send.
The person can open the file; nothing sends it."""

from __future__ import annotations

import logging

NAME = "thimbleby.content"
#: What comes before the words kept in a content log line.
SAID = " | said: "
#: The most characters one content log line keeps.
LINE_LIMIT = 8000

log = logging.getLogger(NAME)


def keep(head: str, said: object) -> None:
    """One content log line: a short fixed head saying what happened, then what was said, on one line."""
    log.warning("%s%s%r", head, SAID, said)


def said_in(text: str) -> list[str]:
    """The words the content log's lines kept, without their heads, times or levels."""
    return [line.partition(SAID)[2] for line in text.splitlines() if SAID in line]
