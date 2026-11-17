// The question a first sign-in asks on the Mail step (design 6.32): how far back to read mail in full. Each reach shows
// what it would take in and about what it costs; nothing is chosen until the person picks one, "Not now" is one of the
// choices, and nothing is read before they do. The read goes through the look further back, which holds the work for
// the person's go. One compact line inside each account's row, answered for every one of its sources that still has it open.
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { useEstimate } from "../lib/money";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { costWords } from "./LookBack";
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
      unpriced: same.reduce((n, x) => n + x.unpriced, 0),
      reaches: same.every((x) => x.reaches),
    };
  });
}

export function FullReadChoice(props: { sources: Source[]; account: string }) {
  const { t, tn } = useWords();
  const act = useAct();
  const client = useQueryClient();
  const estimate = useEstimate();
  const open = props.sources.filter((s) => s.full_read_open);
  const [picked, setPicked] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const views = useQueries({ queries: open.map((s) => ({ queryKey: ["full-read", s.id], queryFn: () => api.fullRead(s.id) })) });
  if (open.length === 0) return null;
  const ready = views.every((v) => v.data !== undefined);
  const options = ready ? summed(views.map((v) => v.data as S["FullReadView"])) : [];
  const confirm = async () => {
    if (picked === null) return;
    setBusy(true);
    for (const s of open) {
      const done = await act(
        () => api.answerFullRead(s.id, picked),
        picked === NOT_NOW
          ? undefined
          : (r) => ({
              message: r.taken === 0 ? t("walkthrough.mail.full_read.nothing") : r.started ? tn("coverage.look_back.done", r.taken, { source: s.label }) : t("coverage.look_back.done_held", { source: s.label }),
            }),
      );
      if (done === undefined) break;
    }
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
              const cost = o.count === 0 ? "" : costWords(o, estimate, t);
              const found = o.count === 0 ? t("walkthrough.mail.full_read.covered") : tn("walkthrough.mail.full_read.found", o.count, { cost });
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
