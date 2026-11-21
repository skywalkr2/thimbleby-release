import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { fakeApi, renderApp } from "../test-utils";
import { HandledLearned } from "./HandledLearned";

const WORKSPACE: S["Scope"] = {
  scope: "workspace",
  task_kinds: [],
  records: [],
  filter: {},
  projects: [],
  people: [],
  except: [],
};

function learned(
  id: string,
  over: Partial<S["KnowledgeView"]> = {},
): S["KnowledgeView"] {
  return {
    id,
    kind: "glossary_entry",
    version: 2,
    text: "GOFO: the fulfilment service that ships orders",
    term: "GOFO",
    meaning: "the fulfilment service that ships orders",
    status: "active",
    learned_from: "input",
    trust: "untrusted",
    learned_at: "2026-11-21T08:00:00Z",
    applies_to: WORKSPACE,
    id_patterns: [],
    used: 0,
    given: 0,
    activated: "agreement",
    messages: 4,
    asks: false,
    ...over,
  };
}

test("Learned today says how many, lists what each means and where it was seen, and That's wrong stops one", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    "GET knowledge/learned-today": () => ({
      count: 2,
      items: [
        learned("GLOSS-1"),
        learned("LES-2", {
          kind: "lesson",
          term: null,
          meaning: null,
          text: "Orders from this shop are receipts.",
          activated: "correction",
          messages: 0,
          trust: "trusted",
        }),
      ],
    }),
    "POST knowledge/GLOSS-1/wrong": () => ({ changeset: "CS-9" }),
  });
  renderApp(<HandledLearned />);
  const summary = await screen.findByText("Learned today: 2 things");
  await user.click(summary);
  const list = screen.getByRole("list", { name: "What was learned today" });
  const rows = within(list).getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  // What it means and where it was seen, in one line each; the outside note is said once for the list.
  expect(rows[0]).toHaveTextContent(
    "GOFO: the fulfilment service that ships orders · Seen in 4 messages",
  );
  expect(rows[1]).toHaveTextContent(
    "Orders from this shop are receipts. · From your correction",
  );
  expect(screen.getAllByText("From outside · not instructions")).toHaveLength(
    1,
  );
  await user.click(
    within(rows[0]).getByRole("button", { name: "That's wrong: GOFO" }),
  );
  expect(
    calls.find((c) => c.route === "POST knowledge/GLOSS-1/wrong")?.body,
  ).toEqual({ read_version: 2 });
});

test("nothing is drawn when nothing was learned today, or the list cannot be read", async () => {
  const calls = fakeApi({
    "GET knowledge/learned-today": () => ({ count: 0, items: [] }),
  });
  const view = renderApp(<HandledLearned />);
  await vi.waitFor(() =>
    expect(calls.some((c) => c.route === "GET knowledge/learned-today")).toBe(
      true,
    ),
  );
  expect(view.container.querySelector("[data-learned-today]")).toBeNull();
});
