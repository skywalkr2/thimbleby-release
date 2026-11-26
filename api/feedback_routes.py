"""API route for Send feedback (design 7, Help): the last failures the person may add to a message, masked."""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from api.schemas import (
    AlphaNumbers,
    FeedbackProblem,
    FeedbackProblems,
    ReportFacts,
    ReportSend,
    ReportSent,
    SlowScreenReport,
)
from engine import __version__, alpha_measures, app_log, content_log, problems, report_send, slow_screens
from engine.config import Config, ConfigError, load_config
from engine.reminder_content import own_address
from engine.sides import word
from engine.storage import Store
from engine.today import zone
from engine.worker import Worker
from engine.workspace import Workspace


def build_feedback_router(ws: Workspace, cfg: Config, store: Store, worker: Worker) -> APIRouter:
    r = APIRouter(prefix="/api")

    def _scrubbed_details(shown: str, room: int = 0) -> str:
        """The details the person was shown, passed through the same scrub and limit again before they leave."""
        with store.read_scope():
            hide = problems.masker_for(ws, store, cfg)
        return report_send.details_text(
            shown, masker=hide, folders={str(ws.root): "<workspace>"}, limit=report_send.LIMITS["details"] - room
        )

    def _without_private() -> Callable[[str], tuple[str, int]]:
        """What takes out of a report part each line that may hold the person's material: kept answers, round
        reasons, failed runs' error text and the content log, read once for the report."""
        with store.read_scope():
            material = problems.private_material(store, current(), worker.now())
            hide = problems.masker_for(ws, store, cfg)
        material += content_log.said_in(_content_log_text())
        removed = word(current(), "report.removed_line")
        return lambda text: report_send.without_private(text, material, removed, hide)

    def _content_log_text() -> str:
        """The private content log's newest file, which can hold the assistant's words; empty when there is none."""
        try:
            return app_log.content_path(ws).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def current() -> Config:
        """The settings as the files hold them now, so a change to how far back or how many applies at once."""
        try:
            return load_config(ws.config_dir, env=dict(os.environ))
        except ConfigError:
            return cfg

    @r.get("/feedback/problems")
    def feedback_problems() -> FeedbackProblems:
        """The failures of the last `ui.feedback_problem_days` days, newest first and at most `ui.feedback_problem_max`:
        failed AI calls, account checks and source reads, and errors in the app. Each has when, what was being done,
        the account's service, adapter and program version, the request's settings, the status, the error kind and the
        service's own error text. Secrets, addresses, paths and the names of the workspace's own people, projects and
        files are masked; nothing the person wrote or read is in it. The app sends nothing: the person sends it."""
        live = current()
        here = zone(live)
        found = problems.recent(ws, store, live, worker.now())
        return FeedbackProblems(
            problems=[
                FeedbackProblem(
                    at=p.at.astimezone(here),
                    doing=p.doing,
                    what=p.what,
                    service=p.service,
                    adapter=p.adapter,
                    program_version=p.program_version,
                    params=p.params,
                    status=p.status,
                    error_kind=p.error_kind,
                    text=p.text,
                )
                for p in found
            ]
        )

    @r.get("/alpha-measures")
    def alpha_numbers() -> AlphaNumbers:
        """The alpha's five numbers for this person, from the records on this computer: days used in the first week,
        cost per day, corrections per day, drafts sent as written and edited, and minutes from install to a first
        result. Nothing is sent: sharing them is the person's own Send in Report a problem."""
        here = zone(current())
        with store.read_scope():
            found = alpha_measures.alpha_measures(store.read(), worker.now(), here)
        return AlphaNumbers(
            since=found.since,
            until=found.until,
            days_so_far=found.days_so_far,
            complete=found.complete,
            days_used=found.days_used,
            cost_per_day=found.cost_per_day,
            corrections_per_day=found.corrections_per_day,
            sent_as_written=found.sent_as_written,
            sent_edited=found.sent_edited,
            first_result_minutes=found.first_result_minutes,
        )

    @r.get("/report/facts")
    def report_facts() -> ReportFacts:
        """What a problem report states besides the person's words and the problem lines: the app's version, the
        operating system, the person's own address when their record holds one, to offer as the reply address, and
        the technical details a report would carry.
        Whether a report address is set says whether Report a problem is offered. Nothing is sent."""
        with store.read_scope():
            mine = own_address(store.read(), cfg.workspace.user.person)
            kept = problems.last_stopped_answer(store, current(), worker.now())
            details = report_send.details_for(ws, store, cfg, answer_offered=kept is not None)
        details, removed_lines = _without_private()(details)
        answer = report_send.answer_block(kept[1], kept[0].date().isoformat()) if kept is not None else ""
        return ReportFacts(
            enabled=report_send.address(cfg.ui.report_to) is not None,
            version=__version__,
            system=report_send.system_text(),
            reply_to=mine,
            details=details,
            answer=answer,
            removed_lines=removed_lines,
        )

    @r.post("/report/send")
    def report_send_now(body: ReportSend) -> ReportSent:
        """Send the report the person approved, once: their words, the reply address, the version and system, and the
        problem lines as shown, to the configured address. It never raises for a service that did not take it; the
        answer says why, and the screen offers Try again and Copy the report."""
        to = report_send.address(cfg.ui.report_to)
        if to is None:
            raise HTTPException(status_code=404, detail="Report a problem isn't set up here.")
        answer = ""
        if body.include_answer:
            # Only the preview this server made goes: a block it didn't make, or one older than the newest, is refused.
            kept = problems.last_stopped_answer(store, current(), worker.now())
            shown = report_send.answer_block(kept[1], kept[0].date().isoformat()) if kept is not None else ""
            if not shown or body.answer_block != shown:
                raise HTTPException(
                    status_code=409, detail="The answer shown is no longer the one kept. Open the report again."
                )
            answer = shown
        # Nothing of the assistant's or a service's words leaves in the problem lines or the details, whatever the
        # screen sent: a line that may hold it goes as "removed", and the rest is sent, so a report is never lost.
        cut = _without_private()
        problems_out, from_problems = cut(body.problems)
        details_out, from_details = cut(body.details if body.include_details else "")
        room = report_send.ANSWER_MAX + report_send.ANSWER_HEADING_ROOM if body.answer_block else 0
        done = report_send.send(
            to,
            words=body.words.strip(),
            reply_to=body.reply_to.strip(),
            version=__version__,
            problems=problems_out,
            details=report_send.with_answer(
                _scrubbed_details(details_out, room=room) if body.include_details else "", answer
            ),
        )
        return ReportSent(ok=done.ok, why=done.why, removed_lines=from_problems + from_details)

    @r.get("/slow-screens/{screen}/report")
    def slow_screen_report(screen: str) -> SlowScreenReport:
        """The report for a main screen that is slow now (design 6.13): its name, how long it took, the limit, and how
        many records of each kind the workspace holds. The app sends nothing: the person reads it and sends it."""
        found = slow_screens.for_workspace(ws.root, cfg.server.slow_screen_ms)
        seconds = found.slow().get(screen)
        if seconds is None:
            raise HTTPException(status_code=404, detail="That screen isn't slow now.")
        with store.read_scope():
            title, text = slow_screens.report_text(cfg, store, screen, seconds, found.limit_ms)
        return SlowScreenReport(title=title, text=text)

    return r
