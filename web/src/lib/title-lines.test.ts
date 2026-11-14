import { firstLine } from "./title-lines";

test("a body is never a title: the title is the first line with words, however long the note is (S-0336)", () => {
  const text = "\n  First line of the note  \nSecond line.\n\nThird.";
  expect(firstLine(text)).toBe("First line of the note");
  expect(firstLine("Only a title")).toBe("Only a title");
  expect(firstLine("   \n  ")).toBe("");
});
