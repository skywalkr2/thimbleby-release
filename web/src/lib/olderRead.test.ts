import { expect, test } from "vitest";
import { clockTime, setTimePrefs } from "./dates";
import { inHours } from "../test-utils";
import { stopWords, waitWhen } from "./olderRead";

const say = (key: string, vars?: Record<string, string | number>) => `${key}${vars?.time ? ` @${vars.time}` : ""}${vars?.when ? ` @${vars.when}` : ""}`;
const at = inHours(2);

test("a read the service asked to wait before taking anything says when reading starts, never that the rest continues", () => {
  expect(stopWords({ stopped: "throttled", continues_at: at, taken: 0 }, say)).toMatch(/^read\.stopped\.throttled\.start @read\.wait\.around/);
  expect(stopWords({ stopped: "offline", continues_at: at, taken: 0 }, say)).toMatch(/^read\.stopped\.offline\.start @read\.wait\.around/);
});

test("a read that took some and was slowed down says when the rest continues", () => {
  expect(stopWords({ stopped: "throttled", continues_at: at, taken: 100 }, say)).toMatch(/^read\.stopped\.throttled @read\.wait\.around/);
  expect(stopWords({ stopped: "throttled", continues_at: at }, say)).toMatch(/^read\.stopped\.throttled @read\.wait\.around/);
});

test("a read saved for the background, or between its slices, says it is being read and gives no time", () => {
  expect(stopWords({ stopped: "queued", continues_at: at, taken: 0 }, say)).toBe("read.stopped.queued");
  expect(stopWords({ stopped: "reading", continues_at: at, taken: 40 }, say)).toBe("read.stopped.reading");
});

import { firstReadLines, firstReadPending, stillReading } from "./olderRead";

const first = (over: Partial<Parameters<typeof firstReadPending>[0]> = {}) => ({ label: "Your inbox", enabled: true, read_at: null, account_state: "signed_in", last: null, ...over });

test("a read with some taken and about how many there will be says N of about M (H5-08)", () => {
  expect(stopWords({ stopped: "reading", continues_at: at, taken: 400, about: 1700 }, say)).toBe("read.stopped.of");
  expect(stopWords({ stopped: "queued", continues_at: at, taken: 0, about: 1700 }, say)).toBe("read.stopped.queued");
});

test("an account's card says what its first read is doing from sign-in on, and when it waits until (H5-08, H5-10)", () => {
  const waiting = first({ label: "Your calendar", last: { outcome: "throttled", retry_at: at } });
  expect(firstReadLines([first(), waiting], say)).toEqual(["read.first_look.taking", "read.first_look.waiting @read.wait.around @" + clockTime(at)]);
  expect(firstReadLines([first({ read_at: "2026-11-19T18:00:00Z" })], say)).toEqual([]);
});

test("a source that is off, signed out or failing has no first-look line, and only a first read to come or older mail being read counts as still reading", () => {
  for (const over of [{ enabled: false }, { account_state: "expired" }, { account_state: "signed_out" }, { last: { outcome: "failed" } }]) expect(firstReadPending(first(over))).toBe(false);
  expect(stillReading([first({ read_at: "x" })])).toBe(false);
  expect(stillReading([first({ read_at: "x", older_read: { gave_up: false } } as never)])).toBe(true);
  expect(stillReading([first({ read_at: "x", older_read: { gave_up: true } } as never)])).toBe(false);
  expect(stillReading([first()])).toBe(true);
});

test("a source whose older mail is being read, or that has looked back, has had its first look", () => {
  const base = { label: "Inbox", last: null, read_at: null };
  expect(firstReadPending(base)).toBe(true);
  expect(firstReadPending({ ...base, older_read: { gave_up: false } })).toBe(false);
  expect(firstReadPending({ ...base, looked_back_to: "2026-10-05" })).toBe(false);
});

const fromNow = (seconds: number) => new Date(Date.now() + seconds * 1000).toISOString();

test("a wait of seconds, minutes or longer is said in words, then by the time of day, at the setting's limit (H5-07)", () => {
  setTimePrefs({ shortWait: 5 });
  expect(waitWhen(fromNow(-30), say)).toBe("read.wait.minute");
  expect(waitWhen(fromNow(60), say)).toBe("read.wait.minute");
  expect(waitWhen(fromNow(180), say)).toBe("read.wait.few");
  expect(waitWhen(fromNow(600), say)).toMatch(/^read\.wait\.around @/);
  setTimePrefs({ shortWait: 15 });
  expect(waitWhen(fromNow(600), say)).toBe("read.wait.few");
  setTimePrefs({ shortWait: 5 });
});

test("every line that says when a read carries on uses the words for a short wait (H5-07)", () => {
  setTimePrefs({ shortWait: 5 });
  const soon = fromNow(60);
  expect(stopWords({ stopped: "throttled", continues_at: soon, taken: 100 }, say)).toBe("read.stopped.throttled @read.wait.minute");
  expect(stopWords({ stopped: "throttled", continues_at: soon, taken: 0 }, say)).toBe("read.stopped.throttled.start @read.wait.minute");
  const waiting = first({ label: "Your calendar", last: { outcome: "throttled", retry_at: soon } });
  expect(firstReadLines([waiting], say)).toEqual(["read.first_look.waiting @read.wait.minute"]);
});
