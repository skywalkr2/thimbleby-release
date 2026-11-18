// After a business or job is added (design 6.32, 7.9): which of the mailboxes and calendars already connected serve it. They
// were connected before it existed, so nothing says so yet; asking once keeps mail from them off Personal and out of the
// wrong side. Each tick is saved at once as that connection's `sides` and undone by unticking it; ticking nothing is allowed.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, ApiError, type S } from "../lib/api";
import { useSides } from "../lib/sides";
import { freshSettings, useAfterSave } from "../lib/settings-save";
import { useLoadFailure } from "../lib/load-failure";
import { useWords } from "../lib/wording";
import { CheckboxGroup } from "../ui/CheckboxGroup";
import { LoadFailed } from "../ui/LoadFailed";
import { Skeleton } from "../ui/Skeleton";
import { SOURCES } from "./SourceSides";
import styles from "./SideServedBy.module.css";

/** The connections that read mail or a calendar, on, as the ones a new side could be served by. */
export function useReadingSources() {
  return readingOf(useQuery({ queryKey: ["watch"], queryFn: api.watchSources }).data);
}

function readingOf(list: S["WatchSourceView"][] | undefined) {
  return (list ?? []).filter((s) => s.enabled && (s.reads ?? []).length > 0);
}

export function SideServedBy(props: { side: { id: string; name: string } }) {
  const { t, tn } = useWords();
  const client = useQueryClient();
  const afterSave = useAfterSave();
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  const failure = useLoadFailure(watch);
  const reading = readingOf(watch.data);
  const { personal, sides } = useSides();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [wanted, setWanted] = useState<Record<string, boolean>>({});
  const [problem, setProblem] = useState("");
  const chain = useRef<Promise<void>>(Promise.resolve());
  const order = [...(personal ? [personal] : []), ...sides.map((s) => s.project)];
  const stored = (settings.data?.items.find((i) => i.key === SOURCES)?.value ?? []) as Array<{ id: string; sides?: string[] }>;
  const held = (id: string) => (stored.find((s) => s.id === id)?.sides ?? []).includes(props.side.id);
  // The question is never dropped for a read that failed or has not answered: the person sees that, and can try again.
  if (failure.failed) return <LoadFailed message={t("settings.business.served_load_failed")} onRetry={() => void watch.refetch()} />;
  if (watch.isPending) return <Skeleton rows={2} />;
  if (reading.length === 0) return null;

  const save = async (id: string, on: boolean) => {
    // The settings as they are now, so a change made meanwhile is noticed rather than overwritten.
    const current = await freshSettings(client);
    const list = (current.items.find((i) => i.key === SOURCES)?.value ?? []) as Array<Record<string, unknown> & { id: string; sides?: string[] }>;
    const changes = {
      [SOURCES]: list.map((s) => {
        if (s.id !== id) return s;
        const now = new Set(s.sides ?? []);
        if (on) now.add(props.side.id);
        else now.delete(props.side.id);
        return { ...s, sides: [...order.filter((x) => now.has(x)), ...[...now].filter((x) => !order.includes(x))] };
      }),
    };
    const saved = await api.saveSettings({ changes, reset: [], fingerprint: current.fingerprint });
    // The screens are read again in the background: the next tick reads the settings itself and does not wait for every screen to
    // answer (a slow one would hold the ticks made after it, which are lost when the drawer closes first).
    void afterSave(saved, { quiet: true });
  };
  const change = (id: string, on: boolean) => {
    setProblem("");
    setWanted((all) => ({ ...all, [id]: on }));
    // One save at a time, in the order the ticks were made.
    chain.current = chain.current.then(async () => {
      try {
        // A save refused because the settings moved on (another save landed between the read and the write) is made again from
        // what is there now, so a tick is never lost to a race.
        for (let attempt = 1; ; attempt += 1) {
          try {
            await save(id, on);
            break;
          } catch (err) {
            if (!(err instanceof ApiError && err.status === 409) || attempt >= 3) throw err;
          }
        }
      } catch (err) {
        setProblem(err instanceof ApiError && err.detail && err.status < 500 ? err.detail : t("side.serves.failed", { name: props.side.name }));
      }
      setWanted((all) => Object.fromEntries(Object.entries(all).filter(([key]) => key !== id)));
    });
  };

  // One card for each account (its address over its inbox, its calendar and the rest), as setup and Connections ask the same thing;
  // a connection with no account (a mailbox, a folder) stands in a card of its own.
  const accounts = [...new Set(reading.map((s) => s.account ?? ""))];
  const shortOf = (source: (typeof reading)[number]) =>
    source.account && source.label.endsWith(`, ${source.account}`) ? source.label.slice(0, -(source.account.length + 2)) : source.label;
  return (
    <div data-side-served-by="" className={styles.group} role="group" aria-labelledby="side-serves-legend" aria-describedby="side-serves-hint">
      <p id="side-serves-legend" className={styles.legend}>
        {t("side.serves.legend", { name: props.side.name })}
      </p>
      {accounts.map((account) => {
        const mine = reading.filter((s) => (s.account ?? "") === account);
        return (
          <CheckboxGroup key={account || "none"} legend={account || mine[0].label} className={styles.card} data-served-account={account || undefined}>
            {mine.map((source) => (
              <label key={source.id} className="check-line">
                <input type="checkbox" checked={wanted[source.id] ?? held(source.id)} disabled={settings.isPending} onChange={(e) => change(source.id, e.target.checked)} />
                <span>{account ? shortOf(source) : source.label}</span>
              </label>
            ))}
          </CheckboxGroup>
        );
      })}
      <p className="hint" id="side-serves-hint">
        {tn("side.serves.hint", reading.length)}
      </p>
      {problem && (
        <p className="problem-note" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}
