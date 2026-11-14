import { keepNumber } from "./keep-number";

test("a number that ends a title is joined to the word before it, so it never wraps alone", () => {
  expect(keepNumber("Question for account 1")).toBe("Question for account 1");
  expect(keepNumber("Venue list")).toBe("Venue list");
  expect(keepNumber("Budget 2026 review")).toBe("Budget 2026 review");
});
