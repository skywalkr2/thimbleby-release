import { api, ApiError, setRequestTimeouts } from "./api";
import { problemText } from "./problem";

const t = (key: string) => ({ "error.failed_plain": "That didn't work. Try again in a moment." })[key] ?? key;

/** A server that never answers: the request ends only when it is aborted. */
function silent() {
  globalThis.fetch = vi.fn((_url: unknown, init?: RequestInit) =>
    new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }),
  ) as unknown as typeof fetch;
}

async function outcome(run: () => Promise<unknown>): Promise<unknown> {
  return run().then(
    () => "answered",
    (err) => err,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  setRequestTimeouts(30, 300);
});
afterEach(() => vi.useRealTimers());

test("a request that never answers ends in the plain message instead of hanging", async () => {
  silent();
  const pending = outcome(() => api.status());
  await vi.advanceTimersByTimeAsync(29_000);
  let settled = false;
  void pending.then(() => (settled = true));
  await vi.advanceTimersByTimeAsync(0);
  expect(settled).toBe(false);
  await vi.advanceTimersByTimeAsync(1_500);
  const err = (await pending) as ApiError;
  expect(err).toBeInstanceOf(ApiError);
  expect(err.detail).toBe("");
  expect(problemText(err, t)).toBe("That didn't work. Try again in a moment.");
});

test("the wait is the setting's, and a call that waits on purpose has the longer one", async () => {
  silent();
  setRequestTimeouts(5, 60);
  const short = outcome(() => api.status());
  await vi.advanceTimersByTimeAsync(5_100);
  expect(await short).toBeInstanceOf(ApiError);
  const long = outcome(() => api.testAi());
  let settled = false;
  void long.then(() => (settled = true));
  await vi.advanceTimersByTimeAsync(59_000);
  expect(settled).toBe(false);
  await vi.advanceTimersByTimeAsync(1_500);
  expect(await long).toBeInstanceOf(ApiError);
});

test("an answer that arrives in time is not cut off, and a refused connection stays its own error", async () => {
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, headers: new Headers(), json: async () => ({ ok: 1 }) })) as unknown as typeof fetch;
  expect(await api.status()).toEqual({ ok: 1 });
  globalThis.fetch = vi.fn(async () => {
    throw new TypeError("network down");
  }) as unknown as typeof fetch;
  expect(await outcome(() => api.status())).toBeInstanceOf(TypeError);
});
