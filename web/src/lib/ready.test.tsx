import "@testing-library/jest-dom/vitest";
import { act, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { trackRequest, ReadyMark } from "./ready";
import { invalidateFor } from "./live";

function Screen(props: { answer: Promise<string> }) {
  const q = useQuery({ queryKey: ["x"], queryFn: () => props.answer });
  return <p>{q.data ?? "waiting"}</p>;
}

test("the main region is marked ready only when its reads have answered and no request is pending", async () => {
  location.hash = "#today";
  let answer!: (v: string) => void;
  const promise = new Promise<string>((r) => (answer = r));
  const client = new QueryClient();
  const { container } = render(
    <QueryClientProvider client={client}>
      <main id="main">
        <Screen answer={promise} />
        <ReadyMark />
      </main>
    </QueryClientProvider>,
  );
  const main = container.querySelector("main")!;
  expect(main).not.toHaveAttribute("data-ready");
  answer("done");
  await waitFor(() => expect(main).toHaveAttribute("data-ready", "#today"));
  // A request in flight takes the mark off, and its end puts it back.
  const end = trackRequest();
  await waitFor(() => expect(main).not.toHaveAttribute("data-ready"));
  end();
  await waitFor(() => expect(main).toHaveAttribute("data-ready", "#today"));
  // A new address is marked at that address, never left at the old one.
  act(() => {
    location.hash = "#work/open";
  });
  await waitFor(() => expect(main).toHaveAttribute("data-ready", "#work/open"));
});

test("a re-read already on its way when the screen becomes ready (the refresh a connecting event stream asks for) does not hold the mark", async () => {
  location.hash = "#today";
  const client = new QueryClient();
  // The screen already holds this data, and reading it again never answers.
  client.setQueryData(["held"], "known");
  function Reads() {
    const first = useQuery({ queryKey: ["fresh"], queryFn: () => Promise.resolve("first") });
    const again = useQuery({ queryKey: ["held"], queryFn: () => new Promise<string>(() => undefined), staleTime: 0 });
    return (
      <p>
        {first.data ?? "waiting"} {again.data}
      </p>
    );
  }
  const { container } = render(
    <QueryClientProvider client={client}>
      <main id="main">
        <Reads />
        <ReadyMark />
      </main>
    </QueryClientProvider>,
  );
  const main = container.querySelector("main")!;
  await waitFor(() => expect(main).toHaveAttribute("data-ready", "#today"));
  expect(client.isFetching()).toBe(1);
});

test("once the screen is ready, a read again of its data (the refresh after a write) holds the mark until it answers", async () => {
  location.hash = "#work/open";
  let calls = 0;
  let again!: (v: string) => void;
  const client = new QueryClient();
  function Reads() {
    const q = useQuery({
      queryKey: ["z"],
      queryFn: () => {
        calls += 1;
        return calls === 1 ? Promise.resolve("first") : new Promise<string>((r) => (again = r));
      },
    });
    return <p>{q.data ?? "waiting"}</p>;
  }
  const { container } = render(
    <QueryClientProvider client={client}>
      <main id="main">
        <Reads />
        <ReadyMark />
      </main>
    </QueryClientProvider>,
  );
  const main = container.querySelector("main")!;
  await waitFor(() => expect(main).toHaveAttribute("data-ready", "#work/open"));
  act(() => {
    void client.invalidateQueries();
  });
  await waitFor(() => expect(main).not.toHaveAttribute("data-ready"));
  act(() => again("changed"));
  await waitFor(() => expect(main).toHaveAttribute("data-ready", "#work/open"));
});

test("reads the event stream starts for another's change do not keep the mark off, and this page's own re-read of the same data does", async () => {
  location.hash = "#work/stages";
  let calls = 0;
  let again!: (v: string) => void;
  const client = new QueryClient();
  function Reads() {
    const q = useQuery({
      queryKey: ["z"],
      queryFn: () => {
        calls += 1;
        return calls === 1 ? Promise.resolve("first") : new Promise<string>((r) => (again = r));
      },
    });
    return <p>{q.data ?? "waiting"}</p>;
  }
  const { container } = render(
    <QueryClientProvider client={client}>
      <main id="main">
        <Reads />
        <ReadyMark />
      </main>
    </QueryClientProvider>,
  );
  const main = container.querySelector("main")!;
  await waitFor(() => expect(main).toHaveAttribute("data-ready", "#work/stages"));
  // Another window's change: the page reads again, and stays marked while that read is still out (it never answers here).
  act(() => invalidateFor(client, "{}"));
  expect(client.isFetching()).toBe(1);
  // Let the page see the read start (the cache tells it on the next turn), then the mark is still there.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
  });
  expect(main).toHaveAttribute("data-ready", "#work/stages");
  // The page's own write then reads the same data again: that read restarts the one on its way, and holds the mark until it answers.
  act(() => {
    void client.invalidateQueries();
  });
  await waitFor(() => expect(main).not.toHaveAttribute("data-ready"));
  act(() => again("changed"));
  await waitFor(() => expect(main).toHaveAttribute("data-ready", "#work/stages"));
});
