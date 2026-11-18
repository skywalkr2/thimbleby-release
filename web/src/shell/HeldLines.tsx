// Today's lines for work that has stopped or that needs a look before it can go on (design 7.7, 8.5): work held until the
// app restarts, an AI account paused until its usage limit resets, work waiting for the network, the synced folder that
// can't be used until the person settles which copy to keep, a backup account that hasn't passed its check, a kind of
// file that isn't being read, the standing rules to look over, and a switch of account or model whose check found
// problems.
// Each is one row of the Today queue that says what to do first, with the one button that does it (a few offer a second,
// as design 7.6 allows for held lines). The lines come from the queue; a line is gone once its cause is, and only the
// person's own click ever restarts the app.
import { useQuery } from "@tanstack/react-query";
import { isValidElement, useState, type ReactNode } from "react";
import { api, type S } from "../lib/api";
import { NO_RECORD_ACTS, useAct } from "../lib/act";
import { useAccountNames } from "../lib/account-names";
import { useTierName } from "../lib/ai-routing";
import { withoutAddress } from "../lib/calendar";
import { whenWords } from "../lib/coverage";
import { day, noReset, wallWhen } from "../lib/dates";
import { useEstimate, useMoney } from "../lib/money";
import { useRestart, useRestartText } from "../lib/restart";
import { inOrder, useActSaved, useAfterSave, useFreshFingerprint } from "../lib/settings-save";
import { useSignInWindow } from "../lib/sign-in-window";
import { useWords } from "../lib/wording";
import { Button, ButtonLink } from "../ui/Button";
import { domainOf } from "../components/SafeText";
import { atMost } from "../components/LookBack";
import { IconButton } from "../ui/IconButton";
import { MenuButton } from "../ui/MenuButton";
import { Pill, type PillTone } from "../ui/Pill";
import { StateMark, withStatus } from "../ui/StateMark";
import { Icon, type IconName } from "../ui/Icon";
import { Row, type RowProps } from "../ui/Row";
import { AccountMoveLine, ModelMovedLine, ModelWatchLine } from "./ModelLines";
import styles from "./HeldLines.module.css";

/** The icon in each held line's 24px slot: what kind of thing holds the assistant's work (a restart, a failure, a paused account, a
 * folder, a message to send), so no held line has an empty slot while the others in its list have a mark. */
const HELD_ICON: Record<string, IconName> = {
  restart: "refresh",
  stuck: "alert",
  paused: "alert",
  borrow: "users",
  credential: "alert",
  offline: "alert",
  handover: "archive",
  account_check: "alert",
  switch_failed: "alert",
  identity: "users",
  work_access: "alert",
  sent_folder: "folder",
  folder_rename: "folder",
  update: "refresh",
  updated: "check",
  extractor: "alert",
  source_unread: "inbox",
  slow_screen: "alert",
  catch_up_go: "inbox",
  intake_go: "inbox",
  older_read: "refresh",
  rule_review: "book",
  pack_tier: "puzzle",
  no_account: "alert",
};

/** A held line's row: the shared row with the icon of its kind in the leading slot. */
function HeldRow(props: RowProps & { "data-queue-line": string }) {
  const icon = HELD_ICON[props["data-queue-line"]] ?? "alert";
  // The kind's mark is the line's status: a dot and a word at the start of its meta, never a chip after the title.
  const { pill, meta, ...rest } = props;
  const status = isValidElement<{ tone?: PillTone; children: ReactNode }>(pill) && pill.type === Pill ? { tone: pill.props.tone, word: pill.props.children } : null;
  return <Row lead={<Icon name={icon} />} {...rest} pill={status ? undefined : pill} meta={withStatus(status, meta)} />;
}

type Line = S["QueueLineView"];

/** The kinds of queue line that are a stop or a check on the assistant's own work, each drawn here with its one button. */
export const HELD_KINDS: Line["kind"][] = ["restart", "stuck", "paused", "borrow", "credential", "no_account", "pack_tier", "offline", "handover", "account_check", "switch_failed", "account_move", "sent_folder", "folder_rename", "update", "updated", "model_watch", "model_moved", "identity", "work_access", "extractor", "source_unread", "slow_screen", "rule_review", "catch_up_go", "intake_go", "older_read"];

export function isHeld(line: Line): boolean {
  return HELD_KINDS.includes(line.kind);
}

