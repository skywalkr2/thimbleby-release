"""API route for Send feedback (design 7, Help): the last failures the person may add to a message, masked."""

from __future__ import annotations

import os

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
from engine import __version__, alpha_measures, problems, report_send, slow_screens
from engine.config import Config, ConfigError, load_config
from engine.reminder_content import own_address
from engine.storage import Store
from engine.today import zone
from engine.worker import Worker
from engine.workspace import Workspace


def build_feedback_router(ws: Workspace, cfg: Config, store: Store, worker: Worker) -> APIRouter:
    r = APIRouter(prefix="/api")

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
        operating system, and the person's own address when their record holds one, to offer as the reply address.
        Whether a report address is set says whether Report a problem is offered. Nothing is sent."""
        with store.read_scope():
            mine = own_address(store.read(), cfg.workspace.user.person)
        return ReportFacts(
            enabled=report_send.address(cfg.ui.report_to) is not None,
            version=__version__,
            system=report_send.system_text(),
            reply_to=mine,
        )

    @r.post("/report/send")
    def report_send_now(body: ReportSend) -> ReportSent:
        """Send the report the person approved, once: their words, the reply address, the version and system, and the
        problem lines as shown, to the configured address. It never raises for a service that did not take it; the
        answer says why, and the screen offers Try again and Copy the report."""
        to = report_send.address(cfg.ui.report_to)
        if to is None:
            raise HTTPException(status_code=404, detail="Report a problem isn't set up here.")
        done = report_send.send(
            to,
            words=body.words.strip(),
            reply_to=body.reply_to.strip(),
            version=__version__,
            problems=body.problems,
        )
        return ReportSent(ok=done.ok, why=done.why)

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
