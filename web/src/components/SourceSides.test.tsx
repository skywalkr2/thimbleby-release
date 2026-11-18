import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { RestartProvider } from "../lib/restart";
import { Refuse, fakeApi, renderApp } from "../test-utils";
import { SourceSides } from "./SourceSides";

// The tick boxes on Connections that say which sides a connection serves: a tick is saved at once as the source's sides, queued
// behind one still saving, never lost to a settings change made meanwhile, and a tick that couldn't be saved says so.

const PERSONAL = "PRJ-1";
const EMPLOYER = "Test Employer";
const SHOP = "Test Shop";
const SIDES = [
  { project: "PRJ-2", kind: "job", name: EMPLOYER, removable: false, filed: 0 },
  { project: "PRJ-3", kind: "business", name: SHOP, removable: false, filed: 0 },
] as S["SideView"][];
const SOURCE = { id: "s1", label: "Your inbox", reads: ["mail"], sides: [] } as unknown as S["WatchSourceView"];

type Post = (body: { fingerprint: string; changes: { "watch.sources": Array<Record<string, unknown>> } }) => unknown;

function serve(post: Post = () => undefined, delays = { read: 0, write: 0 }) {
  let sources: Array<Record<string, unknown>> = [{ id: "s1", connector: "x/mail", label: "Your inbox", settings: {} }];
  const fingerprint = () => `fp-${JSON.stringify(sources)}`;
  const later = (ms: number) => new Promise((done) => setTimeout(done, ms));
  const state = { get sources() { return sources; } };
  fakeApi({
    "GET settings": async () => {
      const answer = {
        fingerprint: fingerprint(),
        items: [{ key: "watch.sources", file: "watch", group: "watch", description: "", type: "other", options: [], value: sources, default: [], source: "file", locked: false, basic: false, editable: false }],
      };
      if (delays.read) await later(delays.read);
      return answer;
    },
    "POST settings": async (body) => {
      if (delays.write) await later(delays.write);
      const sent = body as Parameters<Post>[0];
      if (sent.fingerprint !== fingerprint()) return new Refuse(409, "The settings changed since you opened them. Look again, then save.");
      const answer = await post(sent);
      if (answer instanceof Refuse) return answer;
      const before = sources;
      sources = sent.changes["watch.sources"];
      return { changes: [{ key: "watch.sources", before, after: sources, was_default: false, is_default: false }], fingerprint: fingerprint(), needs_restart: false };
    },
  });
  return state;
}

function show() {
  return renderApp(
    <RestartProvider hellos={1} pollSeconds={0.05} doneSeconds={0.05}>
      <SourceSides sources={[SOURCE]} label="Your inbox" personal={PERSONAL} sides={SIDES} />
    </RestartProvider>,
  );
}

const group = () => screen.findByRole("group", { name: "Your inbox: who is it for?" });

test("a tick is saved at once as the source's sides, in the order of the choices, and the line says how it stands", async () => {
  const user = userEvent.setup();
  const state = serve();
  show();
  const inbox = await group();
  expect(within(inbox).getAllByRole("checkbox").map((b) => (b.closest("label") as HTMLElement).textContent)).toEqual(["Personal", EMPLOYER, SHOP]);
  await user.click(within(inbox).getByRole("checkbox", { name: EMPLOYER }));
  await user.click(within(inbox).getByRole("checkbox", { name: "Personal" }));
  await waitFor(() => expect((state.sources[0] as { sides?: string[] }).sides).toEqual([PERSONAL, "PRJ-2"]));
  expect(await within(inbox).findByRole("status")).toHaveTextContent(`Your inbox is for Personal and ${EMPLOYER}.`);
});

test("a second tick made while a save runs is queued and saved after it, so neither is lost", async () => {
  const user = userEvent.setup();
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  const saved: string[][] = [];
  let first = true;
  serve(async (body) => {
    saved.push(body.changes["watch.sources"][0].sides as string[]);
    if (first) {
      first = false;
      await gate;
    }
  });
  show();
  const inbox = await group();
  await user.click(within(inbox).getByRole("checkbox", { name: "Personal" }));
  expect(within(inbox).getByRole("checkbox", { name: EMPLOYER })).toBeEnabled();
  await user.click(within(inbox).getByRole("checkbox", { name: EMPLOYER }));
  release();
  await waitFor(() => expect(saved).toHaveLength(2));
  expect(saved).toEqual([[PERSONAL], [PERSONAL, "PRJ-2"]]);
  expect(await within(inbox).findByRole("status")).toHaveTextContent(`Your inbox is for Personal and ${EMPLOYER}.`);
});

test("quick ticks, on a server that checks the fingerprint and answers after a while, all end up saved as the boxes show", async () => {
  const user = userEvent.setup();
  const state = serve(undefined, { read: 15, write: 25 });
  const app = show();
  const inbox = await group();
  // The app's live stream asks for everything again whenever the server says something changed, at any moment.
  const stream = setInterval(() => void app.client.invalidateQueries(), 9);
  await user.click(within(inbox).getByRole("checkbox", { name: "Personal" }));
  await user.click(within(inbox).getByRole("checkbox", { name: EMPLOYER }));
  await user.click(within(inbox).getByRole("checkbox", { name: SHOP }));
  await user.click(within(inbox).getByRole("checkbox", { name: SHOP }));
  const shown = () => within(inbox).getAllByRole("checkbox").map((b) => (b as HTMLInputElement).checked);
  await waitFor(() => expect((state.sources[0] as { sides?: string[] }).sides).toEqual([PERSONAL, "PRJ-2"]), { timeout: 3000 });
  await waitFor(() => expect(shown()).toEqual([true, true, false]));
  expect(within(inbox).queryByRole("alert")).toBeNull();
  clearInterval(stream);
});

test("ticking and unticking quickly ends with a message that matches the boxes", async () => {
  const user = userEvent.setup();
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let first = true;
  serve(async () => {
    if (first) {
      first = false;
      await gate;
    }
  });
  show();
  const inbox = await group();
  const personal = within(inbox).getByRole("checkbox", { name: "Personal" });
  await user.click(personal);
  await user.click(personal);
  release();
  await waitFor(() => expect(within(inbox).getByRole("status")).toHaveTextContent("Your inbox isn't marked for any of them."));
  expect(within(inbox).getAllByRole("checkbox").every((b) => !(b as HTMLInputElement).checked)).toBe(true);
});

test("a tick that couldn't be saved names its box and offers Try again, which saves it", async () => {
  const user = userEvent.setup();
  let fail = true;
  const state = serve(async () => (fail ? new Refuse(500, "") : undefined));
  show();
  const inbox = await group();
  await user.click(within(inbox).getByRole("checkbox", { name: EMPLOYER }));
  const problem = await within(inbox).findByRole("alert");
  expect(problem).toHaveTextContent(`Your inbox: couldn't save ${EMPLOYER}.`);
  expect(within(inbox).getByRole("checkbox", { name: EMPLOYER })).not.toBeChecked();
  fail = false;
  await user.click(within(problem).getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(within(inbox).getByRole("checkbox", { name: EMPLOYER })).toBeChecked());
  expect((state.sources[0] as { sides: string[] }).sides).toEqual(["PRJ-2"]);
  expect(within(inbox).queryByRole("alert")).toBeNull();
});
