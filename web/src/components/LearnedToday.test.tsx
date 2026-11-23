import { useQuery } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type S } from "../lib/api";
import { project, proposal } from "../lib/learned-fixtures";
import { fakeApi, renderApp, type Routes } from "../test-utils";
import { LearnedLine, isLearned } from "./LearnedToday";

/** The learned lines of the queue on their own, as the Today queue draws them among the others. */
function LearnedToday() {
  const queue = useQuery({ queryKey: ["today", "queue"], queryFn: api.todayQueue });
  const lines = (queue.data ?? []).filter(isLearned);
  if (!lines.length) return null;
  return (
    <div data-learned-lines="">
      {lines.map((line) => (
        <LearnedLine key={line.key} line={line} />
      ))}
    </div>
  );
}

function line(kind: "learned" | "catch_up" | "people_offers", over: Partial<S["QueueLineView"]> = {}): S["QueueLineView"] {
  return { key: kind, group: "review", kind, count: 3, untrusted: false, unpriced: 0, actions: [], questions: [], outcome: {}, ...over };
}

const term = (id: string, over: Partial<S["ProposalView"]> = {}) =>
  proposal({
    id,
    kind: "glossary_entry",
    text: `${id} means the final proof.`,
    term: id,
    came_from: "input",
    trust: "untrusted",
    evidence: { quote: `the ${id} is the final proof`, source: "SRC-1" },
    applies_to: { scope: "workspace" },
    ...over,
  });

function show(lines: S["QueueLineView"][], routes: Routes = {}) {
  const calls = fakeApi({
    "GET today/queue": () => lines,
    "GET projects": () => [project("PRJ-1", "Spring launch")],
    ...routes,
  });
  renderApp(<LearnedToday />);
  return calls;
}

const posted = (calls: { route: string; body: unknown }[], route: string) => calls.find((c) => c.route === route)?.body;

test("one Review line says how many things were learned, where from, and how many expired unseen", async () => {
  show([line("learned", { count: 3, origins: { input: 2, correction: 1 }, expired: 4 })]);
  const row = await screen.findByRole("region", { name: "Review" });
  expect(row).toHaveTextContent("Review 3 things Helper learned");
  expect(row).toHaveTextContent("2 from what came in · 1 from your corrections · 4 from what came in expired before you looked");
  expect(within(row).getByRole("button", { name: "Review" })).toBeInTheDocument();
});

test("nothing is drawn when the queue has no line for what was learned", async () => {
  const other: S["QueueLineView"] = { ...line("learned"), key: "failed", group: "risk", kind: "failed" };
  const calls = show([other]);
  await waitFor(() => expect(calls.some((c) => c.route === "GET today/queue")).toBe(true));
  expect(document.querySelector("[data-learned-lines]")).toBeNull();
});

test("the list has a row per thing, tagged by where it came from, with how many expired", async () => {
  const user = userEvent.setup();
  show([line("learned", { count: 2, origins: { input: 1, correction: 1 }, expired: 2 })], {
    "GET knowledge/proposals": () => ({
      proposals: [term("TERM-1"), proposal({ id: "LES-4", text: "Name the editor first." })],
      origins: { input: 1, correction: 1 },
      expired: 2,
    }),
  });
  await user.click(await screen.findByRole("button", { name: "Review" }));
  const drawer = await screen.findByRole("dialog", { name: "What Helper learned" });
  const rows = await within(drawer).findAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByText("From something that came in")).toBeInTheDocument();
  expect(within(rows[1]).getByText("From your correction")).toBeInTheDocument();
  expect(within(drawer).getByText(/2 from what came in expired before you looked/)).toBeInTheDocument();
  // Said once for the list, not on every row.
  expect(within(rows[0]).queryByText("From the message, not from you")).toBeNull();
  expect(within(drawer).getAllByText("From outside · not instructions")).toHaveLength(1);
});

