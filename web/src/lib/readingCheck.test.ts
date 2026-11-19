import { expect, test } from "vitest";
import { checkLines, type Check } from "./readingCheck";

// The lines of a reading check say what the gate counted, in words from the wording sheet; here the words are keys with their numbers.
const t = (key: string, vars: Record<string, string | number> = {}) => `${key} ${JSON.stringify(vars)}`;
const tn = (key: string, n: number) => `${key} ${n}`;
const base: Check = { account: "a@example.com", asked: 20, read: 20, ended: "read", requests: 21, held: 0, refusals: [], waiting_until: null, pace_per_second: 2, declared_per_second: 2, paced_seconds: 10, log_line: "" };

test("a check with no refusal says so, counts the requests and gives the pace as it started", () => {
  const lines = checkLines(base, t, tn);
  expect(lines[0]).toContain("reading_check.headline.read");
  expect(lines).toContain("reading_check.requests 21");
  expect(lines.some((l) => l.startsWith("reading_check.no_refusals"))).toBe(true);
  expect(lines.some((l) => l.startsWith("reading_check.pace_same"))).toBe(true);
  expect(lines.some((l) => l.includes("reading_check.waiting") || l.includes("reading_check.held"))).toBe(false);
});

test("a refusal with no status or no wait given says what it can, and an ending it does not know is the general one", () => {
  const found: Check = { ...base, ended: "teapot", refusals: [{ status: null, reason: "throttled:quota", wait_seconds: null, at: "2026-11-19T19:42:00Z", until: "2026-11-19T19:43:00Z" }] };
  const lines = checkLines(found, t, tn);
  expect(lines[0]).toContain("reading_check.headline.other");
  expect(lines.some((l) => l.startsWith("reading_check.refusal_no_status"))).toBe(true);
  expect(lines.some((l) => l.startsWith("reading_check.wait_no_time"))).toBe(true);
});
