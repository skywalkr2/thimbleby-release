import { eraseLines, groupOf } from "./erase-groups";

type Kind = "backup" | "workspace" | "unfinished_backup" | "synced_folder";
const item = (kind: Kind, name: string, files = 1, bytes = 10, commits?: number) => ({ kind, path: `/x/${name}`, name, files, bytes, commits });

test("every entry of a workspace folder is a group in words, never its file name", () => {
  expect(groupOf({ kind: "workspace" as const, name: "cockpit.db-wal" })).toBe("records");
  expect(groupOf({ kind: "workspace" as const, name: ".git" })).toBe("records");
  expect(groupOf({ kind: "workspace" as const, name: ".gitignore" })).toBe("settings");
  expect(groupOf({ kind: "workspace" as const, name: ".cockpit" })).toBe("settings");
  expect(groupOf({ kind: "workspace" as const, name: ".thimbleby" })).toBe("settings");
  expect(groupOf({ kind: "workspace" as const, name: "thimbleby.db-wal" })).toBe("records");
  expect(groupOf({ kind: "workspace" as const, name: "texts" })).toBe("came_in");
  expect(groupOf({ kind: "workspace" as const, name: "something-new" })).toBe("other");
  expect(groupOf({ kind: "backup" as const, name: "w-20261001-101010" })).toBe("backups");
  expect(groupOf({ kind: "unfinished_backup" as const, name: ".w.part" })).toBe("backups");
});

test("the lines are one per group, in order, with their counts added", () => {
  const lines = eraseLines([item("backup", "a", 3), item("workspace", "cockpit.db", 1), item("workspace", ".gitignore", 1), item("backup", "b", 4), item("workspace", ".git", 20, 5, 7)]);
  expect(lines.map((l) => l.group)).toEqual(["records", "settings", "backups"]);
  expect(lines[0]).toMatchObject({ files: 21, commits: 7 });
  expect(lines[2]).toMatchObject({ count: 2, files: 7 });
});
