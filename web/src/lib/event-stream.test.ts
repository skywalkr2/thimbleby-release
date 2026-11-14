import { AuthEventSource } from "./event-stream";
import { resetSession } from "./session";

function streamOf(text: string, keepOpen = false): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      if (!keepOpen) controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

beforeEach(() => {
  resetSession();
  window.localStorage.setItem("cockpit.session", "kept-session");
});
afterEach(() => {
  vi.unstubAllGlobals();
  resetSession();
});

test("the stream is read with the session as a header, never a cookie, and its named events arrive", async () => {
  const fetchMock = vi.fn(async () => streamOf('event: hello\ndata: 3\n\n: keep-alive\n\nevent: changed\ndata: {"kinds": ["person"]}\n\n', true));
  vi.stubGlobal("fetch", fetchMock);
  const stream = new AuthEventSource("api/events");
  const seen: Array<[string, string]> = [];
  stream.addEventListener("hello", (e) => seen.push(["hello", e.data]));
  stream.addEventListener("changed", (e) => seen.push(["changed", e.data]));
  await vi.waitFor(() => expect(seen).toHaveLength(2));
  expect(seen).toEqual([["hello", "3"], ["changed", '{"kinds": ["person"]}']]);
  expect(stream.readyState).toBe(1);
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("api/events");
  expect(init.headers).toMatchObject({ Authorization: "Bearer kept-session" });
  expect(init.credentials).toBeUndefined();
  stream.close();
  expect(stream.readyState).toBe(2);
});

test("a refused sign-in closes the stream for good and says so", async () => {
  const fetchMock = vi.fn(async () => new Response("{}", { status: 401 }));
  vi.stubGlobal("fetch", fetchMock);
  const stream = new AuthEventSource("api/events");
  const failed = vi.fn();
  stream.onerror = failed;
  await vi.waitFor(() => expect(stream.readyState).toBe(2));
  expect(failed).toHaveBeenCalled();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("a stream that drops says so and is tried again, as the browser's own would", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout"] });
  const fetchMock = vi.fn(async () => streamOf(fetchMock.mock.calls.length === 1 ? "event: hello\ndata: 1\n\n" : "event: hello\ndata: 2\n\n"));
  vi.stubGlobal("fetch", fetchMock);
  const stream = new AuthEventSource("api/events");
  const hellos: string[] = [];
  const dropped = vi.fn();
  stream.addEventListener("hello", (e) => hellos.push(e.data));
  stream.onerror = dropped;
  await vi.waitFor(() => expect(dropped).toHaveBeenCalledTimes(1));
  expect(stream.readyState).toBe(0);
  await vi.advanceTimersByTimeAsync(3100);
  await vi.waitFor(() => expect(hellos).toEqual(["1", "2"]));
  stream.close();
  vi.useRealTimers();
});
