import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test } from "vitest";
import { useLoadFailure } from "./load-failure";

// S-0431: a read that failed stays failed while the app reads again by itself, and says so with the same words until one answers.
test("a failed read stays failed while it is read again, and ends only when a read answers", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let release: () => void = () => undefined;
  let mode: "fail" | "hold" | "pass" = "fail";
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result } = renderHook(
    () => {
      const q = useQuery({
        queryKey: ["page"],
        queryFn: async () => {
          if (mode === "fail") throw new Error("locked");
          if (mode === "hold") await new Promise<void>((resolve) => (release = resolve));
          return "page";
        },
      });
      return { q, failure: useLoadFailure(q) };
    },
    { wrapper },
  );
  await waitFor(() => expect(result.current.failure.failed).toBe(true));
  mode = "hold";
  act(() => void client.invalidateQueries());
  await waitFor(() => expect(result.current.q.fetchStatus).toBe("fetching"));
  // The query is pending again, yet the failed state and its error are still there for the screen to draw.
  expect(result.current.q.isPending).toBe(true);
  expect(result.current.failure.failed).toBe(true);
  expect((result.current.failure.error as Error).message).toBe("locked");
  await act(async () => release());
  await waitFor(() => expect(result.current.failure.failed).toBe(false));
  expect(result.current.q.data).toBe("page");
});
