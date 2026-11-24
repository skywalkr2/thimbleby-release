// What an AI account's service actually charged, beside what the app worked out, per UTC day (design 6.16, "What a provider
// actually charged"). On an account's card (with the form that adds the billing key, picks the key the account runs with and
// sets how often the report is read) and, for every account whose report is on, in Settings under AI and spending.
// A day the service hasn't reported shows "not reported yet", never nothing or 0; today says "so far"; a figure the service
// may still revise says so; a report of the whole organization says it includes use outside the app; a report in another
// currency is shown, not compared. The app's own figure is the one that limits and estimates use; this never changes them.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { api, ApiError, type S } from "../lib/api";
import { useAccountActs } from "../lib/ai-account-acts";
import { useAccountNames } from "../lib/account-names";
import { monthDay, todayOn, wallWhen } from "../lib/dates";
import { useMoney, usePrice } from "../lib/money";
import { problemText } from "../lib/problem";
import { useWords } from "../lib/wording";
import { Actions } from "../ui/Actions";
import { Button } from "../ui/Button";
import { FormField } from "../ui/FormField";
import { Select } from "../ui/Select";
import styles from "./AiCosts.module.css";

type Entry = S["AiCostAccount"];

/** How many of the latest days the table shows; the rest stay kept for the gap check. */
export const DAYS_SHOWN = 7;
/** The hours a read can be asked every, besides off. */
export const HOUR_CHOICES = [1, 2, 4, 6, 12, 24];

const todayUtc = () => todayOn(new Date());

