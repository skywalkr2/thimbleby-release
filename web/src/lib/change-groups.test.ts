import type { S } from "./api";
import { accountsOf, groupChanges } from "./change-groups";

// The same change read from two of the person's accounts is one row naming both (`ui.twin_window_minutes`).
type Item = S["ChangeItem"];
const item = (id: string, createdAt: string): Item => ({
  id,
  version: 1,
  dismissed: false,
  stage_task: false,
  first_go: false,
  refused: false,
  state: "done",
  waiting: null,
  created_at: createdAt,
  note: null,
  source: null,
  source_title: null,
  changeset: null,
});


describe("the same change read from two accounts", () => {
  const read = (id: string, source: string, title: string, at: string): Item => ({ ...item(id, at), source, source_title: title });
  const same = () => "Invitation to the review";

  test("within the window it is one row naming both accounts, never a row for each", () => {
    const rows = [read("A", "SRC-1", "Work account", "2026-10-20T09:05:00Z"), read("B", "SRC-2", "Home account", "2026-10-20T09:00:00Z")];
    const [group] = groupChanges(rows, same, () => "done", 10);
    expect(group.runs).toHaveLength(1);
    expect(group.runs[0].head.id).toBe("A");
    expect(group.runs[0].twins.map((c) => c.id)).toEqual(["B"]);
    expect(accountsOf(group.runs[0])).toEqual(["Work account", "Home account"]);
  });

  test("farther apart than the window, from one account, or with the window off, each stays a row of its own account (an ordinary run of rows that read the same)", () => {
    const far = [read("A", "SRC-1", "Work account", "2026-10-20T09:30:00Z"), read("B", "SRC-2", "Home account", "2026-10-20T09:00:00Z")];
    expect(groupChanges(far, same, () => "done", 10)[0].runs[0].twins).toEqual([]);
    const one = [read("A", "SRC-1", "Work account", "2026-10-20T09:05:00Z"), read("B", "SRC-1", "Work account", "2026-10-20T09:00:00Z")];
    expect(groupChanges(one, same, () => "done", 10)[0].runs[0].twins).toEqual([]);
    const near = [read("A", "SRC-1", "Work account", "2026-10-20T09:05:00Z"), read("B", "SRC-2", "Home account", "2026-10-20T09:00:00Z")];
    expect(groupChanges(near, same, () => "done", 0)[0].runs[0].twins).toEqual([]);
  });
});
