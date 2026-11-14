// Settings, Advanced: delete the workspace and everything kept of it (design 12.4). Removing an item keeps its history; this
// is the one way to take the content out. The dialog lists exactly what goes (each entry of the workspace folder, each backup
// copy, with its files and size) and what stays because another computer shares it, and the button works only once the
// workspace's own name has been typed. Nothing is deleted before that; the list is the one the app deletes, so a copy that
// appeared since is refused and the list is looked at again.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Heading } from "react-aria-components";
import { api, type S } from "../lib/api";
import { eraseLines } from "../lib/erase-groups";
import { problemText } from "../lib/problem";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { FormField } from "../ui/FormField";
import { DialogFooter, ModalPanel, restoreFocus } from "./ModalPanel";

export function DeleteWorkspace() {
  const { t, tn } = useWords();
  const client = useQueryClient();
  const titleId = useId();
  const [asking, setAsking] = useState<HTMLElement | null | false>(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [gone, setGone] = useState("");
  const plan = useQuery({ queryKey: ["erase"], queryFn: api.erasePlan, enabled: asking !== false, staleTime: 0, gcTime: 0 });
  const size = (n: number) => (n >= 1_000_000 ? t("erase.size.mb", { n: (n / 1_000_000).toFixed(1) }) : t("erase.size.kb", { n: Math.max(1, Math.round(n / 1000)) }));
  const close = () => {
    const opener = asking || null;
    setAsking(false);
    setTyped("");
    setProblem("");
    restoreFocus(() => opener);
  };
  const go = async (view: S["ErasePlanView"]) => {
    setBusy(true);
    setProblem("");
    try {
      const done = await api.erase({ token: view.token });
      setAsking(false);
      setGone(done.failed.length > 0 ? t("erase.failed", { paths: done.failed.map((f) => f.path).join(", ") }) : t("erase.done", { app: t("app.name") }));
    } catch (err) {
      setProblem(problemText(err, t));
      void client.invalidateQueries({ queryKey: ["erase"] });
    } finally {
      setBusy(false);
    }
  };
  const view = plan.data;
  const ready = !!view && typed.trim() === view.name && !busy;
  return (
    <section className="panel-section delete-workspace" aria-labelledby="erase-title" data-erase="">
      <h3 id="erase-title">{t("erase.title")}</h3>
      <p className="hint">{t("erase.intro")}</p>
      {gone ? (
        <p role="status">{gone}</p>
      ) : (
        <Button type="button" variant="danger" onClick={(e) => setAsking(e.currentTarget)}>
          {t("erase.open")}
        </Button>
      )}
      {asking !== false && (
        <ModalPanel titleId={titleId} onClose={close}>
          <Heading slot="title" id={titleId} level={2}>
            {t("erase.title")}
          </Heading>
          <form
            data-erase-dialog=""
            onSubmit={(e) => {
              e.preventDefault();
              if (view && ready) void go(view);
            }}
          >
            {!view ? (
              <p role="status">{plan.isError ? problemText(plan.error, t) : t("erase.loading")}</p>
            ) : (
              <>
                <h3 id={`${titleId}-list`}>{t("erase.list")}</h3>
                <ul aria-labelledby={`${titleId}-list`} className="erase-list">
                  {eraseLines(view.items).map((line) => (
                    <li key={line.group} data-group={line.group}>
                      <strong>{line.group === "backups" ? tn("erase.group.backups", line.count) : t(`erase.group.${line.group}`)}</strong> · {tn("erase.files", line.files, { size: size(line.bytes) })}
                      {line.commits ? ` · ${tn("erase.history", line.commits)}` : ""}
                    </li>
                  ))}
                </ul>
                {view.stays.map((item) => (
                  <p key={item.path} className="hint" role="note">
                    {t("erase.stays", { path: item.path })}
                  </p>
                ))}
                <p>{t("erase.cant_undo", { app: t("app.name") })}</p>
                <FormField label={t("erase.type", { name: view.name })}>
                  {(id) => <input id={id} type="text" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />}
                </FormField>
              </>
            )}
            <div role="status">
              {problem && (
                <p className="problem-note" role="alert">
                  {problem}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button type="button" onClick={close}>
                {t("erase.cancel")}
              </Button>
              <Button type="submit" variant="danger" loading={busy} disabled={!ready}>
                {t("erase.go")}
              </Button>
            </DialogFooter>
          </form>
        </ModalPanel>
      )}
    </section>
  );
}
