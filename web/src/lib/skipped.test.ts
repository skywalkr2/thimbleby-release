import { expect, test } from "vitest";
import { addSkipped, skippedWords } from "./skipped";

const tn = (key: string, n: number) => `${key}:${n}`;

test("each kind skipped is one sentence, the known kinds in a fixed order, and none says nothing", () => {
  expect(skippedWords({ other: 1, too_large: 3 }, tn)).toBe("read.skipped.too_large:3 read.skipped.other:1");
  expect(skippedWords({}, tn)).toBe("");
  expect(skippedWords(undefined, tn)).toBe("");
  expect(skippedWords({ too_large: 0 }, tn)).toBe("");
});

test("a kind the screen doesn't know counts as one that couldn't be read", () => {
  expect(skippedWords({ something_new: 2, other: 1 }, tn)).toBe("read.skipped.other:3");
});

test("counts of several reads add up by kind", () => {
  expect(addSkipped([{ too_large: 1 }, undefined, { too_large: 2, other: 1 }])).toEqual({ too_large: 3, other: 1 });
});
