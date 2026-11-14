import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { vi } from "vitest";
import { RoundCheck } from "./RoundCheck";

// S-0049: the round mark on a to-do reads as "done", never as "select".
test("the mark is a button named for what it does, not a check box, and its ring is decoration", async () => {
  const run = vi.fn();
  const { container } = render(<RoundCheck label="Mark done: Order the flowers" onClick={run} />);
  expect(screen.queryByRole("checkbox")).toBeNull();
  const mark = screen.getByRole("button", { name: "Mark done: Order the flowers" });
  expect(container.querySelector("span[aria-hidden='true']")).not.toBeNull();
  await userEvent.click(mark);
  expect(run).toHaveBeenCalledTimes(1);
});

test("the ring is empty at rest: the check is drawn but invisible until hover or focus brings it, and it never fades below 3:1 as a ring", () => {
  const css = readFileSync(join(__dirname, "RoundCheck.module.css"), "utf8");
  expect(css).toMatch(/\.ring::after\s*\{[^}]*opacity:\s*0[;\s}]/);
  expect(css).toMatch(/\.check:hover \.ring::after[^{]*\{[^}]*opacity:\s*1/);
  expect(css).toMatch(/\.ring\s*\{[^}]*border:\s*1\.5px solid var\(--border-strong\)/);
});

test("the ring is drawn with a check inside it, and no other component draws its own plain circle for a to-do", () => {
  const css = readFileSync(join(__dirname, "RoundCheck.module.css"), "utf8");
  expect(css).toMatch(/\.ring::after\s*\{[^}]*border-width:\s*0 2px 2px 0/);
  // Every place that lists a to-do uses this mark: none builds a circle button of its own.
  const own = (file: string) => /styles\.(ring|circle|roundMark)\b/.test(readFileSync(join(__dirname, "..", "components", file), "utf8"));
  const found = readdirSync(join(__dirname, "..", "components")).filter((f) => f.endsWith(".tsx") && !f.endsWith(".test.tsx") && own(f));
  expect(found).toEqual([]);
});
