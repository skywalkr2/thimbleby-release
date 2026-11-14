import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { joinMeta, SIDE_PART } from "./meta-join";

const text = (parts: Parameters<typeof joinMeta>[0]) => {
  const { container } = render(<p>{joinMeta(parts)}</p>);
  return container.textContent!.replace(/ /g, " ").replace(/\s+/g, " ").trim();
};

test("a dot separates the parts, and none stands at either end", () => {
  expect(text(["Due Fri", null, "Quinn Sample", false, "To send"])).toBe("Due Fri · Quinn Sample · To send");
});

test("a side mark is followed by a dot, so its name never runs into the next part", () => {
  expect(text([<b key={SIDE_PART}>Orchard Press</b>, "Quinn Sample", "To send"])).toBe("Orchard Press · Quinn Sample · To send");
});

test("nothing separates a side mark from what comes before it, and a mark that ends the line has no dot after it", () => {
  expect(text(["Due Fri", <b key={SIDE_PART}>Orchard Press</b>])).toBe("Due Fri Orchard Press");
  expect(text([<b key={SIDE_PART}>Orchard Press</b>])).toBe("Orchard Press");
});
