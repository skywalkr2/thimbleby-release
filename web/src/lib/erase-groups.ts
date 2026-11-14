// What Delete this workspace lists, in the person's words: the app's own files grouped by what they hold, never by file name.
// One function, so the dialog and any other place that lists what would go says it the same way.
import type { S } from "./api";

type Item = S["ErasePlanView"]["items"][number];

export type EraseGroup = "records" | "settings" | "came_in" | "backups" | "other";

/** The order the groups are listed in. */
export const ERASE_ORDER: EraseGroup[] = ["records", "settings", "came_in", "backups", "other"];

// The entries of a workspace folder by what they hold. An entry no group names is listed as "other", never by its file name.
const RECORDS = /^((thimbleby|cockpit)\.db(-[a-z]+)?|data|\.git)$/;
const SETTINGS = /^(config|\.(thimbleby|cockpit)|\.gitignore|plugins|plugin-data|prompts|playbooks?)$/;
const CAME_IN = /^(sources|texts|files|inbox|attachments)$/;

export function groupOf(item: Pick<Item, "kind" | "name">): EraseGroup {
  if (item.kind === "backup" || item.kind === "unfinished_backup") return "backups";
  if (RECORDS.test(item.name)) return "records";
  if (SETTINGS.test(item.name)) return "settings";
  if (CAME_IN.test(item.name)) return "came_in";
  return "other";
}

export interface EraseLine {
  group: EraseGroup;
  /** How many things are in it: files, or for the backups, copies. */
  count: number;
  files: number;
  bytes: number;
  /** For the records: how many changes the history holds, when it could be counted. */
  commits: number | null;
}

/** The plan's items as one line per group that has anything in it, in the listed order. */
export function eraseLines(items: Item[]): EraseLine[] {
  const lines = new Map<EraseGroup, EraseLine>();
  for (const item of items) {
    const group = groupOf(item);
    const line = lines.get(group) ?? { group, count: 0, files: 0, bytes: 0, commits: null };
    line.count += 1;
    line.files += item.files;
    line.bytes += item.bytes;
    if (item.commits) line.commits = (line.commits ?? 0) + item.commits;
    lines.set(group, line);
  }
  return ERASE_ORDER.flatMap((g) => (lines.has(g) ? [lines.get(g)!] : []));
}
