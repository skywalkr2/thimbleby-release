import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fakeApi, renderApp } from "../test-utils";
import { ApiError, answeredWrites } from "./api";
import { clearIfUnchanged } from "./clear-if-unchanged";
import { vi } from "vitest";
import { ActScope, useAct } from "./act";
import { invalidateFor, noteOwnRefresh } from "./live";
import { broadRefreshes, positionAnsweredSince, runWrite } from "./write";

fakeApi({});

/** A call that stays open until the test lets it answer. */
function held<T>() {
  let release: (v: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => (release = resolve));
  return { promise, release };
}

test("two writes with the same key go out in order: the second leaves only after the first has answered, even a failed one", async () => {
  const client = new QueryClient();
  const first = held<string>();
  const order: string[] = [];
  const a = runWrite(client, () => (order.push("a sent"), first.promise), { key: "settings" });
  const b = runWrite(
    client,
    () => {
      order.push("b sent");
      return Promise.resolve("b");
    },
    { key: "settings", touches: [] },
  );
  const other = runWrite(client, () => (order.push("other sent"), Promise.resolve("o")), { key: "elsewhere", touches: [] });
  await other;
  // A different key never waits; the same key does.
  expect(order).toEqual(["a sent", "other sent"]);
  first.release("a");
  await a;
  expect(await b).toBe("b");
  expect(order).toEqual(["a sent", "other sent", "b sent"]);
});

test("a failed write does not stop the next one with its key", async () => {
  const client = new QueryClient();
  const a = runWrite(client, () => Promise.reject(new Error("no")), { key: "k", touches: [] });
  const b = runWrite(client, () => Promise.resolve("ok"), { key: "k", touches: [] });
  await expect(a).rejects.toThrow("no");
  expect(await b).toBe("ok");
});

function Reader(props: { family: string; fetches: Record<string, number> }) {
  useQuery({
    queryKey: [props.family],
    queryFn: () => {
      props.fetches[props.family] = (props.fetches[props.family] ?? 0) + 1;
      return Promise.resolve(props.fetches[props.family]);
    },
  });
  return null;
}

test("after a write only the families it names read again; another family's screen does not", async () => {
  const fetches: Record<string, number> = {};
  const view = renderApp(
    <>
      <Reader family="people" fetches={fetches} />
      <Reader family="today" fetches={fetches} />
    </>,
  );
  await waitFor(() => expect(fetches).toEqual({ people: 1, today: 1 }));
  await runWrite(view.client, () => Promise.resolve(1), { touches: ["people"] });
  await waitFor(() => expect(fetches.people).toBe(2));
  expect(fetches.today).toBe(1);
});

test("a write that names kinds reads again the families that show them, and one that names nothing reads everything and is counted", async () => {
  const fetches: Record<string, number> = {};
  const view = renderApp(
    <>
      <Reader family="people" fetches={fetches} />
      <Reader family="today" fetches={fetches} />
    </>,
  );
  await waitFor(() => expect(fetches).toEqual({ people: 1, today: 1 }));
  const before = broadRefreshes.count;
  await runWrite(view.client, () => Promise.resolve(1), { kinds: ["look"] });
  await waitFor(() => expect(fetches.today).toBe(2));
  expect(fetches.people).toBe(1);
  expect(broadRefreshes.count).toBe(before);
  await runWrite(view.client, () => Promise.resolve(1));
  await waitFor(() => expect(fetches).toEqual({ people: 2, today: 3 }));
  expect(broadRefreshes.count).toBe(before + 1);
});

test("the toast for a write shows before any screen has finished reading again", async () => {
  const user = userEvent.setup();
  const slow = held<string>();
  let calls = 0;
  function Screen() {
    useQuery({ queryKey: ["slow"], queryFn: () => (++calls === 1 ? Promise.resolve("first") : slow.promise) });
    const act = useAct();
    return (
      <button type="button" onClick={() => void act(() => Promise.resolve("x"), () => ({ message: "Saved." }), undefined, { touches: ["slow"] })}>
        Save
      </button>
    );
  }
  renderApp(<Screen />);
  await waitFor(() => expect(calls).toBe(1));
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await within(screen.getByRole("region", { name: "Notifications" })).findByText("Saved.")).toBeInTheDocument();
  expect(calls).toBe(2);
  slow.release("done");
});