/** One held line of the Today queue, drawn by its kind. */
export function HeldLine(props: {
  line: Line;
  onOpenAiAccounts: () => void;
  onOpenHandover: () => void;
  onOpenRules?: () => void;
  onOpenKnowledge?: () => void;
  onAddAccount?: () => void;
  onOpenSources?: () => void;
}) {
  const { line } = props;
  switch (line.kind) {
    case "restart":
      return <RestartLine line={line} />;
    case "stuck":
      return <StuckLine line={line} />;
    case "handover":
      return <HandoverLine line={line} onOpen={props.onOpenHandover} />;
    case "borrow":
      return <BorrowLine line={line} />;
    case "credential":
      return <CredentialLine line={line} onOpenAiAccounts={props.onOpenAiAccounts} />;
    case "offline":
      return <OfflineLine line={line} />;
    case "account_check":
      return <AccountCheckLine line={line} />;
    case "switch_failed":
      return <SwitchFailedLine line={line} />;
    case "account_move":
      return <AccountMoveLine line={line} />;
    case "sent_folder":
      return <SentFolderLine line={line} onOpen={props.onOpenSources} />;
    case "folder_rename":
      return <FolderRenameLine line={line} />;
    case "update":
      return <UpdateLine line={line} />;
    case "updated":
      return <UpdatedLine line={line} />;
    case "model_watch":
      return <ModelWatchLine line={line} />;
    case "model_moved":
      return <ModelMovedLine line={line} />;
    case "identity":
      return <IdentityLine line={line} onOpenAiAccounts={props.onOpenAiAccounts} />;
    case "work_access":
      return <WorkAccessLine line={line} />;
    case "extractor":
      return <ExtractorLine line={line} />;
    case "source_unread":
      return <SourceUnreadLine line={line} onOpen={props.onOpenSources} />;
    case "slow_screen":
      return <SlowScreenLine line={line} />;
    case "rule_review":
      return <RuleReviewLine line={line} onOpen={props.onOpenRules} onOpenKnowledge={props.onOpenKnowledge} />;
    case "no_account":
      return <NoAccountLine line={line} onAdd={props.onAddAccount ?? props.onOpenAiAccounts} />;
    case "pack_tier":
      return <PackTierLine line={line} onOpen={props.onOpenAiAccounts} />;
    case "catch_up_go":
      return <CatchUpGoLine line={line} />;
    case "intake_go":
      return <IntakeGoLine line={line} />;
    case "older_read":
      return <OlderReadLine line={line} />;
    default:
      return <PausedLine line={line} onOpenAiAccounts={props.onOpenAiAccounts} />;
  }
}

function RestartLine(props: { line: Line }) {
  const { t, tn } = useWords();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const restart = useRestart();
  const progress = useRestartText();
  const canRestart = !!status.data?.can_restart;
  const label = tn("queue.restart", props.line.count);
  // While a restart is under way its own words replace the explanation, so the line follows the same flow as the header.
  const sub = progress && restart.phase !== "asking" ? progress : t(status.data && !canRestart ? "queue.restart.manual" : "queue.restart.sub");
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.restart.label")}
      data-queue-line="restart"
      pill={<Pill tone="warn">{t("queue.restart.label")}</Pill>}
      title={label}
      meta={sub}
      primary={
        canRestart ? (
          <>
          <Button size="sm" variant="primary" data-key="primary" disabled={restart.busy || restart.waiting} onClick={() => void restart.now()}>
            {t("restart.now")}
          </Button>
          </>
        ) : undefined
      }
    />
  );
}

function StuckLine(props: { line: Line }) {
  const { t } = useWords();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const restart = useRestart();
  const canRestart = !!status.data?.can_restart;
  const time = props.line.waiting_since ? wallWhen(props.line.waiting_since) : "";
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.stuck.label")}
      data-queue-line="stuck"
      pill={<Pill tone="danger">{t("queue.stuck.label")}</Pill>}
      title={<>{t("queue.stuck.text", { time })}</>}
      meta={t(status.data && !canRestart ? "queue.restart.manual" : "queue.stuck.sub")}
      primary={
        canRestart ? (
          <>
          <Button size="sm" variant="primary" data-key="primary" disabled={restart.busy || restart.waiting} onClick={() => void restart.now()}>
            {t("restart.now")}
          </Button>
          </>
        ) : undefined
      }
    />
  );
}

function PausedLine(props: { line: Line; onOpenAiAccounts: () => void }) {
  const { t, tn } = useWords();
  const nameOf = useAccountNames();
  const { line } = props;
  const credit = noReset(line.until);
  const label = tn(credit ? "queue.paused_credit" : "queue.paused", line.count, { account: nameOf(line.account ?? ""), time: line.until && !credit ? wallWhen(line.until) : "" });
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.paused.label")}
      data-queue-line="paused"
      pill={<Pill tone="warn">{t("queue.paused.label")}</Pill>}
      title={label}
      meta={t(credit ? "queue.paused_credit.sub" : "queue.paused.sub")}
      primary={
        
        <>
        <Button size="sm" variant="primary" data-key="primary" onClick={props.onOpenAiAccounts}>
          {t("queue.paused.open")}
        </Button>
              </>
      }
    />
  );
}

/** Every account a kind of work can use is waiting for its limit to reset and another kind of work's account is free:
 * the question says which, until when and what it would cost, and nothing is borrowed until the person says yes. */
