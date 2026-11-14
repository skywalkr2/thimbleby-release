import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { fakeApi, Refuse, renderApp } from "../test-utils";
import { DeleteWorkspace } from "./DeleteWorkspace";

const PLAN: S["ErasePlanView"] = {
  name: "my-work",
  token: "token-1",
  items: [
    { kind: "workspace", path: "/home/me/my-work/cockpit.db", name: "cockpit.db", files: 1, bytes: 2_500_000 },
    { kind: "workspace", path: "/home/me/my-work/.git", name: ".git", files: 40, bytes: 90_000, commits: 12 },
    { kind: "backup", path: "/mnt/drive/my-work-20261028-090000", name: "my-work-20261028-090000", files: 9, bytes: 3_000_000 },
    { kind: "unfinished_backup", path: "/mnt/drive/.my-work-20261027-090000.part", name: ".my-work-20261027-090000.part", files: 2, bytes: 4000 },
  ],
  stays: [{ kind: "synced_folder", path: "/home/me/Shared", name: "Shared", files: 3, bytes: 100 }],
};

test("it lists exactly what goes and what stays, and deleting needs the workspace's name typed", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({ "GET erase": () => PLAN, "POST erase": () => ({ removed: 5, failed: [] }) });
  renderApp(<DeleteWorkspace />);
  expect(screen.getByText(/Removing an item keeps its history/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Delete this workspace…" }));
  const dialog = await screen.findByRole("dialog");
  const list = await within(dialog).findByRole("list", { name: "This will be deleted" });
  const rows = within(list).getAllByRole("listitem");
  // Plain groups: the database and the history are the records; both backup copies are counted together, with the right plural.
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("Your records and their history · 41 files, 2.6 MB · 12 changes in its history");
  expect(rows[1]).toHaveTextContent("2 backup copies · 11 files, 3.0 MB");
  expect(list).not.toHaveTextContent(/cockpit|\.git|\.db/);
  expect(within(dialog).getByRole("note")).toHaveTextContent("shared with another computer: /home/me/Shared");
  const go = within(dialog).getByRole("button", { name: "Delete everything" });
  expect(go).toBeDisabled();
  await user.type(within(dialog).getByLabelText("Type my-work to delete all of it"), "my-wor");
  expect(go).toBeDisabled();
  await user.type(within(dialog).getByLabelText("Type my-work to delete all of it"), "k");
  expect(go).toBeEnabled();
  expect(calls.some((c) => c.route === "POST erase")).toBe(false);
  await user.click(go);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Everything was deleted"));
  expect(calls.find((c) => c.route === "POST erase")?.body).toEqual({ token: "token-1" });
  expect(screen.queryByRole("button", { name: "Delete this workspace…" })).toBeNull();
});

test("a list that changed is refused, says so, and nothing is shown as deleted", async () => {
  const user = userEvent.setup();
  fakeApi({
    "GET erase": () => PLAN,
    "POST erase": () => new Refuse(409, "What would be deleted has changed since you looked, so nothing was deleted. Look again."),
  });
  renderApp(<DeleteWorkspace />);
  await user.click(screen.getByRole("button", { name: "Delete this workspace…" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(await within(dialog).findByLabelText("Type my-work to delete all of it"), "my-work");
  await user.click(within(dialog).getByRole("button", { name: "Delete everything" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("has changed since you looked");
  expect(screen.queryByText(/Everything was deleted/)).toBeNull();
});

test("cancelling closes the list and deletes nothing", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({ "GET erase": () => PLAN });
  renderApp(<DeleteWorkspace />);
  await user.click(screen.getByRole("button", { name: "Delete this workspace…" }));
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(calls.some((c) => c.route === "POST erase")).toBe(false);
});