test("a form keeps what was typed while its save was on its way", async () => {
  const user = userEvent.setup();
  const answer = held<string>();
  function Form() {
    const [text, setText] = useState("");
    const act = useAct();
    return (
      <>
        <input aria-label="Note" value={text} onChange={(e) => setText(e.target.value)} />
        <button
          type="button"
          onClick={() => {
            const sent = text;
            void act(() => answer.promise, () => ({ message: "Saved." }), undefined, { key: "note", touches: [] }).then(() => clearIfUnchanged(setText, sent));
          }}
        >
          Add
        </button>
      </>
    );
  }
  renderApp(<Form />);
  await user.type(screen.getByLabelText("Note"), "one");
  await user.click(screen.getByRole("button", { name: "Add" }));
  await user.type(screen.getByLabelText("Note"), " two");
  answer.release("ok");
  await screen.findByText("Saved.");
  await waitFor(() => expect(screen.getByLabelText("Note")).toHaveValue("one two"));
});

test("the live event that echoes the person's own write skips a read in flight, but never one already finished: another writer's change of the same kind is read", async () => {
  const fetches: Record<string, number> = {};
  const answers: Array<() => void> = [];
  function Slow() {
    useQuery({
      queryKey: ["today"],
      queryFn: () => {
        fetches.today = (fetches.today ?? 0) + 1;
        // The first read answers at once; later ones wait until the test lets them.
        return fetches.today === 1 ? Promise.resolve(1) : new Promise<number>((resolve) => answers.push(() => resolve(fetches.today ?? 0)));
      },
    });
    return null;
  }
  const view = renderApp(<Slow />);
  await waitFor(() => expect(fetches.today).toBe(1));
  const writing = runWrite(view.client, () => Promise.resolve(1), { kinds: ["look"] });
  await waitFor(() => expect(fetches.today).toBe(2));
  // The person's own refresh is still reading: the echo of the same write does not start a second read.
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"] }));
  expect(fetches.today).toBe(2);
  answers.shift()?.();
  await writing;
  // The write answered before its refresh; wait for the refresh itself to finish.
  await waitFor(() => expect(view.client.isFetching()).toBe(0));
  // The refresh has finished. The assistant writes the same kind a moment later: that event reads.
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"] }));
  await waitFor(() => expect(fetches.today).toBe(3));
  answers.shift()?.();
  // Work of another kind reads too, and so does the same echo long after.
  invalidateFor(view.client, JSON.stringify({ kinds: ["look", "changes"] }));
  await waitFor(() => expect(fetches.today).toBe(4));
  answers.shift()?.();
  noteOwnRefresh(view.client, ["look"], Date.now() - 60_000);
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"] }));
  await waitFor(() => expect(fetches.today).toBe(5));
  answers.shift()?.();
});

test("the live event of the person's own write, which names a ledger position no later than the answer's, reads nothing again, even a read that has finished; an event past it reads", async () => {
  const fetches: Record<string, number> = {};
  function Today() {
    useQuery({ queryKey: ["today"], queryFn: () => Promise.resolve((fetches.today = (fetches.today ?? 0) + 1)) });
    return null;
  }
  const view = renderApp(<Today />);
  await waitFor(() => expect(fetches.today).toBe(1));
  noteOwnRefresh(view.client, ["look"], Date.now(), 10);
  // Its news ends at the answer's position: the write's own reads had it.
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"], position: 10 }));
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"], position: 7 }));
  await waitFor(() => expect(view.client.isFetching()).toBe(0));
  expect(fetches.today).toBe(1);
  // Past it, another writer wrote the same kind: that reads.
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"], position: 11 }));
  await waitFor(() => expect(fetches.today).toBe(2));
  // An event that names no position (an older server) reads, as it did.
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"] }));
  await waitFor(() => expect(fetches.today).toBe(3));
});

