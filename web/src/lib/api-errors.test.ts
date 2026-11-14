import { api, ApiError } from "./api";
import { problemText } from "./problem";

const t = (key: string, vars: Record<string, string | number> = {}) =>
  ({
    "error.failed": `That didn't work. ${vars.detail ?? ""}`,
    "error.failed_plain": "That didn't work. Try again in a moment.",
    "error.signed_out": "Signed out.",
  })[key] ?? key;

function answer(status: number, body: string, json = true) {
  globalThis.fetch = vi.fn(async () => ({
    ok: false,
    status,
    headers: new Headers(),
    json: async () => {
      if (!json) throw new Error("not json");
      return JSON.parse(body);
    },
  })) as unknown as typeof fetch;
}

async function failure(): Promise<ApiError> {
  try {
    await api.runtimeConfig();
  } catch (err) {
    return err as ApiError;
  }
  throw new Error("expected a failure");
}

test("a server fault never puts its own text on screen", async () => {
  answer(500, JSON.stringify({ detail: "KeyError: 'x' at engine/applier.py line 12" }));
  const err = await failure();
  expect(err.detail).toBe("");
  expect(problemText(err, t)).toBe("That didn't work. Try again in a moment.");
});

test("a framework's stock words are not shown, whatever the status", async () => {
  for (const [status, detail] of [[404, "Not Found"], [405, "Method Not Allowed"], [400, "Bad Request"]] as const) {
    answer(status, JSON.stringify({ detail }));
    expect(problemText(await failure(), t)).toBe("That didn't work. Try again in a moment.");
  }
});

test("a refusal's plain words still come through, and an unreadable answer is the plain message", async () => {
  answer(422, JSON.stringify({ detail: "Use at most 80 characters." }));
  expect(problemText(await failure(), t)).toBe("Use at most 80 characters.");
  answer(502, "<html>Bad gateway</html>", false);
  expect(problemText(await failure(), t)).toBe("That didn't work. Try again in a moment.");
});

test("a signed-out answer is always the sheet's own message, not the server's sentence", async () => {
  answer(401, JSON.stringify({ error: "Open the link the app printed when it started to sign in on this computer." }));
  const err = await failure();
  expect(err.detail).toBe("");
  expect(problemText(err, t)).toBe("Signed out.");
});
