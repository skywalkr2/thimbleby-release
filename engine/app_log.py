"""The app's own log file (design 6.13): a rotating file in the workspace's private folder that a person can send with a
bug report, holding what went wrong in full detail: the time, the place in the code, and each error's traceback.

What it never holds is what the person gave the app. Every line is masked before it is written, the same way a
feedback report is (`engine.problems.mask`): keys, tokens and passwords, email addresses, file paths, the names of the
workspace's own people, projects and files, and a URL's all but its host. A traceback keeps its frames (the code's own
file, line and function) and the code on each line, and masks the error's message. The level, the size of a file and
how many files are kept are settings (`server.log_level`, `server.log_max_mb`, `server.log_files`). Nothing here is
sent anywhere: the person sends the file, or not. A traceback is written here and never shown on a screen.
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import os
import re
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine import content_log, problems
from engine.state_file import write_whole

FOLDER = "logs"
FILE = "thimbleby.log"
#: The private content log beside it (`engine.content_log`), never part of a report.
CONTENT_FILE = "content.log"
#: How many content log files are kept.
CONTENT_FILES = 2
#: How long the names the workspace's records give are kept before they are read again, so a log line costs no read.
NAMES_FOR = 60.0
#: The most characters one masked line of an error's message keeps.
LINE_LIMIT = 600
#: The most errors deep a chain or a group of errors is followed.
MAX_DEPTH = 8
#: Loggers whose lines carry what the person asked for or opened (addresses with ids and tokens), never kept.
SILENT = ("uvicorn.access",)

_MARKERS = ("/site-packages/", "/engine/", "/api/", "/plugins/")


def log_path(ws: Any) -> Path:
    return ws.private_dir / FOLDER / FILE


def content_path(ws: Any) -> Path:
    return ws.private_dir / FOLDER / CONTENT_FILE


def short_path(path: str) -> str:
    """A code file's place without the folders of this computer: from its package on, else only its name."""
    clean = path.replace("\\", "/")
    for marker in _MARKERS:
        at = clean.rfind(marker)
        if at >= 0:
            return clean[at + (len(marker) if marker == "/site-packages/" else 1) :]
    return clean.rsplit("/", 1)[-1]


class MaskedFormatter(logging.Formatter):
    """A line with its message masked and its traceback shown by place and masked message."""

    def __init__(self, hide: Callable[[str | None], str], limit: int = LINE_LIMIT) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self.hide = hide
        self.limit = limit

    def _cut(self, text: str) -> str:
        return text if len(text) <= self.limit else text[: self.limit - 1] + "…"

    def format(self, record: logging.LogRecord) -> str:
        message = self._cut(self.hide(record.getMessage()))
        line = f"{self.formatTime(record)} {record.levelname} {record.name}: {message}"
        if record.exc_info and record.exc_info[1] is not None:
            line += "\n" + self.formatException(record.exc_info)
        return line

    def formatException(self, ei: Any) -> str:  # noqa: N802 - the logging module's own name
        out: list[str] = []
        self._render(traceback.TracebackException(*ei), out, 0)
        return "\n".join(out)

    def _render(self, found: traceback.TracebackException, out: list[str], depth: int) -> None:
        """One error and what led to it: each frame by place and code, and the message masked. The frames are read from
        the error's own record, never from text, so a message can't pass for code."""
        pad = "  " * depth
        if depth < MAX_DEPTH:
            if found.__cause__ is not None:
                self._render(found.__cause__, out, depth)
                out.append(f"{pad}The above exception was the direct cause of the following exception:")
            elif found.__context__ is not None and not found.__suppress_context__:
                self._render(found.__context__, out, depth)
                out.append(f"{pad}During handling of the above exception, another exception occurred:")
        out.append(f"{pad}Traceback (most recent call last):")
        for frame in found.stack:
            out.append(f'{pad}  File "{short_path(frame.filename)}", line {frame.lineno}, in {frame.name}')
            if frame.line:
                out.append(f"{pad}    {frame.line}")
        for text in found.format_exception_only():
            for line in text.rstrip("\n").splitlines():
                out.append(pad + self._cut(self.hide(line)))
        for sub in found.exceptions or ():
            if depth < MAX_DEPTH:
                self._render(sub, out, depth + 1)


class _Private(logging.handlers.RotatingFileHandler):
    """A rotating file only this person's account can read, each file as it is made."""

    def _open(self) -> Any:
        stream = super()._open()
        with contextlib.suppress(OSError):
            os.chmod(self.baseFilename, 0o600)
        return stream


