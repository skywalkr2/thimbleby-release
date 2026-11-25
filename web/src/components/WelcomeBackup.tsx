// The backup step of the setup guide (design 7.8): the cloud drives found on the computer, by name, with the first
// recommended; "Continue" makes the folder inside the drive, saves it and makes the first backup. Another
// folder (a USB drive, a network folder) is a path behind "Choose another folder", checked before it is saved. On the
// person's own computer that folder can be picked from a list.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, ApiError, type S } from "../lib/api";
import { backupText } from "../lib/backup";
import { problemText } from "../lib/problem";
import { useAfterSave } from "../lib/settings-save";
import { useWords } from "../lib/wording";
import { ConfirmRemove } from "./ConfirmRemove";
import { FolderPicker } from "./FolderPicker";
import { restoreFocus } from "./ModalPanel";
import { useContinue, useHasContinueSlot } from "../lib/walkthrough-continue";
import { Button } from "../ui/Button";
import { Pill } from "../ui/Pill";
import { FormField } from "../ui/FormField";
import { CheckboxGroup } from "../ui/CheckboxGroup";
import { Actions } from "../ui/Actions";
import { folderName } from "../lib/backup";
import { RadioCard, RadioCards } from "../ui/RadioCard";
import styles from "./WelcomeBackup.module.css";

/** The choice that is not one of the drives found: a folder of the person's own. */
const OTHER = "\u0001other";

/** A drive found, as one choice: its name and its account together, so two accounts of one drive stay apart. */
const keyOf = (drive: { name: string; account?: string }) => `${drive.name}\u0001${drive.account ?? ""}`;

function size(mb: number, t: (key: string, vars?: Record<string, string | number>) => string): string {
  return mb >= 1024 ? t("welcome.backup.gb", { n: (mb / 1024).toFixed(1) }) : t("welcome.backup.mb", { n: Math.round(mb) });
}

