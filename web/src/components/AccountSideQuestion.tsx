// "What is this account for?" under one account on setup's mail step (design 6.32, 7.8): a list of the person's sides, and Both (or
// Every side), to pick from. The pick is saved at once as the `sides` of each of the account's sources, the record the tick boxes
// on Connections write too, and the mail already read moves with it. It is asked only when there is a side beside Personal. Leaving it
// unanswered is only through the step's own Skip: the account then stays not assigned.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, type S } from "../lib/api";
import { SOURCES, setSourceSides } from "../lib/source-sides";
import { useAfterSave } from "../lib/settings-save";
import { useWords } from "../lib/wording";
import { CheckboxGroup } from "../ui/CheckboxGroup";
import styles from "./SetupAccountRow.module.css";

type Source = S["WatchSourceView"];

const EVERY = "__every__";

/** Whether an account's sources have a side said (one that still exists). */
export function accountAnswered(sources: Source[], sideIds: string[]): boolean {
  return sources.every((s) => (s.sides ?? []).some((id) => sideIds.includes(id)));
}

export function AccountSideQuestion(props: { sources: Source[]; account: string; /** The person chose to say it later: the account is shown as not assigned. */ later?: boolean; personal: string | null; sides: S["SideView"][] }) {
  const { t } = useWords();
  const client = useQueryClient();
  const afterSave = useAfterSave();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [wanted, setWanted] = useState<string | null>(null);
  const [problem, setProblem] = useState("");
  const options = [...(props.personal ? [{ id: props.personal, name: t("sides.filter.personal") }] : []), ...props.sides.map((s) => ({ id: s.project, name: s.name }))];
  const order = options.map((o) => o.id);
  const mine = props.sources.map((s) => s.id);
  const stored = (settings.data?.items.find((i) => i.key === SOURCES)?.value ?? []) as Array<{ id: string; sides?: string[] }>;
  const held = (id: string) => (stored.find((s) => s.id === id)?.sides ?? []).filter((side) => order.includes(side));
  // What the sources hold now, as one pick: a side, every side, or none when they hold nothing or a mix this question doesn't offer.
  const picked = (() => {
    const first = held(mine[0] ?? "");
    const same = mine.every((id) => [...held(id)].sort().join("|") === [...first].sort().join("|"));
    if (!same || first.length === 0) return null;
    if (first.length === order.length && order.length > 1) return EVERY;
    return first.length === 1 ? first[0] : null;
  })();
  const shown = wanted ?? picked;
  const choose = async (value: string) => {
    setProblem("");
    setWanted(value);
    try {
      const saved = await setSourceSides(client, mine, value === EVERY ? order : [value], order);
      await afterSave(saved, { quiet: true });
    } catch (err) {
      setProblem(err instanceof ApiError && err.detail && err.status < 500 ? err.detail : t("walkthrough.mail.account_for.failed", { account: props.account }));
    }
    setWanted(null);
  };
  const choices = [...options.map((o) => ({ value: o.id, title: o.name })), { value: EVERY, title: t(options.length === 2 ? "walkthrough.mail.account_for.both" : "walkthrough.mail.account_for.every") }];
  return (
    <CheckboxGroup legend={t("walkthrough.mail.account_for.legend")} className={styles.question} data-sign-in-sides="" data-account-for={props.account} data-answered={picked !== null ? "" : undefined}>
      {choices.map((c) => (
        <label key={c.value} className="side-chip" title={c.title} data-ticked={shown === c.value ? "true" : undefined}>
          <input type="radio" name={`account-for-${props.account || mine.join("-")}`} checked={shown === c.value} disabled={settings.isPending || wanted !== null} onChange={() => void choose(c.value)} />
          <span>{c.title}</span>
        </label>
      ))}
      {props.later && picked === null && (
        <p className="hint" data-account-for-left="">
          {t("walkthrough.mail.account_for.left")}
        </p>
      )}
      {problem && (
        <p className="problem-note" role="alert">
          {problem}
        </p>
      )}
    </CheckboxGroup>
  );
}