function BorrowLine(props: { line: Line }) {
  const { t, tn, has } = useWords();
  const act = useAct();
  const estimate = useEstimate();
  const [busy, setBusy] = useState<"yes" | "no" | null>(null);
  const nameOf = useAccountNames();
  const { line } = props;
  const accountId = line.account ?? "";
  const account = nameOf(accountId);
  const paused = nameOf(line.text ?? "");
  const time = line.until ? wallWhen(line.until) : "";
  const work = t(has(`queue.borrow.work.${line.tier}`) ? `queue.borrow.work.${line.tier}` : "queue.borrow.work.other");
  const cost = line.estimate_usd == null ? null : estimate(line.estimate_usd);
  const sub =
    cost === null
      ? tn("queue.borrow.unpriced", line.count)
      : line.unpriced > 0
        ? tn("queue.borrow.mixed", line.count, { cost })
        : tn("queue.borrow.priced", line.count, { cost });
  const answer = async (use: boolean) => {
    setBusy(use ? "yes" : "no");
    await act(
      () => api.borrowAccount({ tier: line.tier ?? "", account: accountId, model: line.model ?? "", use }),
      () => ({ message: use ? t("queue.borrow.yes_toast", { account, time }) : t("queue.borrow.no_toast", { paused }) }),
    );
    setBusy(null);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.borrow.label")}
      data-queue-line="borrow"
      pill={<Pill tone="warn">{t("queue.borrow.label")}</Pill>}
      title={<>{t("queue.borrow", { account, work, paused, time })}</>}
      meta={sub}
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" loading={busy === "yes"} disabled={busy !== null} aria-label={t("queue.borrow.yes_named", { account, work })} onClick={() => void answer(true)}>
          {t("queue.borrow.yes")}
        </Button>
        <Button size="sm" variant="secondary" loading={busy === "no"} disabled={busy !== null} onClick={() => void answer(false)}>
          {t("queue.borrow.no")}
        </Button>
              </>
      }
    />
  );
}

/** A key or sign-in that stops working on a known day, or already has: what to renew and by when, every place the same
 * credential is used, and the one button that starts renewing it. The line is gone once the new end date is set or the
 * sign-in is made again. */
function CredentialLine(props: { line: Line; onOpenAiAccounts: () => void }) {
  const { t } = useWords();
  const { line } = props;
  const [first = "", ...others] = line.places ?? [];
  const signIn = line.credential_kind === "sign_in";
  const past = (line.waiting_days ?? 0) < 0;
  const date = line.due ? day(line.due) : "";
  const { start, busy, problem } = useSignInWindow(line.credential_name ?? "");
  const text = t(`queue.credential.${signIn ? "sign_in" : "account"}.${past ? "past" : "soon"}`, { thing: first, date });
  const label = t(signIn ? "queue.credential.sign_in_label" : "queue.credential.label");
  const also = signIn ? t(`queue.credential.sign_in.also.${past ? "past" : "soon"}`, { date }) : t("queue.credential.also");
  return (
    <HeldRow
      as="section"
      aria-label={label}
      data-queue-line="credential"
      pill={<Pill tone="warn">{label}</Pill>}
      title={text}
      primary={
        <>
        {signIn ? (
          <Button size="sm" variant="primary" data-key="primary" loading={busy} onClick={() => void start()}>
            {t("queue.credential.sign_in")}
          </Button>
        ) : (
          <Button size="sm" variant="primary" data-key="primary" onClick={props.onOpenAiAccounts}>
            {t("queue.credential.open")}
          </Button>
        )}
              </>
      }
    >
        {others.length > 0 ? (
          <>
            <p className="hint">{also}</p>
            <ul className={styles.places}>
              {others.map((place) => (
                <li key={place}>{place}</li>
              ))}
            </ul>
          </>
        ) : (
          <p className="hint">{t("queue.credential.only")}</p>
        )}
        {problem && <p className="problem-note">{problem}</p>}
          </HeldRow>
  );
}

function OfflineLine(props: { line: Line }) {
  const { t, tn } = useWords();
  const { line } = props;
  const label = tn("queue.offline", line.count, { time: line.waiting_since ? wallWhen(line.waiting_since) : "" });
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.offline.label")}
      data-queue-line="offline"
      pill={<Pill tone="warn">{t("queue.offline.label")}</Pill>}
      title={label}
      meta={t("queue.offline.sub")}
    />
  );
}

function HandoverLine(props: { line: Line; onOpen: () => void }) {
  const { t } = useWords();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const restart = useRestart();
  const state = props.line.state ?? "diverged";
  const computer = props.line.text ?? "";
  const text =
    state === "chosen"
      ? t("queue.handover.chosen")
      : state === "taken"
        ? t("queue.handover.taken")
        : state === "elsewhere"
        ? computer
          ? t("queue.handover.elsewhere", { computer })
          : t("queue.handover.elsewhere_unknown")
        : t("queue.handover.diverged");
  // Once a copy is chosen the one thing left is the restart, and only the person's click restarts.
  const canRestart = state === "chosen" && !!status.data?.can_restart;
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.handover.label")}
      data-queue-line="handover"
      pill={<Pill tone="warn">{t("queue.handover.label")}</Pill>}
      title={text}
      meta={<>{t(`queue.handover.${state}_sub`)}</>}
      primary={
        <>
        {canRestart && (
          <Button size="sm" variant="primary" data-key="primary" disabled={restart.busy || restart.waiting} onClick={() => void restart.now()}>
            {t("restart.now")}
          </Button>
        )}
        <Button size="sm" variant={canRestart ? "secondary" : "primary"} data-key={canRestart ? undefined : "primary"} onClick={props.onOpen}>
          {t(`queue.handover.open_${state}`)}
        </Button>
              </>
      }
    />
  );
}

/** A backup account that hasn't passed its check for the work it would stand in for: Check now runs that test, and the
 * line is gone once it passes. */
