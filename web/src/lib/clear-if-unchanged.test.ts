import { describe, expect, it } from "vitest";
import { clearIfUnchanged } from "./clear-if-unchanged";

// Runs the updater the way React does, against the field's value at the moment the save answers.
const answer = (now: string, saved: string): string => {
  let out = "?";
  clearIfUnchanged((u) => {
    out = typeof u === "function" ? u(now) : u;
  }, saved);
  return out;
};

describe("clearIfUnchanged", () => {
  it("empties a field that still holds what was saved", () => expect(answer("Bank", "Bank")).toBe(""));
  it("keeps what was typed since", () => expect(answer("Bank of", "Bank")).toBe("Bank of"));
  it("keeps a field that was emptied and typed afresh", () => expect(answer("N", "Bank")).toBe("N"));
});