export function WelcomeBackup(props: {
  local: boolean;
  saveLabel?: string;
  /** Drawn on Settings' own page: its buttons start at the field's left edge, and a folder is shown by its name. */
  settings?: boolean;
}) {
  const { t } = useWords();
  const client = useQueryClient();
  const afterSave = useAfterSave();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const [path, setPath] = useState("");
  const [checked, setChecked] = useState<S["FolderCheckView"] | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const chooser = useRef<HTMLButtonElement>(null);
  const hasSlot = useHasContinueSlot();
  const drives = useQuery({ queryKey: ["cloud-folders"], queryFn: api.cloudFolders, enabled: props.local, retry: false });
  const found = drives.data?.folders ?? [];
  // The drive named after an account says which kind: a work account's is never chosen for the person.
  const driveName = (drive: { name: string; account?: string; work?: boolean }) =>
    drive.work ? t("welcome.backup.drive.work", { name: drive.name, account: drive.account ?? "" }) : t("welcome.backup.drive.personal", { name: drive.name });
  const [choice, setChoice] = useState<string | null>(null);
  const [removing, setRemoving] = useState<{ path: string; where: string } | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);

  const targets = settings.data?.items.find((i) => i.key === "storage.backups.targets")?.value;
  const existing = Array.isArray(targets)
    ? targets.flatMap((x: unknown) => {
        const target = x as { path?: unknown; label?: unknown };
        return typeof target?.path === "string" ? [{ path: target.path, label: typeof target.label === "string" ? target.label : "" }] : [];
      })
    : [];

  // The first backup is made as soon as the folder is chosen: the screen says how it went.
  const backup = existing.length > 0 && status.data?.backup.configured ? status.data.backup : null;
  const failed = !!backup && backup.last_success === null && !!backup.last_error;

  const check = async (at: string) => {
    setProblem("");
    try {
      setChecked(await api.folderCheck(at));
    } catch (err) {
      setChecked(null);
      setProblem(problemText(err, t));
    }
  };

  // Folders already chosen are kept unless the person chooses another way; with none, the first drive found is chosen.
  const looking = props.local && drives.isPending;
  const recommended = found.find((d) => d.recommended);
  const picked = choice ?? (existing.length > 0 || looking ? null : recommended ? keyOf(recommended) : found.length > 0 ? null : OTHER);
  const ownFolder = picked === OTHER;

  /** Makes the choice real: the drive's folder is made and saved, or the typed folder is. True when it went through. */
  const save = async (): Promise<boolean> => {
    if (!settings.data || picked === null) return true;
    setBusy(true);
    setProblem("");
    try {
      if (ownFolder) {
        const saved = await api.saveBackupFolder({ path: path.trim(), label: "", fingerprint: settings.data.fingerprint });
        setPath("");
        setChecked(null);
        void afterSave(saved, { message: t("welcome.backup.saved", { path: folderName(path.trim()) }) });
      } else {
        const drive = found.find((d) => keyOf(d) === picked);
        const saved = await api.backupToCloudFolder({ name: drive?.name ?? "", account: drive?.account ?? "", fingerprint: settings.data.fingerprint });
        void afterSave(saved, { message: t("welcome.backup.saved_drive", { name: drive ? driveName(drive) : "" }) });
      }
      setChoice(null);
      // The step goes on when the server has answered: the screens read again behind it, and a step that waited for every one
      // of those reads left the person on this screen for as long as the slowest took.
      void client.invalidateQueries({ queryKey: ["status"] });
      void client.invalidateQueries({ queryKey: ["backups"] });
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) void client.invalidateQueries({ queryKey: ["settings"] });
      setProblem(err instanceof ApiError && err.detail ? err.detail : problemText(err, t));
      return false;
    } finally {
      setBusy(false);
    }
  };

  /** Stops backing up to one place; the copies already there stay. */
  const remove = async () => {
    if (!settings.data || !removing) return;
    setRemoveBusy(true);
    try {
      const saved = await api.removeBackupFolder({ path: removing.path, fingerprint: settings.data.fingerprint });
      await afterSave(saved);
      setRemoving(null);
      await client.invalidateQueries({ queryKey: ["status"] });
      await client.invalidateQueries({ queryKey: ["backups"] });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) void client.invalidateQueries({ queryKey: ["settings"] });
      setRemoving(null);
      setProblem(err instanceof ApiError && err.detail ? err.detail : problemText(err, t));
    } finally {
      setRemoveBusy(false);
    }
  };

  // A folder the check refused holds Continue, with the reason under the box once: the press never has to find it out again.
  const refused = ownFolder && !!checked && !checked.ok;
  const missing = looking
    ? t("welcome.backup.looking")
    : ownFolder && !path.trim()
      ? t("welcome.backup.why_path")
      : picked === null && existing.length === 0
        ? t("welcome.backup.why_path")
        : refused
        ? t("welcome.backup.why_refused")
        : !settings.data ? t("welcome.backup.getting_ready") : "";
  useContinue(hasSlot ? { run: save, label: t("welcome.backup.go"), disabled: !!missing, why: missing } : null);

  return (
    <div className="guide-body" data-in-settings={props.settings ? "" : undefined}>
      {existing.length === 0 && settings.data && (
        <p className="hint" data-local-only="">
          {t("welcome.backup.local_only")}
        </p>
      )}
      {existing.length > 0 && (
        <div>
          <p className="what">{t("welcome.backup.current")}</p>
          <ul className="plain-list">
            {existing.map((e) => (
              <li key={e.path} className="inline-field">
                <span className="path">
                  {props.settings ? e.label || folderName(e.path) : e.label ? t("welcome.backup.target", { label: e.label, path: e.path }) : e.path}
                </span>
                <Button
                  size="sm"
                  variant="quiet"
                  aria-label={t("backups.remove_for", { where: e.label || e.path })}
                  onClick={() => setRemoving({ path: e.path, where: e.label || e.path })}
                >
                  {t("backups.remove")}
                </Button>
              </li>
            ))}
          </ul>
          {backup && (
            <p className={failed ? "problem-note" : "hint"} role={failed ? "alert" : "status"} data-first-backup="">
              {failed
                ? t("welcome.backup.first_failed", { problem: backup.last_error ?? "" })
                : backup.last_success === null
                  ? t("welcome.backup.first_making")
                  : backup.needs_attention
                    ? backupText(backup, t)
                    : t("welcome.backup.first_made")}
            </p>
          )}
        </div>
      )}
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        {found.length > 0 || existing.length > 0 ? (
          <CheckboxGroup legend={t("welcome.backup.where")}>
            <RadioCards>
            {found.map((drive) => (
              <RadioCard key={keyOf(drive)} name="backup-where" checked={picked === keyOf(drive)} onChange={() => setChoice(keyOf(drive))} title={driveName(drive)} description={drives.data?.shown} tag={drive.recommended && <Pill>{t("welcome.ai.recommended")}</Pill>} />
            ))}
            <RadioCard name="backup-where" checked={ownFolder} onChange={() => setChoice(OTHER)} title={t("welcome.backup.other")} description={t("welcome.backup.other_note")} />
            </RadioCards>
          </CheckboxGroup>
        ) : (
          props.local && !looking && <p className="hint">{t("welcome.backup.none_found")}</p>
        )}
        {ownFolder && (
          <>
            <FormField id="backup-path" label={t("welcome.backup.path")}>
              <div className="inline-field">
                <input
                  id="backup-path"
                  type="text"
                  value={path}
                  // On the person's own computer the folder is picked from the list, never typed; only where the app cannot list
                  // folders (a hosted install) is the address a typed one.
                  readOnly={props.local}
                  autoComplete="off"
                  aria-describedby="backup-path-hint"
                  // The folder is checked as soon as the person leaves the box (or presses Enter), with the result in words under it.
                  onBlur={() => {
                    if (path.trim() && !checked) void check(path.trim());
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && path.trim()) {
                      e.preventDefault();
                      void check(path.trim());
                    }
                  }}
                  onChange={(e) => {
                    setPath(e.target.value);
                    setChecked(null);
                  }}
                />
                {props.local && (
                  <Button ref={chooser} onClick={() => setPicking(true)}>
                    {t("welcome.backup.choose")}
                  </Button>
                )}
              </div>
              <p className="hint" id="backup-path-hint">
                {!props.local
                  ? t("welcome.backup.path_hint")
                  : (drives.data?.names ?? []).length > 0
                    ? t("welcome.backup.path_pick", { drives: (drives.data?.names ?? []).join(", ") })
                    : t("welcome.backup.path_pick_plain")}
              </p>
            </FormField>
            <div role="status">
              {checked && (
                <p className={checked.ok ? "hint" : "problem-note"}>
                  {checked.ok
                    ? checked.free_mb === null || checked.free_mb === undefined
                      ? t("welcome.backup.ok")
                      : t("welcome.backup.ok_free", { size: size(checked.free_mb, t) })
                    : t("welcome.backup.not_ok", { problem: checked.problem ?? "" })}
                </p>
              )}
            </div>
          </>
        )}
        {problem && !(refused && problem === checked?.problem) && (
          <p className="problem-note" role="alert">
            {problem}
          </p>
        )}
        {found.some((d) => d.work) && (
          <p className="hint" data-work-drive="">
            {t("welcome.backup.work_note")}
          </p>
        )}
        {/* In Settings the button appears once there is something to save: never a disabled one before a choice. */}
        {!hasSlot && !(props.settings && (!!missing || picked === null)) && (
          <Actions align={props.settings ? "start" : "end"}>
            <Button variant="primary" loading={busy} disabled={!!missing || picked === null} reason={missing || undefined} onClick={() => void save()}>
              {props.saveLabel ?? t("welcome.backup.go_here")}
            </Button>
          </Actions>
        )}
      </form>
      {removing && (
        <ConfirmRemove
          title={t("backups.remove_title", { where: removing.where })}
          go={t("backups.remove_go")}
          busy={removeBusy}
          onGo={() => void remove()}
          onCancel={() => setRemoving(null)}
        >
          <p>{t("backups.remove_text")}</p>
        </ConfirmRemove>
      )}
      {picking && (
        <FolderPicker
          start={checked?.ok ? path : undefined}
          onClose={() => {
            setPicking(false);
            restoreFocus(() => chooser.current);
          }}
          onPick={(picked) => {
            setPicking(false);
            setPath(picked);
            void check(picked);
            restoreFocus(() => chooser.current);
          }}
        />
      )}
    </div>
  );
}