test("the stream's news of the person's own write that comes before the write's answer is not read again, and news past the answer's position is", async () => {
  const fetches: Record<string, number> = {};
  function Today() {
    useQuery({ queryKey: ["today"], queryFn: () => Promise.resolve((fetches.today = (fetches.today ?? 0) + 1)) });
    return null;
  }
  const view = renderApp(<Today />);
  await waitFor(() => expect(fetches.today).toBe(1));
  let answer: () => void = () => undefined;
  const writing = runWrite(
    view.client,
    () =>
      new Promise<number>((resolve) => {
        answer = () => {
          answeredWrites.seq += 1;
          answeredWrites.entries.push({ seq: answeredWrites.seq, kinds: ["look"], position: 20 });
          resolve(1);
        };
      }),
  );
  // The stream tells of the write while the write is still out.
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"], position: 20 }));
  expect(fetches.today).toBe(1);
  answer();
  await writing;
  await waitFor(() => expect(fetches.today).toBe(2));
  await waitFor(() => expect(view.client.isFetching()).toBe(0));
  // Only the write's own reads were made.
  expect(fetches.today).toBe(2);
  // News past the answer's position reads.
  invalidateFor(view.client, JSON.stringify({ kinds: ["look"], position: 21 }));
  await waitFor(() => expect(fetches.today).toBe(3));
});

test("a write keeps the ledger position its answer named, for the event that echoes it", async () => {
  const view = renderApp(<span />);
  const since = answeredWrites.seq;
  answeredWrites.seq += 1;
  answeredWrites.entries.push({ seq: answeredWrites.seq, kinds: ["look"], position: 12 });
  expect(positionAnsweredSince(since)).toBe(12);
  answeredWrites.seq += 1;
  answeredWrites.entries.push({ seq: answeredWrites.seq, kinds: ["look"], position: null });
  expect(positionAnsweredSince(since)).toBeNull();
  expect(view.client).toBeTruthy();
});

test("a write is done at the server's answer: it never waits for the reads that follow it", async () => {
  let release: () => void = () => undefined;
  function Slow() {
    useQuery({ queryKey: ["today"], queryFn: () => new Promise<number>((resolve) => (release = () => resolve(2))) });
    return null;
  }
  const view = renderApp(<Slow />);
  release();
  await waitFor(() => expect(view.client.isFetching()).toBe(0));
  let done = false;
  const writing = runWrite(view.client, () => Promise.resolve("saved"), { kinds: ["look"] }).then((r) => {
    done = true;
    return r;
  });
  await expect(writing).resolves.toBe("saved");
  // The screen's read is still out: the write did not wait for it.
  expect(done).toBe(true);
  expect(view.client.isFetching()).toBeGreaterThan(0);
  release();
});

test("a write that names nothing reads again only what the server said it changed", async () => {
  const fetches: Record<string, number> = {};
  function Both() {
    useQuery({ queryKey: ["today"], queryFn: () => ((fetches.today = (fetches.today ?? 0) + 1), Promise.resolve(1)) });
    useQuery({ queryKey: ["settings"], queryFn: () => ((fetches.settings = (fetches.settings ?? 0) + 1), Promise.resolve(1)) });
    return null;
  }
  const view = renderApp(<Both />);
  await waitFor(() => expect(fetches.today).toBe(1));
  await waitFor(() => expect(fetches.settings).toBe(1));
  const broad = broadRefreshes.count;
  // The server's answer names the kinds the write changed.
  await runWrite(view.client, async () => {
    answeredWrites.seq += 1;
    answeredWrites.entries.push({ seq: answeredWrites.seq, kinds: ["action"], position: null });
    return 1;
  });
  await waitFor(() => expect(fetches.today).toBe(2));
  expect(fetches.settings).toBe(1);
  expect(broadRefreshes.count).toBe(broad);
});

// H1-01 and H1-05: a double press sends the change once.
test("a second press of the same action while the first is out sends nothing and says nothing", async () => {
  const user = userEvent.setup();
  const answer = held<string>();
  const run = vi.fn(() => answer.promise);
  function Button1() {
    const act = useAct();
    return (
      <button type="button" onClick={() => void act(run, () => ({ message: "Closed." }), undefined, { once: "close:1" })}>
        Close it
      </button>
    );
  }
  renderApp(<Button1 />);
  await user.dblClick(screen.getByRole("button", { name: "Close it" }));
  answer.release("done");
  expect(await within(screen.getByRole("region", { name: "Notifications" })).findByText("Closed.")).toBeInTheDocument();
  expect(run).toHaveBeenCalledTimes(1);
  expect(within(screen.getByRole("region", { name: "Notifications" })).queryAllByText("Closed.")).toHaveLength(1);
});