function AccountCheckLine(props: { line: Line }) {
  const { t, has } = useWords();
  const act = useAct();
  const nameOf = useAccountNames();
  const [checking, setChecking] = useState(false);
  const { line } = props;
  const accountId = line.account ?? "";
  const account = nameOf(accountId);
  const work = t(has(`queue.account_check.work.${line.tier}`) ? `queue.account_check.work.${line.tier}` : "queue.account_check.work.other");
  const run = async () => {
    setChecking(true);
    await act(
      () => api.testAccount(accountId, line.tier ?? undefined, line.model ?? undefined),
      (results) => {
        const bad = results.find((r) => !r.ok);
        return { message: bad ? t("queue.account_check.not_passed", { account, detail: bad.detail }) : t("queue.account_check.passed", { account, work }) };
      },
      undefined,
      NO_RECORD_ACTS.checkAccount,
    );
    setChecking(false);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.account_check.label")}
      data-queue-line="account_check"
      pill={<Pill tone="warn">{t("queue.account_check.label")}</Pill>}
      title={<>{t("queue.account_check", { account, work })}</>}
      meta={t(line.check_failed ? "queue.account_check.sub_failed" : "queue.account_check.sub")}
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" loading={checking} aria-label={t("queue.account_check.run_named", { account, work })} onClick={() => void run()}>
          {t("queue.account_check.run")}
        </Button>
              </>
      }
    />
  );
}

/** A switch of a kind of work's account or model whose check found problems, or couldn't finish: what didn't come out
 * right, and the two ways forward. Switch back puts the earlier choice back at once, with Undo; Keep it leaves the
 * switch. The line is gone once either is chosen. */
function SwitchFailedLine(props: { line: Line }) {
  const { t, tn, has } = useWords();
  const act = useAct();
  const fingerprint = useFreshFingerprint();
  const [busy, setBusy] = useState<"back" | "keep" | null>(null);
  const nameOf = useAccountNames();
  const { line } = props;
  const tier = line.tier ?? "";
  const account = nameOf(line.account ?? "");
  const previous = nameOf(line.text ?? "");
  const work = t(has(`queue.switch_failed.work.${tier}`) ? `queue.switch_failed.work.${tier}` : "queue.switch_failed.work.other");
  const names = line.names ?? [];
  const back = async () => {
    setBusy("back");
    await act(
      async () => inOrder(async () => api.switchBack(tier, await fingerprint())),
      () => ({ message: t("queue.switch_failed.back_toast", { work, previous }) }),
    );
    setBusy(null);
  };
  const keep = async () => {
    setBusy("keep");
    await act(
      () => api.keepSwitch(tier),
      () => ({ message: t("queue.switch_failed.keep_toast", { account, work }) }),
    );
    setBusy(null);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.switch_failed.label")}
      data-queue-line="switch_failed"
      pill={<Pill tone="warn">{t("queue.switch_failed.label")}</Pill>}
      title={<>{t("queue.switch_failed", { account, work })}</>}
      meta={line.check_failed ? t("queue.switch_failed.sub_unfinished") : tn("queue.switch_failed.sub", line.count)}
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" loading={busy === "back"} disabled={busy !== null} aria-label={t("queue.switch_failed.back_named", { work, previous })} onClick={() => void back()}>
          {t("queue.switch_failed.back")}
        </Button>
        <Button size="sm" variant="secondary" loading={busy === "keep"} disabled={busy !== null} aria-label={t("queue.switch_failed.keep_named", { account, work })} onClick={() => void keep()}>
          {t("queue.switch_failed.keep")}
        </Button>
              </>
      }
    >
        {names.length > 0 && (
          <ul className={styles.places}>
            {names.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        )}
          </HeldRow>
  );
}

/** An agent account whose sign-in changed (keep the new one, or sign in again), or whose sign-in isn't set for the level of
 * the work waiting on it (open the account). Work above open material waits until the person answers. */
function IdentityLine(props: { line: Line; onOpenAiAccounts: () => void }) {
  const { t, tn } = useWords();
  const act = useAct();
  const [busy, setBusy] = useState(false);
  const nameOf = useAccountNames();
  const { line } = props;
  const account = nameOf(line.account ?? "");
  const identity = line.text ?? "";
  if (line.state === "level") {
    const levels = (line.names ?? []).map((level) => t(`changes.level.${level}`)).join(", ");
    return (
      <HeldRow
        as="section"
        aria-label={t("queue.identity.label")}
        data-queue-line="identity"
        pill={<Pill tone="warn">{t("queue.identity.label")}</Pill>}
        title={<>{t(identity ? "queue.identity.level" : "queue.identity.level_unknown", { account, identity, levels })}</>}
        meta={tn("queue.identity.level.sub", line.count)}
        primary={
          <>
          <Button size="sm" variant="primary" data-key="primary" aria-label={t("queue.identity.open_named", { account })} onClick={props.onOpenAiAccounts}>
            {t("queue.identity.open")}
          </Button>
                  </>
        }
      />
    );
  }
  const keep = async () => {
    setBusy(true);
    await act(
      () => api.keepIdentity(line.account ?? ""),
      () => ({ message: t("queue.identity.keep_toast", { account, identity }) }),
    );
    setBusy(false);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.identity.label")}
      data-queue-line="identity"
      pill={<Pill tone="warn">{t("queue.identity.label")}</Pill>}
      title={<>{t("queue.identity", { account, identity })}</>}
      meta={t("queue.identity.sub")}
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" disabled={busy} aria-label={t("queue.identity.sign_in_named", { account })} onClick={props.onOpenAiAccounts}>
          {t("queue.identity.sign_in")}
        </Button>
        <Button size="sm" variant="secondary" loading={busy} disabled={busy} aria-label={t("queue.identity.keep_named", { account, identity })} onClick={() => void keep()}>
          {t("queue.identity.keep")}
        </Button>
              </>
      }
    />
  );
}

