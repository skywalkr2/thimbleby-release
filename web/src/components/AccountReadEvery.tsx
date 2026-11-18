// How often one account is read, on its card on Connections (design 7.9): "Read every 10 minutes · Change". Change opens a list to
// pick from; the choice is saved at once as the interval of each of the account's connections (an interval set on a connection
// wins over the mail and calendar defaults under Settings, Advanced, Mail).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, type S } from "../lib/api";
import { freshSettings, useAfterSave } from "../lib/settings-save";
import { SOURCES } from "./SourceSides";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { Select } from "../ui/Select";
import styles from "./ConnectionCard.module.css";

type Source = S["WatchSourceView"];

/** The choices, the same list the settings of the defaults offer. */
const CHOICES = [5, 10, 15, 30, 60];

export function AccountReadEvery(props: { sources: Source[]; account: string }) {
  const { t, tn } = useWords();
  const client = useQueryClient();
  const afterSave = useAfterSave();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const minutes = [...new Set(props.sources.map((s) => s.every_minutes))].sort((a, b) => a - b);
  if (minutes.length === 0) return null;
  const same = minutes.length === 1;
  const said = same ? tn("sources.read_every", minutes[0]) : t("connection.read_every_range", { from: minutes[0], to: minutes[minutes.length - 1] });
  const mine = props.sources.map((s) => s.id);

  const pick = async (value: string) => {
    setBusy(true);
    setProblem("");
    try {
      const current = await freshSettings(client);
      const list = (current.items.find((i) => i.key === SOURCES)?.value ?? []) as Array<Record<string, unknown> & { id: string }>;
      const changes = { [SOURCES]: list.map((s) => (mine.includes(s.id) ? { ...s, every_minutes: Number(value) } : s)) };
      const saved = await api.saveSettings({ changes, reset: [], fingerprint: current.fingerprint });
      await afterSave(saved, { quiet: true });
      void client.invalidateQueries({ queryKey: ["watch"] });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) void client.invalidateQueries({ queryKey: ["settings"] });
      setProblem(err instanceof ApiError && err.detail && err.status < 500 ? err.detail : t("connection.read_every_failed"));
    }
    setBusy(false);
  };

  return (
    <div className={styles.readEvery} data-card-read-every="">
      <span>{said}</span>
      {!open && (
        <Button variant="quiet" size="sm" className={styles.change} aria-expanded={false} aria-label={t("connection.read_every_change_named", { account: props.account })} onClick={() => setOpen(true)}>
          {t("connection.change")}
        </Button>
      )}
      {open && (
        <>
          <Select aria-label={t("connection.read_every_label", { account: props.account })} value={same ? minutes[0] : ""} disabled={busy || settings.isPending} onChange={(e) => void pick(e.target.value)}>
            {!same && <option value="">{said}</option>}
            {CHOICES.map((n) => (
              <option key={n} value={n}>
                {tn("sources.read_every", n)}
              </option>
            ))}
          </Select>
          <Button variant="quiet" size="sm" onClick={() => setOpen(false)}>
            {t("connection.sides_done")}
          </Button>
        </>
      )}
      {problem && (
        <span role="alert" data-read-every-problem="">
          {problem}
        </span>
      )}
    </div>
  );
}
