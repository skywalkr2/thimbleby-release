import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { S } from "../lib/api";
import { fakeApi, renderApp } from "../test-utils";
import { AlphaNumbers } from "./AlphaNumbers";
import { ReportProblem } from "./ReportProblem";

const NUMBERS: S["AlphaNumbers"] = {
  since: "2026-11-02",
  until: "2026-11-08",
  days_so_far: 7,
  complete: true,
  days_used: 5,
  cost_per_day: 0.1234,
  corrections_per_day: 0.43,
  sent_as_written: 3,
  sent_edited: 2,
  first_result_minutes: 45,
};
const FACTS = { enabled: true, version: "9.8.7", system: "Example OS 1", reply_to: "" };

function routes(numbers: Partial<S["AlphaNumbers"]> = {}) {
  return fakeApi({
    "GET alpha-measures": () => ({ ...NUMBERS, ...numbers }),
    "GET report/facts": () => FACTS,
    "GET feedback/problems": () => ({ problems: [] }),
    "POST report/send": () => ({ ok: true, why: null }),
  });
}

/** The two dialogs as the app joins them: sharing closes the numbers and opens Report a problem with the same words. */
function Joined() {
  const [words, setWords] = useState<string | null>(null);
  return words === null ? <AlphaNumbers onClose={() => undefined} onShare={setWords} /> : <ReportProblem onClose={() => undefined} initialWords={words} />;
}

test("the five numbers are shown in plain words with their dates, and nothing is sent", async () => {
  const calls = routes();
  renderApp(<AlphaNumbers onClose={() => undefined} />);
  const dialog = await screen.findByRole("dialog", { name: "Your alpha numbers" });
  await within(dialog).findByText("Days used: 5 of 7");
  expect(within(dialog).getByText(/^Your first week: .+ to .+$/)).toBeInTheDocument();
  expect(within(dialog).getByText("Cost per day: $0.1234")).toBeInTheDocument();
  expect(within(dialog).getByText("Corrections per day: 0.43")).toBeInTheDocument();
  expect(within(dialog).getByText("Drafts sent as written: 3. Edited first: 2.")).toBeInTheDocument();
  expect(within(dialog).getByText("Time from install to a first result: 45 minutes")).toBeInTheDocument();
  // Without a report address there is nowhere to share, and nothing was posted.
  expect(within(dialog).queryByRole("button", { name: "Share these with the makers" })).toBeNull();
  expect(calls.filter((c) => c.route.startsWith("POST"))).toHaveLength(0);
});

test("a week not yet over says the days so far, no AI use costs nothing and no result says so", async () => {
  routes({ complete: false, days_so_far: 3, until: "2026-11-04", cost_per_day: 0, first_result_minutes: null, days_used: 2 });
  renderApp(<AlphaNumbers onClose={() => undefined} />);
  const dialog = await screen.findByRole("dialog", { name: "Your alpha numbers" });
  await within(dialog).findByText("Days used: 2 of 3");
  expect(within(dialog).getByText(/^So far, 3 days of your first week/)).toBeInTheDocument();
  expect(within(dialog).getByText("Cost per day: nothing, no AI used")).toBeInTheDocument();
  expect(within(dialog).getByText("Time from install to a first result: no result yet")).toBeInTheDocument();
});

test("a workspace with nothing recorded has no numbers to share", async () => {
  routes({ days_so_far: 0, since: null, until: null, days_used: 0 });
  renderApp(<AlphaNumbers onClose={() => undefined} onShare={() => undefined} />);
  const dialog = await screen.findByRole("dialog", { name: "Your alpha numbers" });
  await within(dialog).findByText("Nothing has been recorded yet, so there are no numbers.");
  expect(within(dialog).getByRole("button", { name: "Share these with the makers" })).toBeDisabled();
});

test("sharing opens the report with the numbers as its words, and what is sent is exactly what the preview showed", async () => {
  const user = userEvent.setup();
  const calls = routes();
  renderApp(<Joined />);
  await user.click(await screen.findByRole("button", { name: "Share these with the makers" }));
  const preview = (await screen.findByLabelText("What will be sent", { selector: "textarea" })) as HTMLTextAreaElement;
  await waitFor(() => expect(preview.value).toContain("App version: 9.8.7"));
  const shown = preview.value;
  expect(shown).toContain("Days used: 5 of 7");
  expect(shown).toContain("Drafts sent as written: 3. Edited first: 2.");
  // Nothing has been sent before Send.
  expect(calls.filter((c) => c.route === "POST report/send")).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(calls.filter((c) => c.route === "POST report/send")).toHaveLength(1));
  const sent = calls.find((c) => c.route === "POST report/send");
  const words = (sent?.body as { words: string }).words;
  // The preview is the words, then the reply, version and system lines the server adds.
  expect(shown.startsWith(words)).toBe(true);
  expect(words).toBe(words.trim());
});
