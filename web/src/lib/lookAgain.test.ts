import { expect, test } from "vitest";
import { LOOK_AGAIN_EVERY_MS, LOOK_EVERY_MS, lookAgainIn } from "./lookAgain";

test("an empty People step keeps asking in every state a later look can change, so its offers show without a reload", () => {
  for (const state of ["not_yet", "working"]) expect(lookAgainIn(state)).toBe(LOOK_EVERY_MS);
  for (const state of ["waiting", "reading_more", "looked", "too_little"]) expect(lookAgainIn(state)).toBe(LOOK_AGAIN_EVERY_MS);
  expect(lookAgainIn("no_account")).toBe(false);
});
