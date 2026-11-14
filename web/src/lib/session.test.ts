import { authHeaders, resetSession, sessionKnown, sessionReady } from "./session";

afterEach(() => {
  vi.unstubAllGlobals();
  resetSession();
  window.history.replaceState(null, "", "/");
});

test("the install token in the address is traded for a session once, taken out of the address, and the session is the bearer after", async () => {
  window.history.replaceState(null, "", "/admin/?token=install-1&keep=1#today");
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ session: "made-by-server" }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await sessionReady();
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("api/session");
  expect(init.method).toBe("POST");
  expect(init.headers).toEqual({ Authorization: "Bearer install-1" });
  expect(window.location.search).toBe("?keep=1");
  expect(window.location.hash).toBe("#today");
  expect(authHeaders()).toEqual({ Authorization: "Bearer made-by-server" });
  // Kept in this page's own storage; the install token is not.
  expect(window.localStorage.getItem("cockpit.session")).toBe("made-by-server");
  expect(JSON.stringify(window.localStorage)).not.toContain("install-1");
  await sessionReady();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("no token in the address means no call, and a refused token leaves no session", async () => {
  const none = vi.fn();
  vi.stubGlobal("fetch", none);
  await sessionReady();
  expect(none).not.toHaveBeenCalled();
  expect(authHeaders()).toEqual({});

  resetSession();
  window.history.replaceState(null, "", "/?token=wrong");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  await sessionReady();
  expect(authHeaders()).toEqual({});
  expect(window.location.search).toBe("");
});

test("an unreachable app leaves the page without a session and never throws", async () => {
  window.history.replaceState(null, "", "/?token=install-2");
  vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
  await expect(sessionReady()).resolves.toBeUndefined();
  expect(authHeaders()).toEqual({});
});

test("a call goes out at once when there is no token to trade, and waits only while a trade is under way", async () => {
  expect(sessionKnown()).toBe(true);
  window.history.replaceState(null, "", "/?token=install-2");
  let finish: (r: Response) => void = () => undefined;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => (finish = resolve))));
  const opening = sessionReady();
  expect(sessionKnown()).toBe(false);
  finish(new Response(JSON.stringify({ session: "s" }), { status: 200 }));
  await opening;
  expect(sessionKnown()).toBe(true);
});