/** An account the person said Not now about reading their work mail and notes: one line with Allow, which gives the yes as one
 * settings change with Undo. Allow changes what the account may read, not the assistant's output, so it has no signal. */
function WorkAccessLine(props: { line: Line }) {
  const { t } = useWords();
  const actSaved = useActSaved();
  const fingerprint = useFreshFingerprint();
  const [busy, setBusy] = useState(false);
  const nameOf = useAccountNames();
  const account = nameOf(props.line.account ?? "");
  const allow = async () => {
    setBusy(true);
    await actSaved(
      async () => inOrder(async () => api.allowWork(props.line.account ?? "", await fingerprint())),
      (saved) => saved,
      () => ({ message: t("queue.work_access.toast", { account }) }),
    );
    setBusy(false);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.work_access.label")}
      data-queue-line="work_access"
      pill={<Pill tone="neutral">{t("queue.work_access.label")}</Pill>}
      title={<>{t("queue.work_access", { account })}</>}
      meta={t("queue.work_access.sub")}
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" loading={busy} disabled={busy} aria-label={t("queue.work_access.allow_named", { account })} onClick={() => void allow()}>
          {t("queue.work_access.allow")}
        </Button>
              </>
      }
    />
  );
}

/** A connected mailbox that reads no sent folder: the one button opens where the mailbox's folders are chosen, and the
 * menu ends the line for good. The line goes by itself once a sent folder is read. */
function SentFolderLine(props: { line: Line; onOpen?: () => void }) {
  const { t, tn } = useWords();
  const act = useAct();
  const { line } = props;
  const sources = line.count > 1 && (line.sources ?? []).length ? line.sources ?? [] : [line.source ?? ""];
  const many = sources.length > 1;
  const names = line.names ?? [];
  const account = many ? (names[0] ?? "") : (line.subject ?? "");
  const dismiss = () =>
    void act(
      async () => {
        let last: S["Ok"] | undefined;
        for (const source of sources) last = await api.dismissSentFolder(source);
        return last;
      },
      () => ({
        message: many ? t("queue.sent_folder.dismissed_all") : t("queue.sent_folder.dismissed", { account }),
        undo: async () => {
          for (const source of sources) await api.dismissSentFolderUndo(source);
        },
      }),
    );
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.sent_folder.label")}
      data-queue-line="sent_folder"
      pill={<Pill tone="neutral">{t("queue.sent_folder.label")}</Pill>}
      title={many ? tn("queue.sent_folder.many", sources.length) : t("queue.sent_folder", { account })}
      meta={many ? <span title={names.join(", ")}>{t("queue.sent_folder.many_sub")}</span> : t("queue.sent_folder.sub")}
      primary={
        props.onOpen && (
          <Button size="sm" variant="primary" data-key="primary" aria-label={t("queue.sent_folder.open_named", { account })} onClick={props.onOpen}>
            {t("queue.sent_folder.open")}
          </Button>
        )
      }
      menu={
        <MenuButton
          groups={[{ id: "sent-folder", entries: [{ id: "dismiss", label: many ? t("queue.sent_folder.dismiss_all") : t("queue.sent_folder.dismiss"), note: t("queue.sent_folder.dismiss_note"), run: dismiss }] }]}
          trigger={<IconButton icon="more" size="sm" label={t("menu.more", { what: t("queue.sent_folder.what") })} tooltip={false} />}
        />
      }
    />
  );
}

/** A folder made under the product's earlier name, offered a rename once. Rename is the person's own change (the backup
 * folder is renamed at once, the workspace folder the next time the app starts); Keep ends the offer for good. */
function FolderRenameLine(props: { line: Line }) {
  const { t } = useWords();
  const act = useAct();
  const afterSave = useAfterSave();
  const fingerprint = useFreshFingerprint();
  const [busy, setBusy] = useState(false);
  const { line } = props;
  const which = line.state ?? "";
  const old = line.subject ?? "";
  const next = line.text ?? "";
  const app = t("app.name");
  const rename = async () => {
    setBusy(true);
    const done = await act(
      async () => inOrder(async () => api.renameFolder(which, await fingerprint())),
      () => (which === "workspace" ? { message: t("queue.folder_rename.renamed_later", { new: next, app }), undo: () => api.renameFolderUndo() } : { message: t("queue.folder_rename.renamed", { new: next }) }),
    );
    if (done?.saved) await afterSave(done.saved, { message: t("queue.folder_rename.renamed", { new: next }), quiet: true });
    setBusy(false);
  };
  const keep = () =>
    void act(
      () => api.keepFolderName(which),
      () => ({ message: t("queue.folder_rename.kept", { old }), undo: () => api.keepFolderNameUndo(which) }),
    );
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.folder_rename.label")}
      data-queue-line="folder_rename"
      pill={<Pill tone="neutral">{t("queue.folder_rename.label")}</Pill>}
      title={t("queue.folder_rename", { old, new: next })}
      meta={t(which === "workspace" ? "queue.folder_rename.workspace.sub" : "queue.folder_rename.backups.sub", { app })}
      primary={
        <>
          <Button size="sm" variant="primary" data-key="primary" loading={busy} disabled={busy} aria-label={t("queue.folder_rename.rename_named", { old, new: next })} onClick={() => void rename()}>
            {t("queue.folder_rename.rename")}
          </Button>
          <Button size="sm" variant="secondary" disabled={busy} aria-label={t("queue.folder_rename.keep_named", { old })} onClick={keep}>
            {t("queue.folder_rename.keep")}
          </Button>
        </>
      }
    />
  );
}

