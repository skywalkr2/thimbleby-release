import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSortingCostWords } from "./sorting-cost";
import { WordingProvider } from "./wording";
import { api } from "./api";

const wrap = ({ children }: { children: ReactNode }) => (
  <WordingProvider>
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
  </WordingProvider>
);

async function words(cost: Record<string, unknown>) {
  vi.spyOn(api, "sortingCost").mockResolvedValue(cost as never);
  const { result } = renderHook(() => useSortingCostWords(), { wrapper: wrap });
  await waitFor(() => expect(result.current).not.toBeNull());
  return result.current as string;
}

afterEach(() => vi.restoreAllMocks());

test("a pay-per-use account's day is an estimate in money for the day's messages", async () => {
  expect(await words({ kind: "money", messages: 60, runs: 3, estimate_usd: 0.4, measured: true })).toBe("Estimated at about $0.40 a day for about 60 messages.");
});

test("a plan's day is runs a day from the plan, with no money", async () => {
  const said = await words({ kind: "runs", messages: 60, runs: 3, estimate_usd: null, measured: false });
  expect(said).toBe("Estimated at about 3 runs a day from your plan, for about 60 messages.");
  expect(said).not.toContain("$");
});

test("an account whose price isn't known says so, in runs", async () => {
  expect(await words({ kind: "unknown", messages: 1, runs: 1, estimate_usd: null, measured: true })).toBe(
    "Estimated at about 1 run a day for about 1 message; the price of this account isn't known.",
  );
});

test("with no account the words say the built-in rules sort", async () => {
  expect(await words({ kind: "none", messages: 60, runs: 3, estimate_usd: null, measured: false })).toBe(
    "Until an AI account is added, sorting uses the built-in rules.",
  );
});
