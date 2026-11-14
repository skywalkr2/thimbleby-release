import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import { renderApp } from "../test-utils";
import { ScheduleSkeleton } from "./ScheduleSkeleton";

test("the grids load as hour rows under a heading for each day, the month and the list as rows", () => {
  const { unmount } = renderApp(<ScheduleSkeleton view="grid" days={5} />);
  const grid = screen.getByRole("status");
  expect(grid).toHaveAttribute("data-skeleton", "grid");
  expect(grid).toHaveAttribute("aria-busy", "true");
  expect(grid.style.getPropertyValue("--cols")).toBe("5");
  expect(grid.querySelectorAll("span").length).toBeGreaterThan(5 + 8);
  // The line for "Show all hours" is held above the grid, so the grid is at the same height when the page arrives.
  expect(document.querySelector("[data-hours-held]")).not.toBeNull();
  unmount();
  renderApp(<ScheduleSkeleton view="list" days={5} />);
  expect(screen.getByRole("status")).toHaveAttribute("data-skeleton", "");
});

test("the list and the month load as the rows they will be: a dot, two lines, no pill, in the list's own frame; the grid's headings sit over their days", () => {
  const { unmount } = renderApp(<ScheduleSkeleton view="list" days={5} />);
  const rows = screen.getByRole("status");
  expect(rows.className).toMatch(/framed/);
  // The real row has a dot and a text pair; no button-shaped placeholder at its end.
  expect(rows.querySelector("[class*='btn']")).toBeNull();
  expect(rows.querySelectorAll("[class*='lead']").length).toBeGreaterThan(0);
  unmount();
  renderApp(<ScheduleSkeleton view="grid" days={5} />);
  const heads = Array.from(document.querySelectorAll<HTMLElement>("[class*='skeletonHead']"));
  expect(heads.map((h) => h.style.gridColumn)).toEqual(["2", "3", "4", "5", "6"]);
  // No block at all: nothing drawn while loading can be read as an entry.
  expect(document.querySelectorAll("[class*='skeletonEvent']").length).toBe(0);
});