/** A newer version of the app is ready: its date, up to five lines of what changed, and three choices (Update and restart,
 * Later, and Everything that changed, which opens the release's page in the person's own browser). Later hides that
 * version until a newer one comes. */
function UpdateLine(props: { line: Line }) {
  const { t } = useWords();
  const act = useAct();
  const [busy, setBusy] = useState<"install" | "later" | null>(null);
  const { line } = props;
  const version = line.subject ?? "";
  const app = t("app.name");
  const page = line.text ?? "";
  const domain = page ? domainOf(page) : null;
  const when = line.at ? day(line.at) : "";
  // A copy that isn't the installed app can't update itself: it points to the page and offers Later.
  const canInstall = line.state !== "manual";
  const install = async () => {
    setBusy("install");
    await act(() => api.updateInstall(version));
    setBusy(null);
  };
  const later = async () => {
    setBusy("later");
    await act(
      () => api.updateLater(version),
      () => ({ message: t("queue.update.later_toast", { version }), undo: () => api.updateLaterUndo(version) }),
    );
    setBusy(null);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.update.label")}
      data-queue-line="update"
      pill={<Pill tone="neutral">{t("queue.update.label")}</Pill>}
      title={t("queue.update", { app, version })}
      metaLines={[when ? t("queue.update.sub", { when }) : null, ...(line.names ?? []).slice(0, 5)]}
      primary={
        <>
          {canInstall ? (
            <Button size="sm" variant="primary" data-key="primary" loading={busy === "install"} disabled={busy !== null} aria-label={t("queue.update.install_named", { app, version })} onClick={() => void install()}>
              {t("queue.update.install")}
            </Button>
          ) : null}
          <Button size="sm" variant={canInstall ? "secondary" : "primary"} loading={busy === "later"} disabled={busy !== null} aria-label={t("queue.update.later_named", { version })} onClick={() => void later()}>
            {t("queue.update.later")}
          </Button>
          {domain ? (
            <ButtonLink size="sm" variant="quiet" href={page} target="_blank" rel="noopener noreferrer" aria-label={`${t("queue.update.changes_named", { version })}, ${t("queue.update.opens", { domain })}`}>
              {t("queue.update.changes")} <Icon name="external" size={14} />
            </ButtonLink>
          ) : null}
        </>
      }
    />
  );
}

/** The app was updated: the version it is now, up to five lines of what changed and a link to everything that changed,
 * shown until the person has seen it (Got it). */
function UpdatedLine(props: { line: Line }) {
  const { t } = useWords();
  const act = useAct();
  const [busy, setBusy] = useState(false);
  const { line } = props;
  const version = line.subject ?? "";
  const page = line.text ?? "";
  const domain = page ? domainOf(page) : null;
  const seen = async () => {
    setBusy(true);
    await act(() => api.updateSeen());
    setBusy(false);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.updated.label")}
      data-queue-line="updated"
      pill={<Pill tone="neutral">{t("queue.updated.label")}</Pill>}
      title={t("queue.updated", { version })}
      metaLines={(line.names ?? []).slice(0, 5)}
      primary={
        <>
          <Button size="sm" variant="primary" data-key="primary" loading={busy} disabled={busy} aria-label={t("queue.updated.seen_named", { version })} onClick={() => void seen()}>
            {t("queue.updated.seen")}
          </Button>
          {domain ? (
            <ButtonLink size="sm" variant="quiet" href={page} target="_blank" rel="noopener noreferrer" aria-label={`${t("queue.updated.changes_named", { version })}, ${t("queue.update.opens", { domain })}`}>
              {t("queue.updated.changes")} <Icon name="external" size={14} />
            </ButtonLink>
          ) : null}
        </>
      }
    />
  );
}

/** A kind of file that isn't being read: it says which and why. It has no button; it goes once a file of that kind reads
 * well. */
function ExtractorLine(props: { line: Line }) {
  const { t, has } = useWords();
  const { line } = props;
  const kind = line.file_kind ?? "";
  const named = has(`queue.extractor.kind.${kind}`) ? t(`queue.extractor.kind.${kind}`) : kind;
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.extractor.label")}
      data-queue-line="extractor"
      pill={<Pill tone="warn">{t("queue.extractor.label")}</Pill>}
      title={<>{t("queue.extractor", { kind: named, reason: line.text ?? "" })}</>}
      meta={t("queue.extractor.sub")}
    />
  );
}

/** A source that has failed for longer than its usual gap: what to do about it, since when it hasn't been read, and why;
 * one button, to the screen where it is signed in again or changed. It goes once the source is read again. */