/** The side-by-side of one account: each UTC day with what the service charged and what the app worked out. */
export function CostsTable(props: { entry: Entry }) {
  const { t, has } = useWords();
  const money = useMoney();
  const price = usePrice();
  const { entry } = props;
  const days = (entry.days ?? []).slice(0, DAYS_SHOWN);
  const today = todayUtc();
  const other = days.some((d) => d.reported && d.currency && d.currency !== "USD");
  const taskWords = (id: string) => (has(`task.${id}`) ? t(`task.${id}`) : t("task.other"));
  const real = (d: S["AiCostDay"]) => {
    if (!d.reported || d.amount == null) return t("ai_costs.not_reported");
    const text = price(d.amount, d.currency);
    return d.day === today ? t("ai_costs.so_far", { amount: text }) : d.open ? t("ai_costs.may_change", { amount: text }) : text;
  };
  return (
    <div className={styles.block} data-costs={entry.name}>
      {days.length === 0 ? (
        <p className={styles.note}>{t("ai_costs.none_yet")}</p>
      ) : (
        <table className={styles.table}>
          <caption className="sr">{t("ai_costs.caption")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("ai_costs.col.day")}</th>
              <th scope="col">{t("ai_costs.col.charged")}</th>
              <th scope="col">{t("ai_costs.col.worked_out")}</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.day} data-day={d.day}>
                <th scope="row">{t("ai_costs.utc_day", { day: monthDay(d.day) })}</th>
                <td data-gap={d.gap ? "" : undefined}>{real(d)}</td>
                <td>
                  {money(d.app_usd)}
                  {Object.keys(d.by_task ?? {}).length > 1 && (
                    <ul className={styles.split} aria-label={t("ai_costs.split")}>
                      {Object.entries(d.by_task ?? {})
                        .sort((a, b) => b[1] - a[1])
                        .map(([id, usd]) => (
                          <li key={id}>{t("ai_costs.split_row", { work: taskWords(id), amount: money(usd) })}</li>
                        ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {entry.scope === "organization" && <p className={styles.note}>{t("ai_costs.whole_org")}</p>}
      {other && <p className={styles.note}>{t("ai_costs.other_currency")}</p>}
      {entry.partial && <p className={styles.note}>{t("ai_costs.partial")}</p>}
      {entry.failing && <p className={styles.bad}>{t(has(`ai_costs.failing.${entry.failing}`) ? `ai_costs.failing.${entry.failing}` : "ai_costs.failing.other")}</p>}
      {entry.read_at && <p className={styles.note}>{t("ai_costs.read_at", { when: wallWhen(entry.read_at) })}</p>}
      <p className={styles.note}>{t("ai_costs.leaves_out")}</p>
    </div>
  );
}

/** The card's part for one account whose adapter can read its service's report: the table once it is on, and the form that
 * turns it on. Nothing is shown for an account that cannot. */
export function AccountCosts(props: { account: S["AiAccountView"]; local: boolean }) {
  const { t } = useWords();
  const { account, local } = props;
  const costs = useQuery({ queryKey: ["ai-costs"], queryFn: api.aiCosts, enabled: !!account.cost_report_offered });
  const acts = useAccountActs();
  const base = useId();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [keys, setKeys] = useState<S["BillingKeyChoice"][] | null>(null);
  const [keyId, setKeyId] = useState(account.billing_key_id ?? "");
  const [hours, setHours] = useState(account.cost_report_hours || 4);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  // A form the person opened puts the cursor in its first field.
  useEffect(() => {
    if (open) first.current?.focus();
  }, [open]);
  if (!account.cost_report_offered) return null;
  const entry = costs.data?.accounts.find((a) => a.name === account.name);
  const on = (account.cost_report_hours ?? 0) > 0;
  const haveKey = account.billing_key_state === "saved";
  const body = () => (key.trim() ? (local ? { key: key.trim() } : { key_ref: key.trim() }) : {});

  const show = () => {
    setProblem("");
    setKey("");
    setKeys(null);
    setKeyId(account.billing_key_id ?? "");
    setHours(account.cost_report_hours || 4);
    setOpen(true);
  };
  const findKeys = async () => {
    setBusy(true);
    setProblem("");
    try {
      const found = await api.billingKeys(account.name, body());
      if (found.problem) setProblem(found.problem);
      setKeys(found.keys ?? []);
    } catch (err) {
      setProblem(err instanceof ApiError && err.detail ? err.detail : problemText(err, t));
    } finally {
      setBusy(false);
    }
  };
  const submit = async (nextHours: number) => {
    setBusy(true);
    setProblem("");
    try {
      await acts.save(
        (fingerprint) => api.changeBilling(account.name, { fingerprint, ...body(), key_id: keys ? keyId : undefined, hours: nextHours }),
        t(nextHours ? "ai_costs.saved_on" : "ai_costs.saved_off"),
      );
      setOpen(false);
    } catch (err) {
      setProblem(err instanceof ApiError && err.detail ? err.detail : problemText(err, t));
    } finally {
      setBusy(false);
    }
  };
  const canSave = !busy && (haveKey || key.trim() !== "");
  return (
    <section className={styles.block} aria-label={t("ai_costs.title")} data-account-costs={account.name}>
      <p className={styles.title}>{t("ai_costs.title")}</p>
      {on && entry ? <CostsTable entry={entry} /> : <p className={styles.note}>{t(on ? "ai_costs.none_yet" : "ai_costs.off")}</p>}
      {!open && (
        <Actions align="start">
          <Button size="sm" onClick={show} aria-label={t(on ? "ai_costs.change_named" : "ai_costs.set_up_named", { account: account.label || account.name })}>
            {t(on ? "ai_costs.change" : "ai_costs.set_up")}
          </Button>
          {on && (
            <Button size="sm" variant="quiet" disabled={busy} onClick={() => void submit(0)}>
              {t("ai_costs.turn_off")}
            </Button>
          )}
        </Actions>
      )}
      {open && (
        <form
          className={styles.form}
          onSubmit={(e) => {
            e.preventDefault();
            void submit(hours);
          }}
        >
          <p className={styles.note}>{t("ai_costs.intro")}</p>
          <FormField id={`${base}-key`} label={t(local ? "ai_costs.key" : "ai_costs.key_where")} hint={t(haveKey ? "ai_costs.key_hint_saved" : "ai_costs.key_hint")}>
            <input
              id={`${base}-key`}
              ref={first}
              type={local ? "password" : "text"}
              value={key}
              autoComplete="off"
              spellCheck={false}
              placeholder={local ? undefined : "env:NAME"}
              onChange={(e) => {
                setKey(e.target.value);
                setKeys(null);
              }}
            />
          </FormField>
          <Actions align="start">
            <Button size="sm" disabled={!canSave} onClick={() => void findKeys()}>
              {t("ai_costs.find_keys")}
            </Button>
          </Actions>
          {keys && keys.length > 0 && (
            <FormField id={`${base}-which`} label={t("ai_costs.which_key")} hint={t("ai_costs.which_key_hint")}>
              <Select id={`${base}-which`} value={keyId} onChange={(e) => setKeyId(e.target.value)}>
                <option value="">{t("ai_costs.all_keys")}</option>
                {keys.map((k) => (
                  <option key={k.id} value={k.id}>
                    {t("ai_costs.key_choice", { name: k.name || t("ai_costs.key_unnamed"), hint: k.hint })}
                  </option>
                ))}
              </Select>
            </FormField>
          )}
          <FormField id={`${base}-hours`} label={t("ai_costs.hours")} hint={t("ai_costs.hours_hint")}>
            <Select id={`${base}-hours`} value={String(hours)} onChange={(e) => setHours(Number(e.target.value))}>
              {HOUR_CHOICES.map((h) => (
                <option key={h} value={String(h)}>
                  {t("ai_costs.every_hours", { n: h })}
                </option>
              ))}
            </Select>
          </FormField>
          {problem && (
            <p className={styles.bad} role="alert">
              {problem}
            </p>
          )}
          <Actions align="end">
            <Button variant="quiet" disabled={busy} onClick={() => setOpen(false)}>
              {t("ai_accounts.cancel")}
            </Button>
            <Button variant="primary" type="submit" disabled={!canSave}>
              {t(busy ? "ai_accounts.saving" : "ai_accounts.save")}
            </Button>
          </Actions>
        </form>
      )}
    </section>
  );
}

/** Settings under AI and spending: every account whose report is on, each with its side-by-side. Nothing at all when none is. */
export function AiCostsSpending() {
  const { t } = useWords();
  const nameOf = useAccountNames();
  const costs = useQuery({ queryKey: ["ai-costs"], queryFn: api.aiCosts });
  const list = costs.data?.accounts ?? [];
  if (list.length === 0) return null;
  return (
    <section className="settings-group" aria-labelledby="ai-costs-title" data-ai-costs="">
      <h3 id="ai-costs-title">{t("ai_costs.section")}</h3>
      <p className="hint">{t("ai_costs.section_hint")}</p>
      {list.map((entry) => (
        <div key={entry.name}>
          <h4>{nameOf(entry.name)}</h4>
          <CostsTable entry={entry} />
        </div>
      ))}
    </section>
  );
}