class _Drop(logging.Filter):
    """The app's log keeps neither the silent loggers' lines nor the content log's."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith((*SILENT, content_log.NAME))


class _Names:
    """The masker, found again at most once in `NAMES_FOR` seconds: the names records give change while the app runs."""

    def __init__(self, ws: Any, store: Any, cfg: Any) -> None:
        self.args = (ws, store, cfg)
        self.at = -NAMES_FOR
        self.masker = problems.Masker()

    def __call__(self, text: str | None) -> str:
        if time.monotonic() - self.at >= NAMES_FOR:
            try:
                self.masker = problems.masker_for(*self.args)
            except Exception:  # never stops a line from being written; the shape-based masking still applies
                self.masker = problems.Masker()
            self.at = time.monotonic()
        return self.masker(text)


#: Lines earlier builds wrote to the app's log that hold what the assistant or an agent said, and the head each keeps:
#: what follows the head is taken out when the log starts (`clean_earlier_lines`).
EARLIER_CONTENT = (
    re.compile(r"(the agent was stopped after \d+ seconds); it had printed: .*"),
    re.compile(r"(The assistant's answer couldn't be read after a second try): .*"),
    # A refused change's reason, which quotes the records it names; today's builds write only the fixed words below.
    re.compile(r"(Request [A-Z]+-\d+): (?!the change couldn't be kept$).*"),
)
#: How a log entry's first line starts; a line that doesn't is the rest of the entry before it.
_ENTRY_START = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")
#: What stands in for the words taken out.
TAKEN_OUT = " (what it said was taken out of this log)"


def clean_earlier_lines(ws: Any) -> int:
    """Take out of the app's log files the words earlier builds wrote there that can hold the assistant's or an
    agent's output, keeping each line's head, so a report that offers the log's end never carries them. Returns how
    many lines changed; a file that can't be read or written is left as it is."""
    changed = 0
    for path in sorted(log_path(ws).parent.glob(FILE + "*")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines: list[str] = []
        cutting = False  # the entry being read had its words taken out: its further lines go too
        for line in text.split("\n"):
            if not _ENTRY_START.match(line):
                if cutting:
                    changed += 1
                    continue
                lines.append(line)
                continue
            cutting = False
            for pattern in EARLIER_CONTENT:
                found = pattern.search(line)
                if found is not None:
                    line = line[: found.start()] + found.group(1) + TAKEN_OUT
                    changed += 1
                    cutting = True
                    break
            lines.append(line)
        if "\n".join(lines) != text:
            with contextlib.suppress(OSError):
                write_whole(path, "\n".join(lines), mode=0o600)
    return changed


def install(ws: Any, cfg: Any, store: Any, *, max_bytes: int | None = None) -> logging.Handler | None:
    """Start writing the log for this workspace: the handler is on the root logger, at the configured level. Returns it
    (for `remove`), or None when the folder can't be written, which never stops the app."""
    path = log_path(ws)
    clean_earlier_lines(ws)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = _Private(
            path,
            maxBytes=max_bytes if max_bytes is not None else cfg.server.log_max_mb * 1024 * 1024,
            backupCount=max(0, cfg.server.log_files - 1),
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return None
    level = getattr(logging, cfg.server.log_level.upper())
    handler.setLevel(level)
    handler.setFormatter(MaskedFormatter(_Names(ws, store, cfg)))
    handler.addFilter(_Drop())
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    handler.content = _content_handler(ws, cfg, store, max_bytes)  # type: ignore[attr-defined]
    return handler


def _content_handler(ws: Any, cfg: Any, store: Any, max_bytes: int | None) -> logging.Handler | None:
    """The content log's own file: masked like the app's log, on the content logger only."""
    try:
        handler = _Private(
            content_path(ws),
            maxBytes=max_bytes if max_bytes is not None else cfg.server.log_max_mb * 1024 * 1024,
            backupCount=CONTENT_FILES - 1,
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return None
    handler.setFormatter(MaskedFormatter(_Names(ws, store, cfg), limit=content_log.LINE_LIMIT))
    content_log.log.addHandler(handler)
    if content_log.log.level == logging.NOTSET or content_log.log.level > logging.WARNING:
        content_log.log.setLevel(logging.WARNING)
    return handler


def remove(handler: logging.Handler | None) -> None:
    if handler is None:
        return
    logging.getLogger().removeHandler(handler)
    handler.close()
    content = getattr(handler, "content", None)
    if content is not None:
        content_log.log.removeHandler(content)
        content.close()