function SourceUnreadLine(props: { line: Line; onOpen?: () => void }) {
  const { t, tn, has } = useWords();
  const { line } = props;
  const old = line.problem_kind === "old_data" && !!line.days_old;
  const kind = `queue.source_unread.${line.problem_kind ?? ""}`;
  const key = line.problem_kind && has(kind) ? kind : "queue.source_unread.other";
  const since = line.waiting_since ? whenWords(line.waiting_since, new Date(), t, true) : "";
  // The line never says an address, or part of one: an account's name is its connection's own wording, else its service.
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  const source = (watch.data ?? []).find((s) => s.id === line.source);
  const named = withoutAddress(line.subject ?? "", source?.account) || (source?.connector_label ?? "") || t("account_today.fallback");
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.source_unread.label")}
      data-queue-line="source_unread"
      state="warn"
      title={<>{old ? tn("queue.source_unread.old_data", line.days_old ?? 0, { label: named }) : t(key, { label: named, when: since })}</>}
      meta={<StateMark tone="warn">{t("queue.source_unread.label")}</StateMark>}
      primary={props.onOpen ? (
          <>
          <Button size="sm" variant="primary" data-key="primary" onClick={props.onOpen}>
            {t("queue.source_unread.open")}
          </Button>
          </>
        ) : undefined
      }
    >
        {line.text && <p className="hint">{line.text}</p>}
          </HeldRow>
  );
}

/** A main screen that has been slow to open three times in a row (design 6.13): what to check and how long it took, and
 * one button that drafts a report for the maintainers. The report is shown to be read and copied; nothing is sent from
 * here. The line goes once three loads of the screen are fast again. */
function SlowScreenLine(props: { line: Line }) {
  const { t, has } = useWords();
  const { line } = props;
  const screen = line.subject ?? "";
  const named = has(`slow_screen.name.${screen}`) ? t(`slow_screen.name.${screen}`) : screen;
  const [report, setReport] = useState<{ title: string; text: string } | null>(null);
  const [failed, setFailed] = useState(false);
  const draft = async () => {
    setFailed(false);
    try {
      setReport(await api.slowScreenReport(screen));
    } catch {
      setFailed(true);
    }
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.slow_screen.label")}
      data-queue-line="slow_screen"
      state="warn"
      title={<>{t("queue.slow_screen", { screen: named, seconds: (line.seconds ?? 0).toFixed(1) })}</>}
      meta={<StateMark tone="warn">{t("queue.slow_screen.label")}</StateMark>}
      primary={
        <Button size="sm" variant="primary" data-key="primary" onClick={draft}>
          {t("queue.slow_screen.open")}
        </Button>
      }
    >
      {failed && <p className="hint" role="alert">{t("queue.slow_screen.failed")}</p>}
      {report && (
        <div>
          <p className="hint">{t("queue.slow_screen.draft")}</p>
          <textarea readOnly aria-label={report.title} value={`${report.title}\n\n${report.text}`} rows={6} style={{ width: "100%" }} />
          <Button size="sm" onClick={() => void navigator.clipboard?.writeText(`${report.title}\n\n${report.text}`)}>
            {t("queue.slow_screen.copy")}
          </Button>
        </div>
      )}
    </HeldRow>
  );
}

/** The learning runs for the corrections made before the assistant could learn from them, held together for one go: the
 * count and what they would cost together, and the one Go that starts them all. */
function CatchUpGoLine(props: { line: Line }) {
  const { t, tn } = useWords();
  const act = useAct();
  const estimate = useEstimate();
  const [busy, setBusy] = useState(false);
  const { line } = props;
  const cost = line.estimate_usd == null ? null : estimate(line.estimate_usd);
  const text =
    cost === null
      ? tn("queue.catch_up_go.unpriced", line.count)
      : line.unpriced > 0
        ? tn("queue.catch_up_go.mixed", line.count, { cost })
        : tn("queue.catch_up_go.priced", line.count, { cost });
  const go = async () => {
    setBusy(true);
    await act(api.catchUpGo, () => ({ message: t("queue.catch_up_go.started") }));
    setBusy(false);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.catch_up_go.label")}
      data-queue-line="catch_up_go"
      pill={<Pill tone="warn">{t("queue.catch_up_go.label")}</Pill>}
      title={text}
      meta={t("queue.catch_up_go.sub")}
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" loading={busy} onClick={() => void go()}>
          {t("queue.catch_up_go.run")}
        </Button>
              </>
      }
    />
  );
}

/** A newly added source taken in quietly, held for one go: how many items (from how many days of mail, when it has mail),
 * what they would cost together, and the one Go that starts them all. */
function IntakeGoLine(props: { line: Line }) {
  const { t, tn } = useWords();
  const act = useAct();
  const estimate = useEstimate();
  const money = useMoney();
  const [busy, setBusy] = useState(false);
  const { line } = props;
  const source = line.subject ?? line.source ?? "";
  const text =
    line.days != null
      ? tn("queue.intake_go.mail", line.count, { source, since: tn("queue.intake_go.days", line.days) })
      : tn("queue.intake_go.items", line.count, { source });
  const cost = line.estimate_usd == null ? null : estimate(line.estimate_usd);
  const most = atMost({ estimate_usd: line.estimate_usd, estimate_max_usd: line.estimate_max_usd }, money);
  const kind = line.unpriced > 0 ? "mixed" : "priced";
  const sub = t(cost === null ? "queue.intake_go.cost.unpriced" : most !== null ? `queue.intake_go.cost.${kind}_max` : `queue.intake_go.cost.${kind}`, { cost: cost ?? "", most: most ?? "" });
  const go = async () => {
    setBusy(true);
    await act(
      () => api.intakeGo(line.source ?? ""),
      () => ({ message: t("queue.intake_go.started", { source }) }),
    );
    setBusy(false);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.intake_go.label")}
      data-queue-line="intake_go"
      pill={<Pill tone="warn">{t("queue.intake_go.label")}</Pill>}
      title={text}
      meta={sub}
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" loading={busy} onClick={() => void go()}>
          {t("queue.intake_go.run")}
        </Button>
              </>
      }
    />
  );
}

