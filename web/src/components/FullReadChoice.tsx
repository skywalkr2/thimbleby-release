// The question a first sign-in asks on the Mail step (design 6.32): how far back to read mail in full. Each reach shows
// what it would take in and about what it costs; nothing is chosen until the person picks one, "Not now" is one of the
// choices, and nothing is read before they do. The read goes through the look further back, which holds the work for
// the person's go. One compact line inside each account's row, answered for every one of its sources that still has it open.
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { alreadyOut } from "../lib/write";
import { useToasts } from "../lib/toasts";
import { useEstimate, useMoney } from "../lib/money";
import { skippedWords } from "../lib/skipped";
import { onceEach, stopWords } from "../lib/olderRead";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { costWords, headWords } from "./LookBack";
import { Select } from "../ui/Select";
import styles from "./FullReadChoice.module.css";

type Source = S["WatchSourceView"];
type Option = S["FullReadOptionView"];

const NOT_NOW = 0;

/** A reach in the person's words: whole weeks under four, whole months where they divide, else days. */
export function reachWords(days: number, tn: (key: string, n: number) => string): string {
  if (days % 7 === 0 && days < 28) return tn("walkthrough.mail.full_read.weeks", days / 7);
  if (days % 30 === 0) return tn("walkthrough.mail.full_read.months", days / 30);
  return tn("walkthrough.mail.full_read.days", days);
}

/** What one reach would take in and cost, summed over the account's open sources. */
function summed(views: S["FullReadView"][]): Option[] {
  const first = views[0]?.options ?? [];
  return first.map((o, i) => {
    const same = views.map((v) => v.options[i]).filter((x): x is Option => x !== undefined);
    const priced = same.filter((x) => x.estimate_usd != null);
    return {
      days: o.days,
      count: same.reduce((n, x) => n + x.count, 0),
      estimate_usd: priced.length > 0 ? priced.reduce((n, x) => n + (x.estimate_usd ?? 0), 0) : null,
      estimate_max_usd: priced.length > 0 ? priced.reduce((n, x) => n + (x.estimate_max_usd ?? x.estimate_usd ?? 0), 0) : null,
      unpriced: same.reduce((n, x) => n + x.unpriced, 0),
      reaches: same.every((x) => x.reaches),
      capped: same.some((x) => x.capped),
      estimate: same.some((x) => x.estimate),
      unknown: same.some((x) => x.unknown),
    };
  });
}

export function FullReadChoice(props: { sources: Source[]; account: string }) {
  const { t, tn } = useWords();
  const act = useAct();
  const { push } = useToasts();
  const client = useQueryClient();
  const estimate = useEstimate();
  const money = useMoney();
  const open = props.sources.filter((s) => s.full_read_open);
  const [picked, setPicked] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  // The counts are the mail service's to give and cost it requests: asked once for a source's state (its full read answered, started
  // or finished changes the key), never again on window focus or on a change to something else.
  const views = useQueries({
    queries: open.map((s) => ({
      queryKey: ["full-read", s.id, s.looked_back_to ?? null, s.older_read?.at ?? null],
      queryFn: () => api.fullRead(s.id),
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      // When the first read lands the counts are asked: the choices stay on screen meanwhile, with what they said before.
      placeholderData: (previous: S["FullReadView"] | undefined) => previous,
    })),
  });
  if (open.length === 0) return null;
  const ready = views.every((v) => v.data !== undefined);
  const dayStop = ready ? Math.max(...views.map((v) => (v.data as S["FullReadView"]).day_stop_usd ?? 0)) : 0;
  const options = ready ? summed(views.map((v) => v.data as S["FullReadView"])) : [];
  // What the read did for one source, in words: what is being taken in, then what it skipped (nothing is said of skipping when
  // none was), then, when the service gave far fewer than it said it held, how many it gave of how many.
  const readWords = (r: S["LookBackView"], source: string): string => {
    const head = headWords(r, source, t, tn, "walkthrough.mail.full_read.nothing");
    const skipped = skippedWords(r.skipped, tn);
    const short = r.short ? tn(r.expected_estimate ? "walkthrough.mail.full_read.short_about" : "walkthrough.mail.full_read.short", r.gave, { expected: r.expected }) : "";
    return [head, skipped, short, stopWords(r, t)].filter(Boolean).join(" ");
  };
  // Every open source of the account is answered (the inbox, the sent mail, any other), and what they did is said in one line
  // that names each, since a newer message would replace an older one.
  const confirm = async () => {
    if (picked === null) return;
    // A second press while the read is out does nothing: the read goes through once, and its answer is the one shown.
    if (open.some((s) => alreadyOut(client, `full-read:${s.id}`))) return;
    setBusy(true);
    const said: string[] = [];
    // A source that fails does not stop the others: each is answered, the failure is shown by its own toast, and what the others did is said.
    for (const s of open) {
      const done = await act(() => api.answerFullRead(s.id, picked), undefined, undefined, { once: `full-read:${s.id}` });
      if (done !== undefined && picked !== NOT_NOW) said.push(readWords(done, s.label));
    }
    // Sources that did the same say the same words: each line is said once.
    if (said.length > 0) push({ message: onceEach(said).join(" ") });
    setBusy(false);
    await client.invalidateQueries({ queryKey: ["watch"] });
  };
  const label = t("walkthrough.mail.full_read.label");
  return (
    <div className={styles.line} data-full-read="" data-account={props.account}>
      <span className={styles.label}>
        {label}
      </span>
      {!ready ? (
        <span className="hint" role="status">
          {t("walkthrough.mail.full_read.counting")}
        </span>
      ) : (
        <>
          <Select className={styles.pick} aria-label={t("walkthrough.mail.full_read.name", { account: props.account })} value={picked === null ? "" : String(picked)} disabled={busy} onChange={(e) => setPicked(e.target.value === "" ? null : Number(e.target.value))}>
            <option value="">{t("walkthrough.mail.full_read.choose")}</option>
            {options.map((o) => {
              const cost = o.count === 0 ? "" : costWords(o, estimate, t, money, dayStop);
              const found = o.unknown && o.count === 0 ? t("walkthrough.mail.full_read.found_unknown") : o.count === 0 ? t("walkthrough.mail.full_read.covered") : tn(o.capped ? "walkthrough.mail.full_read.found_capped" : o.estimate ? "walkthrough.mail.full_read.found_about" : "walkthrough.mail.full_read.found", o.count, { cost });
              return (
                <option key={o.days} value={String(o.days)}>
                  {reachWords(o.days, tn)}: {found}
                </option>
              );
            })}
            <option value={String(NOT_NOW)}>{t("walkthrough.mail.full_read.not_now")}</option>
          </Select>
          <Button variant="primary" size="sm" disabled={picked === null} loading={busy} onClick={() => void confirm()}>
            {t(picked === NOT_NOW ? "walkthrough.mail.full_read.skip" : "walkthrough.mail.full_read.go")}
          </Button>
        </>
      )}
    </div>
  );
}
