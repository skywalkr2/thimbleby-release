import type { S } from "./api";
import { backupAge, backupState, backupText, backupTone, backupWord, folderName } from "./backup";

const t = (key: string, vars: Record<string, string | number> = {}) => `${key}${JSON.stringify(vars)}`;
const status = (age_hours: number | null): S["BackupStatus"] => ({
  configured: true,
  last_success: null,
  age_hours,
  needs_attention: false,
  last_error: null,
  encrypted: false,
  folder: "/mnt/drive/Backups",
  newest_hours: age_hours,
});

test("a backup's age is said in whole hours, singular for one, and in days from two days", () => {
  expect(backupAge(status(null), t)).toBeNull();
  expect(backupAge(status(0.2), t)).toBe("age.under_hour{}");
  expect(backupAge(status(1.4), t)).toBe('age.hours.one{"n":1}');
  expect(backupAge(status(3), t)).toBe('age.hours.other{"n":3}');
  expect(backupAge(status(100), t)).toBe('age.days{"n":4}');
});

test("a folder is its own name, whichever way its path is written", () => {
  expect(folderName("/mnt/drive/Backups")).toBe("Backups");
  expect(folderName("/mnt/drive/Backups/")).toBe("Backups");
  expect(folderName("C:\\Users\\Pat\\Cloud Drive\\Copies")).toBe("Copies");
  expect(folderName("Drive")).toBe("Drive");
});

const local = (over: Partial<S["BackupStatus"]> = {}): S["BackupStatus"] => ({ ...status(null), configured: false, folder: "", newest_hours: 3, ...over });

test("copies kept only on this computer say so, quietly, while fresh", () => {
  const b = local();
  expect(backupState(b)).toBe("unset");
  expect(backupTone(b)).toBe("neutral");
  expect(backupWord(backupState(b), (k) => k)).toBe("backup.word.unset");
  expect(backupText(b, t)).toMatch(/^backup\.local_only\{\} · backup\.ok/);
});

test("a folder off the computer is named by its own name", () => {
  expect(backupText(status(2), t)).toContain('backup.folder{"folder":"Backups"}');
  expect(backupTone(status(2))).toBe("ok");
});

test("a failed or three-day-old copy is a warning whether or not a folder is chosen", () => {
  const failed = local({ needs_attention: true, last_error: "no space" as never });
  expect([backupState(failed), backupTone(failed), backupText(failed, t)]).toEqual(["failed", "danger", "backup.failed{}"]);
  const old = local({ needs_attention: true, newest_hours: 72 });
  expect([backupState(old), backupTone(old)]).toEqual(["overdue", "warn"]);
  expect(backupText(old, t)).toContain("backup.overdue");
  const folderOld = { ...status(72), needs_attention: true };
  expect([backupState(folderOld), backupTone(folderOld)]).toEqual(["overdue", "warn"]);
});