test("inside one part of a screen (an ActScope) a second action while the first is out is ignored, and another part is not held up", async () => {
  const user = userEvent.setup();
  const answer = held<string>();
  const first = vi.fn(() => answer.promise);
  const second = vi.fn(() => Promise.resolve("two"));
  const other = vi.fn(() => Promise.resolve("other"));
  function InScope(props: { label: string; run: () => Promise<string> }) {
    const act = useAct();
    return (
      <button type="button" onClick={() => void act(props.run, () => ({ message: `${props.label} done.` }))}>
        {props.label}
      </button>
    );
  }
  renderApp(
    <>
      <ActScope.Provider value="line-1">
        <InScope label="Close" run={first} />
        <InScope label="Keep" run={second} />
      </ActScope.Provider>
      <ActScope.Provider value="line-2">
        <InScope label="Other" run={other} />
      </ActScope.Provider>
    </>,
  );
  await user.click(screen.getByRole("button", { name: "Close" }));
  await user.click(screen.getByRole("button", { name: "Keep" }));
  await user.click(screen.getByRole("button", { name: "Other" }));
  expect(second).not.toHaveBeenCalled();
  expect(other).toHaveBeenCalledTimes(1);
  answer.release("done");
  await waitFor(() => expect(within(screen.getByRole("region", { name: "Notifications" })).getByText("Close done.")).toBeInTheDocument());
});

test("a refusal of 'changed since you looked' for the person's own second press just after it worked is silent, and any other refusal is said", async () => {
  const user = userEvent.setup();
  const clash = new ApiError(409, "That changed since you last looked. It is up to date now, so look again and choose again.", "look-again");
  const run = vi.fn<() => Promise<string>>().mockResolvedValueOnce("ok").mockRejectedValueOnce(clash).mockRejectedValueOnce(new ApiError(409, "Pick a person first."));
  function Press() {
    const act = useAct();
    return (
      <button type="button" onClick={() => void act(run, () => ({ message: "Done." }), undefined, { once: "x" })}>
        Press
      </button>
    );
  }
  renderApp(<Press />);
  await user.click(screen.getByRole("button", { name: "Press" }));
  await within(screen.getByRole("region", { name: "Notifications" })).findByText("Done.");
  await user.click(screen.getByRole("button", { name: "Press" }));
  await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
  expect(within(screen.getByRole("region", { name: "Notifications" })).queryByText(/didn't work/)).toBeNull();
  await user.click(screen.getByRole("button", { name: "Press" }));
  expect(await within(screen.getByRole("region", { name: "Notifications" })).findByText(/Pick a person first/)).toBeInTheDocument();
});

test("an act that changes no record reads the screens it names, even when its answer carries kinds another writer changed meanwhile", async () => {
  const fetches: Record<string, number> = {};
  function Screens() {
    useQuery({ queryKey: ["sign-ins"], queryFn: () => Promise.resolve((fetches.signIns = (fetches.signIns ?? 0) + 1)) });
    return null;
  }
  let act: ReturnType<typeof useAct> = (() => Promise.resolve(undefined)) as unknown as ReturnType<typeof useAct>;
  function Grab() {
    act = useAct();
    return null;
  }
  const view = renderApp(
    <>
      <Screens />
      <Grab />
    </>,
  );
  await waitFor(() => expect(fetches.signIns).toBe(1));
  await act(
    () => {
      answeredWrites.seq += 1;
      answeredWrites.entries.push({ seq: answeredWrites.seq, kinds: ["request"], position: 1474 });
      return Promise.resolve(1);
    },
    undefined,
    undefined,
    { also: ["sign-ins"] },
  );
  await waitFor(() => expect(fetches.signIns).toBe(2));
  await waitFor(() => expect(view.client.isFetching()).toBe(0));
});
