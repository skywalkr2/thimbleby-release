import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { announceSignIn, useSignInWindow } from "./sign-in-window";
import { WordingProvider } from "./wording";
import { fakeApi } from "../test-utils";

// The window that waits for a sign-in keeps listening until the sign-in answers: a window that closes before its answer is read,
// or the screen redrawing around it (its words or the sign-in's name changing), never loses the answer.

const NAME = "pack/account";
const different = { outcome: "different", name: NAME, error: "", detail: "", address: "alex@example.com", expected: "blake@example.com" };

function popup() {
  const win = { closed: false, close: () => undefined, location: { href: "" } };
  vi.stubGlobal("open", () => win);
  return win;
}

beforeEach(() => {
  fakeApi({
    "POST sign-ins/pack/account/start": () => ({ url: "http://localhost:9090/login" }),
    // The add-on has another account signed in, so its status alone says "signed in" whoever came back.
    "GET sign-ins": () => [{ name: NAME, status: "signed_in" }],
  });
});
afterEach(() => vi.unstubAllGlobals());

test("an answer that arrives after the window was seen closed is still shown, and is not taken for a sign-in", async () => {
  const win = popup();
  const { result } = renderHook(() => useSignInWindow(NAME));
  await act(() => result.current.start("blake@example.com"));
  expect(result.current.phase).toBe("waiting");
  win.closed = true;
  // The window is seen closed (its status is read), then the answer it sent first is delivered.
  await waitFor(() => expect(result.current.phase).not.toBe("waiting"), { timeout: 3000 });
  act(() => announceSignIn(different));
  await waitFor(() => expect(result.current.phase).toBe("different"));
  expect(result.current.text).toBe("That was a different account: alex@example.com. Sign in as blake@example.com.");
});

test("the screen redrawing around a waiting sign-in (new words, the sign-in not known for a moment) does not drop its answer", async () => {
  popup();
  const wrap = (words: Record<string, string>) => ({ children }: { children: ReactNode }) => <WordingProvider overrides={words}>{children}</WordingProvider>;
  const { result, rerender } = renderHook(({ name }: { name: string }) => useSignInWindow(name), { initialProps: { name: NAME }, wrapper: wrap({}) });
  await act(() => result.current.start("blake@example.com"));
  // The name is unknown for one draw, then known again.
  rerender({ name: "" });
  rerender({ name: NAME });
  act(() => announceSignIn(different));
  await waitFor(() => expect(result.current.phase).toBe("different"));
});

test("new words arriving while waiting do not drop the answer", async () => {
  popup();
  let words: Record<string, string> = {};
  const { result, rerender } = renderHook(() => useSignInWindow(NAME), { wrapper: ({ children }: { children: ReactNode }) => <WordingProvider overrides={words}>{children}</WordingProvider> });
  await act(() => result.current.start("blake@example.com"));
  words = { "some.other.entry": "Other" };
  rerender();
  act(() => announceSignIn(different));
  await waitFor(() => expect(result.current.phase).toBe("different"));
});