/** A read of a source's older mail that stopped and ran out of tries: the one button reads the rest from where it stopped,
 * now. Nothing is hidden: what was taken in already is said. */
function OlderReadLine(props: { line: Line }) {
  const { t, tn } = useWords();
  const act = useAct();
  const [busy, setBusy] = useState(false);
  const { line } = props;
  const source = line.subject ?? line.source ?? "";
  const go = async () => {
    setBusy(true);
    await act(
      () => api.continueOlderRead(line.source ?? ""),
      () => ({ message: t("queue.older_read.started", { source }) }),
    );
    setBusy(false);
  };
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.older_read.label")}
      data-queue-line="older_read"
      pill={<Pill tone="warn">{t("queue.older_read.label")}</Pill>}
      title={t("queue.older_read.title", { source })}
      meta={tn("queue.older_read.sub", line.count, {})}
      primary={
        <Button size="sm" variant="primary" data-key="primary" loading={busy} onClick={() => void go()}>
          {t("queue.older_read.run")}
        </Button>
      }
    />
  );
}

/** The standing rules given to runs and never shown applying: the line opens the review, and "Not now" puts it off for
 * its week without deciding anything. */
function RuleReviewLine(props: { line: Line; onOpen?: () => void; onOpenKnowledge?: () => void }) {
  const { t, tn } = useWords();
  const act = useAct();
  const { line } = props;
  const text = line.count > 0 ? tn("queue.rule_review", line.count, { days: line.days ?? "" }) : t("queue.rule_review.moved");
  // Not now puts the line off; it doesn't answer it, so it is in the menu with what it does, not a button beside the answer.
  const notNow = () =>
    void act(api.ruleReviewNotNow, (put) => ({
      message: t("queue.rule_review.not_now_done", { day: day(put.until) }),
      undo: () => api.ruleReviewNotNowUndo(put.signal),
    }));
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.rule_review.label")}
      data-queue-line="rule_review"
      pill={<Pill tone="neutral">{t("queue.rule_review.label")}</Pill>}
      title={text}
      meta={t("queue.rule_review.sub")}
      primary={
        props.onOpen && (
          <Button size="sm" variant="primary" data-key="primary" onClick={props.onOpen}>
            {t("queue.rule_review.open")}
          </Button>
        )
      }
      menu={
        <MenuButton
          groups={[
            {
              id: "rule-review",
              entries: [
                {
                  id: "not-now",
                  label: t("queue.rule_review.not_now"),
                  note: line.until ? t("queue.rule_review.not_now_back", { day: day(line.until) }) : undefined,
                  run: notNow,
                },
                ...(props.onOpenKnowledge ? [{ id: "knowledge", label: t("queue.rule_review.open_knowledge"), run: props.onOpenKnowledge }] : []),
              ],
            },
          ]}
          trigger={<IconButton icon="more" size="sm" label={t("menu.more", { what: t("queue.rule_review.label") })} tooltip={false} />}
        />
      }
    />
  );
}

/** A tier an add-on declared for its own work that the person hasn't mapped: its work uses the core's kind of work it
 * named meanwhile, which the line says. Nothing is chosen for the person; the one button opens where they choose. */
function PackTierLine(props: { line: Line; onOpen: () => void }) {
  const { t } = useWords();
  const tierName = useTierName();
  const { line } = props;
  return (
    <HeldRow
      as="section"
      aria-label={t("queue.pack_tier.label")}
      data-queue-line="pack_tier"
      pill={<Pill tone="neutral">{t("queue.pack_tier.label")}</Pill>}
      title={<>{t("queue.pack_tier", { subject: line.subject ?? "", fallback: tierName(line.text ?? "routine") })}</>}
      meta={t("queue.pack_tier.sub")}
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" onClick={props.onOpen}>
          {t("queue.pack_tier.open")}
        </Button>
              </>
      }
    />
  );
}

/** Work with no AI account at all: it waits until one is added, so the line says so and offers the one step that fixes it. */
function NoAccountLine(props: { line: Line; onAdd: () => void }) {
  const { t } = useWords();
  return (
    <HeldRow
      as="section"
      aria-label={t(props.line.group === "risk" ? "queue.no_account.stopped_label" : "queue.no_account.label")}
      data-queue-line="no_account"
      pill={<Pill tone={props.line.group === "risk" ? "danger" : "warn"}>{t(props.line.group === "risk" ? "queue.no_account.stopped_label" : "queue.no_account.label")}</Pill>}
      // An assistant that worked and then lost its account has stopped; one that never had an account is a gap in setup.
      title={t(props.line.group === "risk" ? "queue.no_account.stopped" : "queue.no_account")}
      meta={t("queue.no_account.sub")}
      keepActions
      primary={
        <>
        <Button size="sm" variant="primary" data-key="primary" onClick={props.onAdd}>
          {t("queue.no_account.open")}
        </Button>
              </>
      }
    />
  );
}
