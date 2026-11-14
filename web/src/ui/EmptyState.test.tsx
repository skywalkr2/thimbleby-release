import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EmptyState } from "./EmptyState";
import { LoadFailed } from "./LoadFailed";
import { Skeleton } from "./Skeleton";

test("an empty state is one sentence and one button that does the next step", async () => {
  const user = userEvent.setup();
  const run = vi.fn();
  render(<EmptyState text="Nothing waiting to go out." action={{ label: "Hand something in", onClick: run }} />);
  expect(screen.getByText("Nothing waiting to go out.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Hand something in" }));
  expect(run).toHaveBeenCalledTimes(1);
});

test("an empty state without a next step has no button, and a rail one is a single line", () => {
  const { container } = render(<EmptyState inline text="Not connected" />);
  expect(screen.queryByRole("button")).toBeNull();
  expect(container.querySelector("[data-brand-mark]")).toBeNull();
});

test("a failed load says what failed, offers Try again and keeps the raw detail behind Details", async () => {
  const user = userEvent.setup();
  const retry = vi.fn();
  render(<LoadFailed message="Couldn't load people." onRetry={retry} detail="HTTP 500: boom" />);
  expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load people.");
  const detail = screen.getByText("HTTP 500: boom");
  expect(detail).not.toBeVisible();
  await user.click(screen.getByText("Details"));
  expect(detail).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(retry).toHaveBeenCalledTimes(1);
});

test("a failed load without a detail has no Details", () => {
  render(<LoadFailed message="Couldn't load people." onRetry={() => {}} />);
  expect(screen.queryByText("Details")).toBeNull();
});

test("skeleton rows mark their region busy and say nothing visible", () => {
  const { container } = render(<Skeleton rows={4} />);
  const region = screen.getByRole("status", { name: "Loading…" });
  expect(region).toHaveAttribute("aria-busy", "true");
  expect(container.querySelectorAll("[data-skeleton] > div")).toHaveLength(4);
  expect(region.textContent).toBe("");
});

test("an empty state has a title, a sentence, the icon and one action, and the action can be a link", () => {
  const { container } = render(<EmptyState title="No files yet" text="Add one to keep it here." action={{ label: "Add a file", href: "#add" }} />);
  expect(screen.getByText("No files yet")).toBeInTheDocument();
  expect(screen.getByText("Add one to keep it here.")).toBeInTheDocument();
  expect(container.querySelector("[data-brand-mark]")).not.toBeNull();
  expect(screen.getByRole("link", { name: "Add a file" })).toHaveAttribute("href", "#add");
  expect(container.querySelector("[data-empty]")).not.toBeNull();
});

test("an empty state is a centred card of capped width with the brand mark, a quiet action and no dashed box", async () => {
  const { readFileSync } = await import("node:fs");
  const { join } = await import("node:path");
  const css = readFileSync(join(__dirname, "EmptyState.module.css"), "utf8");
  const rule = css.match(/\.empty \{([^}]*)\}/)![1];
  expect(rule).toMatch(/justify-items: center/);
  expect(rule).toMatch(/text-align: center/);
  expect(rule).toMatch(/margin-inline: auto/);
  expect(rule).toMatch(/max-width: 32rem/);
  expect(css).not.toMatch(/dashed/);
  const { container } = render(<EmptyState title="Nothing yet" text="Add one." action={{ label: "Add", onClick: () => {} }} />);
  expect(container.querySelector("[data-brand-mark]")).not.toBeNull();
  expect(screen.getByRole("button", { name: "Add" })).toHaveAttribute("data-variant", "secondary");
});

test("a page's empty state is the card with the brand mark, a title, a sentence and one action; a rail one stays a line even when asked for the card", () => {
  const { container } = render(<EmptyState card title="All done" text="New to-dos from your mail and notes land here." action={{ label: "See what you finished" }} />);
  expect(container.querySelector("[data-empty]")!.className).toMatch(/card/);
  expect(container.querySelector("[data-brand-mark]")).not.toBeNull();
  const line = render(<EmptyState card inline text="Not connected" />);
  expect(line.container.querySelector("[data-empty]")!.className).not.toMatch(/card/);
});

test("a page's card has one filled primary and at most one quiet text action; a filter's card keeps its action outlined", async () => {
  render(<EmptyState card title="All done" text="Nothing is open." action={{ label: "Add a to-do", primary: true }} quietAction={{ label: "See what you finished" }} />);
  expect(screen.getByRole("button", { name: "Add a to-do" })).toHaveAttribute("data-variant", "primary");
  expect(screen.getByRole("button", { name: "See what you finished" })).toHaveAttribute("data-variant", "quiet");
  const { FilteredEmpty } = await import("./FilteredEmpty");
  render(<FilteredEmpty card text="Nothing for this side" onClear={() => undefined} />);
  expect(screen.getByRole("button", { name: "Clear filter" })).toHaveAttribute("data-variant", "secondary");
});
