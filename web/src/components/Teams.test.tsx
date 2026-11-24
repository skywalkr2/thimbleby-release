import "@testing-library/jest-dom/vitest";
import { screen, within } from "@testing-library/react";
import { fakeApi, renderApp } from "../test-utils";
import { Teams } from "./Teams";

// T3-09: the teams are listed on People, a table with the same detail pane as People, each name a link to its page with how many are in it; with none on file nothing is drawn.
test("each team is a row with a link to its page and how many people are in it", async () => {
  fakeApi({
    "GET teams": () => [
      { id: "TEAM-1", name: "Kitchen", people: ["PER-1", "PER-2"] },
      { id: "TEAM-4", name: "Empty team", people: [] },
    ],
  });
  renderApp(<Teams />);
  const table = await screen.findByRole("table", { name: "Teams" });
  const kitchen = within(table).getByRole("link", { name: "Kitchen" });
  expect(kitchen).toHaveAttribute("href", expect.stringContaining("TEAM-1"));
  expect(kitchen.closest("tr")).toHaveTextContent("2");
  expect(within(table).getByRole("link", { name: "Empty team" }).closest("tr")).not.toHaveTextContent(/\d/);
});

test("with no team on file the section is left out", async () => {
  const calls = fakeApi({ "GET teams": () => [] });
  renderApp(<Teams />);
  await vi.waitFor(() => expect(calls.some((c) => c.route === "GET teams")).toBe(true));
  expect(screen.queryByRole("heading", { name: "Teams" })).toBeNull();
});
