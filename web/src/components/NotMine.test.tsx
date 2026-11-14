import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fakeApi, renderApp } from "../test-utils";
import { useNotMineToTrack } from "./ChangeThis";

// "Not mine to track" (design 6.22): one menu entry for a to-do or question that came from a watched source. It acts at
// once, says in the toast how many went with it, and one Undo puts everything back, the source's stance included.

function Entry(props: { kind: "action" | "question"; id: string }) {
  const { entry } = useNotMineToTrack({ kind: props.kind, id: props.id });
  return <button onClick={entry.run}>{entry.label}</button>;
}

function Offered(props: { origin?: { watch?: string | null } | null }) {
  const { entries } = useNotMineToTrack({ kind: "action", id: "ACT-3" }, props.origin);
  return <p>{entries.length === 0 ? "not offered" : "offered"}</p>;
}

const DONE = { changeset: "CS-4", source: "news", source_label: "News page", others: 2, stance: "follow", read_back: "Dropped this and 2 more from News page. It is now only read to understand." };

test("the entry is worded for the person, acts at once and says how many went with the item", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({ "POST not-mine/action/ACT-3": () => DONE });
  renderApp(<Entry kind="action" id="ACT-3" />);
  await user.click(await screen.findByRole("button", { name: "Not mine to track" }));
  expect(await screen.findByText(/Dropped this and 2 more from News page/)).toBeInTheDocument();
  expect(calls.find((c) => c.route === "POST not-mine/action/ACT-3")?.body).toEqual({});
});

test("one Undo takes the drops and the source's earlier stance back together", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({ "POST not-mine/question/Q-1": () => DONE, "POST not-mine/undo": () => ({ restored: 3 }) });
  renderApp(<Entry kind="question" id="Q-1" />);
  await user.click(await screen.findByRole("button", { name: "Not mine to track" }));
  await user.click(await screen.findByRole("button", { name: "Undo" }));
  await waitFor(() =>
    expect(calls.find((c) => c.route === "POST not-mine/undo")?.body).toEqual({ changeset: "CS-4", source: "news", stance: "follow" }),
  );
});

test("a refusal is said in words and nothing is undone", async () => {
  const user = userEvent.setup();
  fakeApi({
    "POST not-mine/action/ACT-3": () => {
      throw Object.assign(new Error("That item isn't open any more."), { status: 409 });
    },
  });
  renderApp(<Entry kind="action" id="ACT-3" />);
  await user.click(await screen.findByRole("button", { name: "Not mine to track" }));
  expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
});

test("a row offers it only when its origin names the watched source that handed the item in", async () => {
  renderApp(
    <>
      <Offered origin={{ watch: "news" }} />
      <Offered origin={{ watch: null }} />
      <Offered origin={null} />
    </>,
  );
  expect(await screen.findAllByText("offered")).toHaveLength(1);
  expect(screen.getAllByText("not offered")).toHaveLength(2);
});
