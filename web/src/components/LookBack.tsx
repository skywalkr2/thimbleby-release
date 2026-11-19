// Looking further back in a mail source (design 6.32): the person picks how many more days from a list, sees how many items
// that is and about what it costs, and confirms; nothing is read before. The older mail is taken in the same quiet way as the
// source's first read. When the source holds no mail that far back the answer says where its mail starts.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { day } from "../lib/dates";
import { useEstimate, useMoney } from "../lib/money";
import { skippedWords } from "../lib/skipped";
import { stopWords } from "../lib/olderRead";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import styles from "./Today.module.css";
import { Select } from "../ui/Select";

type Source = S["WatchSourceView"];

/** The look further back for one source: a list of days, what it would take in and cost, and the button that does it. */
export function LookBack(props: { source: Source; onClose: () => void }) {
  const { t, tn } = useWords();
  const act = useAct();
  const estimate = useEstimate();
  const money = useMoney();
  const { source } = props;
  const base = useId();
  const field = useRef<HTMLButtonElement>(null);
  const [days, setDays] = useState(0);
  const [busy, setBusy] = useState(false);
  // The cursor goes to the list when the form opens.
  useEffect(() => field.current?.focus(), []);
  const preview = useQuery({
    queryKey: ["look-back", source.id, days],
    queryFn: () => api.lookBackPreview(source.id, days),
    enabled: days > 0,
  });
  const found = preview.data;
  const cost = found ? costWords(found, estimate, t, money) : "";
  const confirm = async () => {
    setBusy(true);
    const done = await act(
      () => api.lookBack(source.id, days),
      (result) => ({ message: doneWords(result, source.label, t, tn) }),
    );
    setBusy(false);
    if (done) props.onClose();
  };
  return (
    <div className={styles.lookBack} role="group" aria-label={t("coverage.look_back.label", { label: source.label })} data-look-back="">
      <label htmlFor={`${base}-days`}>{t("coverage.look_back.days")}</label>
      <Select id={`${base}-days`} ref={field} value={days} onChange={(e) => setDays(Number(e.target.value))}>
        <option value={0}>{t("coverage.look_back.choose")}</option>
        {(source.look_back_choices ?? []).map((n) => (
          <option key={n} value={n}>
            {t("coverage.look_back.choice", { n })}
          </option>
        ))}
      </Select>
      <p className={styles.lookBackFound} role="status">
        {days === 0
          ? ""
          : preview.isPending
            ? t("coverage.look_back.counting")
            : found && found.count === 0
              ? t("coverage.look_back.none")
              : found
                ? tn(found.capped ? "coverage.look_back.found_capped" : found.estimate ? "coverage.look_back.found_about" : "coverage.look_back.found", found.count, { from: day(found.from_date), cost })
                : ""}
        {found && !found.reaches && found.available_from ? ` ${t("coverage.look_back.only_from", { date: day(found.available_from) })}` : ""}
      </p>
      <div className={styles.lookBackActions}>
        <Button size="sm" variant="primary" disabled={!found || found.count === 0} loading={busy} onClick={() => void confirm()}>
          {t("coverage.look_back.confirm")}
        </Button>
        <Button size="sm" variant="quiet" onClick={props.onClose}>
          {t("coverage.look_back.cancel")}
        </Button>
      </div>
    </div>
  );
}

type T = (key: string, vars?: Record<string, string | number>) => string;

/** The ceiling beside an estimate: "at most $5.20", only when it is more than the estimate at the cent and the count is
 * not itself "at least". Null when there is nothing to add. */
export function atMost(
  found: { estimate_usd?: number | null; estimate_max_usd?: number | null; capped?: boolean },
  money: ((usd: number) => string) | undefined,
): string | null {
  if (!money || found.capped || found.estimate_usd == null || found.estimate_max_usd == null) return null;
  const most = money(found.estimate_max_usd);
  return most === money(found.estimate_usd) || found.estimate_max_usd <= found.estimate_usd ? null : most;
}

/** What the items would cost, in words: the estimate and, when it is more, the most it could be ("About $1.40 in all, at
 * most $5.20."), the plan's allowance, or both. `money` writes the ceiling; without it only the estimate shows. */
export function costWords(
  found: Pick<S["LookBackView"], "estimate_usd" | "unpriced"> & { estimate_max_usd?: number | null; capped?: boolean },
  estimate: (usd: number | null | undefined) => string | null,
  t: T,
  money?: (usd: number) => string,
  dayStop?: number,
): string {
  const amount = estimate(found.estimate_usd);
  if (amount === null) return t("coverage.look_back.cost.unpriced");
  const kind = found.unpriced > 0 ? "mixed" : "priced";
  const most = atMost(found, money);
  if (most !== null && money && dayStop && dayStop > 0 && found.estimate_max_usd != null && found.estimate_max_usd > dayStop) {
    return t(`coverage.look_back.cost.${kind}_max_day`, { cost: amount, most, stop: money(dayStop) });
  }
  if (most !== null) return t(`coverage.look_back.cost.${kind}_max`, { cost: amount, most });
  return t(`coverage.look_back.cost.${kind}${found.capped ? "_capped" : ""}`, { cost: amount });
}

/** What the look did: how many older items are being taken in, or that they wait for the go, and where the mail starts when
 * the source didn't reach as far as asked. */
/** The first words of what a look did: how many older items are taken in (and, when the assistant's reading of them waits for the go on
 * Today, that), or that there was nothing, or nothing when the read stopped before taking any in. `none` is the key said for nothing. */
export function headWords(done: S["LookBackView"], label: string, t: T, tn: (key: string, n: number, vars?: Record<string, string | number>) => string, none = "coverage.look_back.none"): string {
  if (done.taken === 0) return done.stopped ? "" : t(none);
  return tn(done.started ? "coverage.look_back.done" : "coverage.look_back.done_held", done.taken, { source: label });
}

export function doneWords(done: S["LookBackView"], label: string, t: T, tn: (key: string, n: number, vars?: Record<string, string | number>) => string): string {
  const parts = [headWords(done, label, t, tn)];
  if (!done.reaches && done.available_from) parts.push(t("coverage.look_back.only_from", { date: day(done.available_from) }));
  const skipped = skippedWords(done.skipped, tn);
  if (skipped) parts.push(skipped);
  if (done.short) parts.push(tn(done.expected_estimate ? "walkthrough.mail.full_read.short_about" : "walkthrough.mail.full_read.short", done.gave, { expected: done.expected }));
  const stop = stopWords(done, t);
  if (stop) parts.push(stop);
  return parts.filter(Boolean).join(" ");
}