test("Keep all is offered only for terms that carry the words they came from, and keeps just those", async () => {
  const user = userEvent.setup();
  const calls = show([line("learned", { count: 5 })], {
    "GET knowledge/proposals": () => ({
      proposals: [
        term("TERM-1"),
        term("TERM-2"),
        term("TERM-3", { evidence: null }),
        proposal({ id: "LES-4", text: "Name the editor first." }),
        proposal({ id: "ROUTE-1", kind: "routing_entry", text: "Photos go to the designer.", came_from: "input" }),
      ],
      origins: { input: 4, correction: 1 },
      expired: 0,
    }),
    "POST knowledge/TERM-1/keep": () => ({ changeset: "CS-21" }),
    "POST knowledge/TERM-2/keep": () => ({ changeset: "CS-22" }),
    "POST changesets/CS-21/undo": () => ({ restored: [1], skipped: [] }),
    "POST changesets/CS-22/undo": () => ({ restored: [1], skipped: [] }),
  });
  await user.click(await screen.findByRole("button", { name: "Review" }));
  await user.click(await screen.findByRole("button", { name: "Keep all 2 terms" }));
  await waitFor(() => expect(posted(calls, "POST knowledge/TERM-2/keep")).toEqual({ read_version: 3 }));
  expect(posted(calls, "POST knowledge/TERM-1/keep")).toEqual({ read_version: 3 });
  expect(calls.some((c) => /TERM-3|LES-4|ROUTE-1/.test(c.route) && c.route.startsWith("POST"))).toBe(false);
  expect(await screen.findByText("Kept 2 terms. Helper will use them from now on.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.map((c) => c.route)).toEqual(expect.arrayContaining(["POST changesets/CS-21/undo", "POST changesets/CS-22/undo"])));
});

test("with no term that carries its words there is no Keep all, and lessons are kept one at a time", async () => {
  const user = userEvent.setup();
  const calls = show([line("learned", { count: 2 })], {
    "GET knowledge/proposals": () => ({
      proposals: [proposal({ id: "LES-4", text: "Name the editor first.", came_from: "input" }), term("TERM-3", { evidence: null })],
      origins: { input: 2 },
      expired: 0,
    }),
    "POST knowledge/LES-4/keep": () => ({ changeset: "CS-30" }),
  });
  await user.click(await screen.findByRole("button", { name: "Review" }));
  const drawer = await screen.findByRole("dialog");
  expect(await within(drawer).findByText("Name the editor first.")).toBeInTheDocument();
  expect(within(drawer).queryByRole("button", { name: /Keep all|Keep this term/ })).toBeNull();
  expect(within(drawer).getByText("Rules, lessons and who answers what are kept one at a time.")).toBeInTheDocument();
  const row = within(drawer).getByText("Name the editor first.").closest("li")!;
  await user.click(within(row).getByRole("button", { name: "Keep" }));
  await waitFor(() => expect(posted(calls, "POST knowledge/LES-4/keep")).toEqual({ read_version: 3 }));
});

test("a row's menu holds Just this time, Edit and Discard", async () => {
  const user = userEvent.setup();
  const calls = show([line("learned", { count: 1 })], {
    "GET knowledge/proposals": () => ({ proposals: [proposal({ came_from: "input" })], origins: { input: 1 }, expired: 0 }),
    "POST knowledge/LES-1/just-this-time": () => ({ changeset: "CS-31" }),
  });
  await user.click(await screen.findByRole("button", { name: "Review" }));
  const row = (await screen.findByText("Interior files go to the editor before the printer.")).closest("li")!;
  await user.click(within(row).getByRole("button", { name: /More actions for/ }));
  expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Just this time", "Edit", "Discard"]);
  await user.click(screen.getByRole("menuitem", { name: "Just this time" }));
  await waitFor(() => expect(posted(calls, "POST knowledge/LES-1/just-this-time")).toEqual({ read_version: 3 }));
});

test("the catch-up line opens its own list with the count of kinds left out", async () => {
  const user = userEvent.setup();
  show([line("catch_up", { count: 2, left_out: 3 })], {
    "GET knowledge/catch-up": () => ({
      proposals: [proposal({ id: "LES-8", text: "Send proofs to the author.", batch: "catch_up" })],
      made_at: "2026-10-09T14:00:00Z",
      waiting: 1,
      left_out: 3,
      most: 10,
    }),
  });
  const row = await screen.findByRole("region", { name: "Review" });
  expect(row).toHaveTextContent("Look over 2 things Helper learned from your earlier corrections");
  expect(row).toHaveTextContent("3 additional correction types exceeded the review limit and expired");
  await user.click(within(row).getByRole("button", { name: "Review" }));
  const drawer = await screen.findByRole("dialog", { name: "Learned from your earlier corrections" });
  expect(await within(drawer).findByText("Send proofs to the author.")).toBeInTheDocument();
  expect(within(drawer).getByText(/Reviewing 1 kind of correction/)).toBeInTheDocument();
  expect(within(drawer).getByText(/3 additional correction types are outside the 10-item review limit/)).toBeInTheDocument();
  expect(within(drawer).getByRole("button", { name: "Keep" })).toBeInTheDocument();
});

const INTERNAL = /Keep for|Filing notes|filing notes|selected kinds|incoming material|not instructions|Expires|task_kinds|applies_to/;

test("every kind of card says what changes, where it applies, where it came from and when and why it ends, in plain words", async () => {
  const user = userEvent.setup();
  show([line("learned", { count: 4, origins: { input: 2, correction: 2 } })], {
    "GET knowledge/proposals": () => ({
      proposals: [
        proposal({
          id: "LES-1",
          text: "Alerts like this about the website are work: make each one a to-do.",
          applies_to: { scope: "projects", projects: ["PRJ-1"], task_kinds: ["notes"] },
          evidence: { quote: "12 pages now return an error", source: "SRC-1" },
          came_from: "input",
          trust: "untrusted",
          learned_from: "input",
          expires_at: "2026-10-23T14:00:00Z",
        }),
        proposal({
          id: "GLO-1",
          kind: "glossary_entry",
          term: "Proof",
          text: "Proof means the final proof.",
          applies_to: { scope: "workspace" },
          came_from: "input",
          trust: "untrusted",
          learned_from: "input",
        }),
        proposal({
          id: "ROU-1",
          kind: "routing_entry",
          text: "Photos go to the designer.",
          applies_to: { scope: "workspace", task_kinds: ["sort-mail"] },
          came_from: "correction",
          evidence: null,
        }),
        proposal({
          id: "LES-5",
          text: "Make each website alert a to-do for a fix.",
          applies_to: { scope: "workspace", task_kinds: [] },
          came_from: "correction",
          learned_from: "person",
          evidence: { quote: "should be created as to-dos for fixes" },
        }),
      ],
      origins: { input: 2, correction: 2 },
      expired: 0,
    }),
  });
  await user.click(await screen.findByRole("button", { name: "Review" }));
  const drawer = await screen.findByRole("dialog", { name: "What Helper learned" });
  const rows = await within(drawer).findAllByRole("listitem");
  expect(rows).toHaveLength(4);
  for (const row of rows) expect(row.textContent).not.toMatch(INTERNAL);
  // Where it applies is a plain phrase, and where it came from is said.
  expect(rows[0]).toHaveTextContent("Applies to: things that come in for Spring launch");
  expect(rows[0]).toHaveTextContent("Goes away on");
  expect(rows[0]).toHaveTextContent("because it came from a message and not from you");
  expect(within(drawer).getAllByText("From outside · not instructions")).toHaveLength(1);
  expect(rows[2]).toHaveTextContent("Applies to: all your mail");
  expect(within(rows[2]).queryByText(/Goes away/)).toBeNull();
  expect(rows[1]).toHaveTextContent("Applies to: everything for all your projects");
});

test("the person's own typed words are theirs: marked as theirs, quoted as theirs, never from outside", async () => {
  const user = userEvent.setup();
  show([line("learned", { count: 1, origins: { correction: 1 } })], {
    "GET knowledge/proposals": () => ({
      proposals: [
        proposal({
          id: "LES-5",
          text: "Make each website alert a to-do for a fix.",
          applies_to: { scope: "workspace", task_kinds: [] },
          came_from: "correction",
          learned_from: "person",
          trust: "trusted",
          evidence: { quote: "should be created as to-dos for fixes" },
        }),
      ],
      origins: { correction: 1 },
      expired: 0,
    }),
  });
  await user.click(await screen.findByRole("button", { name: "Review" }));
  const row = (await screen.findByText("Make each website alert a to-do for a fix.")).closest("li")!;
  expect(within(row).getByText("Your own words")).toBeInTheDocument();
  expect(row).toHaveTextContent("You said: should be created as to-dos for fixes");
  expect(row.textContent).not.toMatch(/from outside|not from you|came from a message/i);
  expect(within(row).getByRole("button", { name: "Keep" })).toBeInTheDocument();
});

const offer = (over: Partial<S["PersonOfferView"]> = {}): S["PersonOfferView"] => ({
  id: "POFR-1",
  version: 1,
  name: "Dana Sample",
  address: "dana@example.com",
  why: "Writes to you every week and you reply: likely your accountant.",
  relation: "your accountant",
  sides: ["Work"],
  count: 12,
  ...over,
});

test("a person the assistant offered is a row of its own line on Today, and Keep adds them in one change with Undo (S-0534, H5-78)", async () => {
  const user = userEvent.setup();
  const calls = show([line("people_offers", { count: 1 })], {
    "GET knowledge/proposals": () => ({ people: [offer()], proposals: [], origins: {}, expired: 0 }),
    "POST knowledge/people/POFR-1/keep": () => ({ changeset: "CS-31" }),
    "POST changesets/CS-31/undo": () => ({ restored: [0], skipped: [] }),
  });
  expect(await screen.findByRole("region", { name: "People" })).toHaveTextContent("Pick whether to add the person found in your mail");
  await user.click(await screen.findByRole("button", { name: "Pick" }));
  const drawer = await screen.findByRole("dialog", { name: "People found in your mail" });
  const row = await within(drawer).findByRole("listitem");
  expect(row).toHaveTextContent("Dana Sample");
  expect(row).toHaveTextContent("Added as your accountant · On Work · 12 messages between you");
  await user.click(within(row).getByRole("button", { name: "Add to People" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST knowledge/people/POFR-1/keep")).toBe(true));
  expect(await screen.findByText("Added Dana Sample to People.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-31/undo")).toBe(true));
});

test("Not this one leaves the offered person out, with Undo", async () => {
  const user = userEvent.setup();
  const calls = show([line("people_offers", { count: 1 })], {
    "GET knowledge/proposals": () => ({ people: [offer({ relation: null, sides: [] })], proposals: [], origins: {}, expired: 0 }),
    "POST knowledge/people/POFR-1/not-this-one": () => ({ changeset: "CS-32" }),
    "POST changesets/CS-32/undo": () => ({ restored: [0], skipped: [] }),
  });
  await user.click(await screen.findByRole("button", { name: "Pick" }));
  const row = await within(await screen.findByRole("dialog", { name: "People found in your mail" })).findByRole("listitem");
  expect(row).not.toHaveTextContent("Added as");
  await user.click(within(row).getByRole("button", { name: "More actions for Dana Sample" }));
  await user.click(await screen.findByRole("menuitem", { name: "Not this one" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST knowledge/people/POFR-1/not-this-one")).toBe(true));
  expect(await screen.findByText("Left out Dana Sample. They won't be offered again.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.some((c) => c.route === "POST changesets/CS-32/undo")).toBe(true));
});

test("each row says in one line what it would mean and where it was seen, not only the bare word", async () => {
  const user = userEvent.setup();
  show([line("learned", { count: 1, origins: { input: 1 } })], {
    "GET knowledge/proposals": () => ({
      proposals: [term("GOFO", { text: "GOFO", meaning: "the fulfilment service that ships orders", messages: 4 })],
      origins: { input: 1 },
      expired: 0,
    }),
  });
  await user.click(await screen.findByRole("button", { name: "Review" }));
  const drawer = await screen.findByRole("dialog", { name: "What Helper learned" });
  const [row] = await within(drawer).findAllByRole("listitem");
  expect(row).toHaveTextContent("GOFO: the fulfilment service that ships orders");
  expect(row).toHaveTextContent("Seen in 4 messages");
});
