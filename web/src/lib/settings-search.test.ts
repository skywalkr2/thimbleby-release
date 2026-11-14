import { handOffSearch, peekSearch, takeCarriedCursor, takeSearch } from "./settings-search";

afterEach(() => {
  takeSearch();
  takeCarriedCursor();
});

test("keys typed before the next page is drawn add up to one search, which is handed over once", () => {
  for (const key of ["t", "i", "m", "e", " ", "z"]) handOffSearch(key);
  expect(takeCarriedCursor()).toBe(true);
  expect(takeSearch()).toBe("time z");
  expect(takeSearch()).toBe("");
  expect(takeCarriedCursor()).toBe(false);
});

test("a search handed over after the last one was taken starts again", () => {
  handOffSearch("a");
  expect(takeSearch()).toBe("a");
  handOffSearch("b");
  expect(takeSearch()).toBe("b");
});

test("reading the search while a screen is drawn spends nothing; taking it once the screen is shown does", () => {
  handOffSearch("ti");
  expect(peekSearch()).toBe("ti");
  expect(peekSearch()).toBe("ti");
  handOffSearch("m");
  expect(peekSearch()).toBe("tim");
  takeSearch();
  expect(peekSearch()).toBe("");
});
