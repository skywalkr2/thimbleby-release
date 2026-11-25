// How the screens word the backup state (design 4.15, 7.1, 7.7): the same words in the status popover and Today's line.
import type { S } from "./api";

type T = (key: string, vars?: Record<string, string | number>) => string;

/** How long ago the last backup was, in words; null when none has succeeded. */
export function backupAge(b: { age_hours: number | null }, t: T): string | null {
  if (b.age_hours === null) return null;
  const h = b.age_hours;
  const hours = Math.floor(h);
  return h < 1 ? t("age.under_hour") : h < 48 ? t(`age.hours.${hours === 1 ? "one" : "other"}`, { n: hours }) : t("age.days", { n: Math.floor(h / 24) });
}

/** The age of the newest copy the status speaks of: the folder's own while one is chosen, else the newest kept on this computer. */
function copyAge(b: S["BackupStatus"]): number | null {
  return b.configured && b.problem !== "folder_missing" ? b.age_hours : (b.newest_hours ?? null);
}

/** The backup in one phrase: what it protects (this computer only, or the folder's name), then how it stands; a failed or old
 * copy says so instead. */
export function backupText(b: S["BackupStatus"], t: T): string {
  const age = backupAge({ age_hours: copyAge(b) }, t);
  const where = b.configured ? t("backup.folder", { folder: folderName(b.folder) }) : t("backup.local_only");
  let text: string;
  if (b.problem === "folder_missing") {
    // One state with one set of words: the copy kept here is named, the folder is named by its label, never its path.
    const folder = folderName(b.folder);
    text = age === null ? t("backup.folder_missing.none", { folder }) : t("backup.folder_missing", { folder });
  } else if (b.configured) {
    text = age === null ? (b.last_error ? t("backup.failed") : t("backup.never")) : b.needs_attention ? t("backup.overdue", { age }) : `${where} · ${t("backup.ok", { age })}`;
  } else if (b.needs_attention) {
    text = b.problem === "never" && age === null ? t("backup.local_never") : b.last_error || age === null ? t("backup.failed") : t("backup.overdue", { age });
  } else {
    text = age === null ? where : `${where} · ${t("backup.ok", { age })}`;
  }
  return b.encrypted ? `${text} · ${t("backup.encrypted")}` : text;
}

export type BackupState = "unset" | "never" | "failed" | "overdue" | "smaller" | "folder_missing" | "ok";

/** The backup's one state ("unset" is the quiet one: copies kept on this computer only), named the same in the header chip, Today's line and the popover. */
export function backupState(b: S["BackupStatus"]): BackupState {
  if (b.problem === "folder_missing") return "folder_missing";
  if (!b.configured) return b.needs_attention ? (b.problem === "never" ? "never" : b.last_error ? "failed" : "overdue") : "unset";
  if (b.age_hours === null) return b.last_error ? "failed" : "never";
  if (b.last_error && b.needs_attention) return "failed";
  return b.needs_attention ? "overdue" : "ok";
}

/** The one word for a backup state (wording `backup.word.<state>`): "Backup failed", "Backup overdue". */
export function backupWord(state: BackupState | string, t: T): string {
  return t(`backup.word.${state}`);
}

/** How the backup stands, for the state mark: a danger when the last try failed, a warning when one is due, fine when it is
 * recent, and quiet when none is set up. */
export function backupTone(b: S["BackupStatus"]): "ok" | "warn" | "danger" | "neutral" {
  if (!b.configured && !b.needs_attention) return "neutral";
  if (b.problem === "folder_missing") return "warn";
  if (b.last_error) return "danger";
  return b.needs_attention ? "warn" : "ok";
}

/** A folder by its own name, the last part of its path (a trailing separator ignored), for where a full path would crowd the page. */
export function folderName(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}
