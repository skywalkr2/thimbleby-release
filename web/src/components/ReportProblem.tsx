// Report a problem: the person writes what happened, sees exactly what will be sent (their words, their reply address, the
// app's version and system, and the recent problems the app kept, already masked by the server), and presses Send. Nothing
// leaves before that. The app's own server sends it to the makers' web form; a failure says why in words and offers Try
// again and Copy the report, which puts the same text on the clipboard so the person can mail it themselves.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { Heading } from "react-aria-components";
import { api } from "../lib/api";
import { copyMessage } from "../lib/copy";
import { problemLines } from "../lib/problem-lines";
import { useToasts } from "../lib/toasts";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { CheckboxGroup } from "../ui/CheckboxGroup";
import { FormField } from "../ui/FormField";
import { DialogFooter, ModalPanel } from "./ModalPanel";

/** The most characters of the problem lines the form takes. */
const PROBLEMS_MAX = 20000;
const ADDRESS = /^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/;

/** The lines cut at a whole line when they are longer than the form takes, so the preview and the send are the same text. */
function fit(lines: string): string {
  if (lines.length <= PROBLEMS_MAX) return lines;
  const cut = lines.slice(0, PROBLEMS_MAX);
  return cut.slice(0, Math.max(0, cut.lastIndexOf("\n")));
}

export function ReportProblem(props: { onClose: () => void; /** Words to start the report with, which the person may change; they are shown in what will be sent. */ initialWords?: string }) {
  const { t } = useWords();
  const { push } = useToasts();
  const base = useId();
  const [words, setWords] = useState(props.initialWords ?? "");
  const [reply, setReply] = useState("");
  const [replyTouched, setReplyTouched] = useState(false);
  const [withProblems, setWithProblems] = useState(true);
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);

  const facts = useQuery({ queryKey: ["report-facts"], queryFn: () => api.reportFacts(), gcTime: 0 });
  const recent = useQuery({ queryKey: ["feedback-problems"], queryFn: () => api.feedbackProblems(), gcTime: 0 });
  const found = recent.data?.problems ?? [];

  // The person's own address is offered once it is known, unless they have already typed in the field.
  const offered = facts.data?.reply_to ?? "";
  useEffect(() => {
    if (offered && !replyTouched) setReply(offered);
  }, [offered, replyTouched]);

  const addProblems = withProblems && found.length > 0;
  const problems = addProblems ? fit(problemLines(found, t).join("\n")) : "";
  const replyTrimmed = reply.trim();
  const replyBad = replyTrimmed !== "" && !ADDRESS.test(replyTrimmed);
  const ready = words.trim() !== "" && !replyBad && facts.isSuccess;

  const subject = t("report.subject", { app: t("app.name"), version: facts.data?.version ?? "" }).trim();
  const lines = [
    words.trim(),
    "",
    replyTrimmed ? t("report.line_reply", { address: replyTrimmed }) : t("report.line_reply_none"),
    t("report.line_version", { version: facts.data?.version ?? "" }),
    t("report.line_system", { system: facts.data?.system ?? "" }),
    ...(problems ? ["", problems] : []),
  ];
  const text = lines.join("\n").replace(/^\n+/, "");

  const copy = async () => {
    if ((await copyMessage(`${subject}\n\n${text}`)) === "blocked") {
      setBlocked(true);
      return;
    }
    setBlocked(false);
    push({ message: t("report.copied") });
  };

  const send = async () => {
    if (!ready || sending) return;
    setSending(true);
    setFailed(null);
    try {
      const done = await api.sendReport({ words: words.trim(), reply_to: replyTrimmed, problems });
      if (done.ok) {
        push({ message: t("report.sent") });
        props.onClose();
        return;
      }
      fail(t(`report.failed.${done.why ?? "unavailable"}`));
    } catch {
      fail(t("report.failed.unavailable"));
    } finally {
      setSending(false);
    }
  };
  // The toast's Try again runs the latest send, with whatever the form holds now.
  const again = useRef(send);
  again.current = send;
  const fail = (message: string) => {
    setFailed(message);
    push({
      message,
      tone: "warn",
      key: "report-failed",
      action: { label: t("report.retry"), run: () => again.current() },
      more: [{ label: t("report.copy"), run: () => void copy() }],
    });
  };

  const titleId = `${base}-title`;
  const wordsId = `${base}-words`;
  const hintId = `${base}-hint`;
  const replyId = `${base}-reply`;
  const replyNoteId = `${base}-reply-note`;
  const problemsId = `${base}-problems`;
  return (
    <ModalPanel titleId={titleId} onClose={props.onClose}>
      <Heading slot="title" id={titleId}>
        {t("report.title")}
      </Heading>
      <form onSubmit={(e) => e.preventDefault()}>
        <FormField id={wordsId} label={t("report.words")}>
          <textarea
            id={wordsId}
            className="short"
            autoFocus
            required
            value={words}
            aria-describedby={hintId}
            onChange={(e) => {
              setWords(e.target.value);
              setBlocked(false);
            }}
          />
          <span id={hintId} className="hint">
            {t("report.words_hint")}
          </span>
        </FormField>
        <FormField id={replyId} label={t("report.reply")}>
          <input
            id={replyId}
            type="email"
            autoComplete="email"
            value={reply}
            aria-invalid={replyBad || undefined}
            aria-describedby={replyBad ? replyNoteId : undefined}
            onChange={(e) => {
              setReply(e.target.value);
              setReplyTouched(true);
            }}
          />
          {replyBad && (
            <span id={replyNoteId} className="hint" role="status">
              {t("report.reply_bad")}
            </span>
          )}
        </FormField>
        {found.length > 0 && (
          <>
            <label className="check-line">
              <input type="checkbox" checked={withProblems} aria-describedby={problemsId} onChange={(e) => setWithProblems(e.target.checked)} />
              <span>{t("report.include", { count: found.length })}</span>
            </label>
            <span id={problemsId} className="hint">
              {t("report.include_hint")}
            </span>
          </>
        )}
        <CheckboxGroup legend={t("report.preview")}>
          <FormField id={`${base}-body`} label={t("report.preview")}>
            <textarea id={`${base}-body`} className="short" readOnly rows={Math.min(14, text.split("\n").length + 1)} value={text} />
          </FormField>
        </CheckboxGroup>
        {failed && (
          <p className="problem-note" role="alert">
            {failed}
          </p>
        )}
        {blocked && (
          <p className="problem-note" role="alert">
            {t("report.copy_blocked")}
          </p>
        )}
        <DialogFooter>
          <Button variant="quiet" onClick={props.onClose}>
            {t("action.close")}
          </Button>
          <Button variant="secondary" disabled={!ready} onClick={() => void copy()}>
            {t("report.copy")}
          </Button>
          <Button variant="primary" disabled={!ready || sending} reason={ready ? undefined : t("report.required")} onClick={() => void send()}>
            {sending ? t("report.sending") : failed ? t("report.retry") : t("report.send")}
          </Button>
        </DialogFooter>
      </form>
    </ModalPanel>
  );
}
