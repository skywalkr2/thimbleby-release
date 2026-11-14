import { ESLint } from "eslint";
import { BARE_INVALIDATE_EXCEPTIONS } from "../../eslint.bare-invalidate-exceptions.js";

// The rule that keeps screens from reading everything again after a write (design 7, S-0424).
const eslint = new ESLint({ ignore: false });
const messages = async (file: string) => (await eslint.lintFiles([file]))[0].messages.filter((m) => m.ruleId === "no-restricted-syntax");

test("a new bare invalidateQueries() call fails lint", async () => {
  expect((await messages("src/lib/lint-fixtures/bare-invalidate.ts")).length).toBe(1);
}, 60000);

test("the stream's file and the write piece may refresh everything, and no file is on the exception list", async () => {
  expect(await messages("src/lib/live.ts")).toEqual([]);
  expect(await messages("src/lib/write.ts")).toEqual([]);
  // The list is empty: a screen names what it changed, and a new bare call is refused rather than listed.
  expect(BARE_INVALIDATE_EXCEPTIONS).toEqual([]);
}, 60000);
