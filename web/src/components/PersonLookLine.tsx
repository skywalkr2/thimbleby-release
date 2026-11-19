// How often the assistant looks at who you deal with, as a line under People's title (design 6.32, 7.9): "<assistant> looks at
// who you deal with every week · Change". Change opens a dialog with the interval as a list to pick from and about what the
// looks cost a week, worked out from the estimate for one look. The interval is an ordinary setting (Settings, Advanced, What
// it learns finds it too); it is read at the moment of use, so a change applies at once, with Undo.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useMoney } from "../lib/money";
import { problemText } from "../lib/problem";
import { freshSettings, useAfterSave } from "../lib/settings-save";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { Drawer } from "../ui/Drawer";
import { FormField } from "../ui/FormField";
import { Select } from "../ui/Select";

const KEY = "dispatch.knowledge.person_look_every_days";

/** An interval in days as words after "every": day, week, 2 weeks, month, or "N days". */
export function usePeriod() {
  const { t, tn, has } = useWords();
  return (days: number) => (has(`people.look.period.d${days}`) ? t(`people.look.period.d${days}`) : tn("people.look.period.days", days));
}

export function PersonLookLine() {
  const { t, tn } = useWords();
  const client = useQueryClient();
  const afterSave = useAfterSave();
  const money = useMoney();
  const period = usePeriod();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const cost = useQuery({ queryKey: ["person-look-cost"], queryFn: api.personLookCost });
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const id = useId();
  const item = settings.data?.items.find((i) => i.key === KEY);
  if (!item) return null;
  const days = Number(item.value ?? item.default ?? 7);
  const chosen = Number(picked ?? days);
  const off = item.locked || !item.editable;
  const options = [...new Set([...(item.options ?? []), String(days)])].sort((a, b) => Number(a) - Number(b));

  // What the looks of a week cost at the chosen interval: one look's estimate, times the looks that fit in a week.
  const looks = 7 / chosen;
  const perLook = cost.data?.per_look_usd;
  const looksSaid = tn("people.look.cost.looks", Math.round(looks * 10) / 10);
  const costText = !cost.data
    ? ""
    : cost.data.kind === "money" && perLook != null
      ? t("people.look.cost.money", { amount: money(perLook * looks), looks: looksSaid })
      : cost.data.kind === "runs"
        ? t("people.look.cost.runs", { looks: looksSaid })
        : t("people.look.cost.unknown");

  const close = () => {
    setOpen(false);
    setPicked(null);
    setProblem("");
  };
  const save = async () => {
    if (chosen === days) return close();
    setBusy(true);
    setProblem("");
    try {
      const current = await freshSettings(client);
      const saved = await api.saveSettings({ changes: { [KEY]: chosen }, reset: [], fingerprint: current.fingerprint });
      await afterSave(saved);
      void client.invalidateQueries({ queryKey: ["person-look-cost"] });
      close();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) void client.invalidateQueries({ queryKey: ["settings"] });
      setProblem(err instanceof ApiError && err.detail && err.status < 500 ? err.detail : problemText(err, t));
    }
    setBusy(false);
  };

  return (
    <>
      <p className="hint" data-person-look-line="">
        {t("people.look.line", { period: period(days) })}{" "}
        <button type="button" className="link-button" aria-haspopup="dialog" onClick={() => setOpen(true)}>
          {t("people.look.change")}
        </button>
      </p>
      <Drawer
        open={open}
        title={t("people.look.title")}
        onClose={close}
        dirty={picked !== null && chosen !== days}
        footer={
          <>
            <Button variant="quiet" onClick={close}>
              {t("action.cancel")}
            </Button>
            <Button variant="primary" onClick={() => void save()} disabled={busy || off} reason={off ? t("settings.locked_flag") : undefined}>
              {t("people.look.save")}
            </Button>
          </>
        }
      >
        <p className="hint">{t("people.look.intro")}</p>
        <FormField id={`${id}-days`} label={t("people.look.how_often")}>
          <Select id={`${id}-days`} value={String(chosen)} disabled={busy || off} onChange={(e) => setPicked(e.target.value)}>
            {options.map((o) => (
              <option key={o} value={o}>
                {t("people.look.option", { period: period(Number(o)) })}
              </option>
            ))}
          </Select>
        </FormField>
        <p className="hint" role="status" data-person-look-cost="">
          {costText}
        </p>
        {problem && (
          <p className="problem-note" role="alert">
            {problem}
          </p>
        )}
      </Drawer>
    </>
  );
}


