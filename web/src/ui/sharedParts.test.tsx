import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useStableJustMe } from "../lib/sides";
import { fakeApi, Refuse, renderApp } from "../test-utils";
import { EmptyState } from "./EmptyState";
import { FilterSheet } from "./FilterSheet";
import { ListDetail } from "./ListDetail";
import { LoadFailed } from "./LoadFailed";
import { PageHeader } from "./PageHeader";
import { SegmentedControl } from "./SegmentedControl";
import { Skeleton } from "./Skeleton";
import { ConnectionProvider } from "../lib/connection";

const css = (name: string) => readFileSync(join(__dirname, name), "utf8");

// G1b: the parts every screen shares.

test("a drawer is the full height of the window, square at its corner, with the footer pinned at the bottom", () => {
  const frame = css("Overlay.module.css");
  expect(frame).toMatch(/\.overlay\.drawer \{[^}]*align-items: stretch/);
  expect(frame).toMatch(/\.modal\.drawer \{[^}]*height: 100%[^}]*border-radius: 0/s);
  expect(css("Drawer.module.css")).toMatch(/\.footer \{[^}]*padding: var\(--space-3\) var\(--space-4\)/);
});

test("the status is a dot and a word with no fill, and the segmented control is an outlined track with the chosen segment filled", () => {
  expect(css("StatusChip.module.css")).toMatch(/\.chip \{[^}]*background: transparent/s);
  const seg = css("SegmentedControl.module.css");
  expect(seg).toMatch(/\.track \{[^}]*border: 1px solid var\(--border-strong\)/);
  expect(seg).toMatch(/\.segment\[data-selected\] \{ background: var\(--accent-soft\)/);
});

test("the status chip's word is plain text in every state, so there is never red body text; the dot carries the color", () => {
  const chip = css("StatusChip.module.css");
  expect(chip).not.toMatch(/\.(danger|warn) \.word/);
  expect(chip).toMatch(/\.danger \.dot \{ background: var\(--danger\)/);
  expect(chip).toMatch(/\.word \{[^}]*color: var\(--text\)/);
});

test("every filter is one light pill with one label pattern, 'Name choice' (no colon), in the select form and the sheet form alike", async () => {
  expect(css("FilterChip.module.css")).not.toMatch(/\.name::after/);
  const { FilterPill } = await import("./FilterPill");
  const { container } = render(<FilterPill label="Side" value="Lantern Row Studio" />);
  const pill = container.querySelector("[data-filter-pill]")!;
  expect(pill).toHaveTextContent("SideLantern Row Studio");
  expect(pill.querySelector("[class*=name]")).toHaveTextContent("Side");
  // The phone's sheet button is the same pill, its words the count ("Filter (2)") with no colon.
  const sheet = render(<FilterPill label="Filter (2)" />);
  expect(sheet.container.querySelector("[data-filter-pill] [class*=name]")).toBeNull();
});

test("Undo is one underlined control with the toast's own words, drawn beside the text it undoes", async () => {
  const { UndoLink } = await import("./UndoLink");
  renderApp(<UndoLink onClick={() => undefined} aria-label="Undo: Pay the deposit" />);
  expect(screen.getByRole("button", { name: "Undo: Pay the deposit" })).toHaveTextContent("Undo");
  expect(css("UndoLink.module.css")).toMatch(/text-decoration: underline/);
});

test("an empty state is a centred card with a display-face title", () => {
  const empty = css("EmptyState.module.css");
  expect(empty).toMatch(/\.empty \{[^}]*justify-items: center[^}]*text-align: center/);
  expect(empty).toMatch(/\.title \{[^}]*font-family: var\(--font-display\)/);
  renderApp(<EmptyState title="Nothing here" text="One line." action={{ label: "Add one" }} />);
  expect(screen.getByText("Nothing here")).toBeVisible();
});

test("a table that loads is a head and rows in the table's own card, and its bars are a tone of the text", () => {
  renderApp(<Skeleton shape="table" rows={3} columns={5} />);
  const table = screen.getByRole("status");
  expect(table).toHaveAttribute("data-skeleton", "table");
  expect(table.querySelectorAll("div[aria-hidden]")).toHaveLength(4);
  expect(css("Skeleton.module.css")).toMatch(/--skeleton: color-mix\(in srgb, var\(--text\)/);
});

test("a failed card has no button of its own while the app is offline: the offline bar holds the one Try now", () => {
  const live = (state: "live" | "offline") => ({ state, lastUpdate: null, refresh: () => undefined, reconnect: () => undefined });
  const { unmount } = renderApp(
    <ConnectionProvider live={live("live")}>
      <LoadFailed message="It couldn't be loaded." onRetry={() => undefined} />
    </ConnectionProvider>,
  );
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  unmount();
  renderApp(
    <ConnectionProvider live={live("offline")}>
      <LoadFailed message="It couldn't be loaded." onRetry={() => undefined} />
    </ConnectionProvider>,
  );
  expect(screen.queryByRole("button")).toBeNull();
});

test("a screen's subtitle keeps its line while it is read, so the page does not move when it arrives", () => {
  const { unmount } = renderApp(<PageHeader title="Schedule" reserveSubtitle />);
  expect(document.querySelector("[data-sub-reserved]")).not.toBeNull();
  // r4-c7: the held line is seen as a quiet bar (never text, never read out), not as an empty gap.
  expect(document.querySelector("[data-sub-reserved] [data-sub-bar]")).not.toBeNull();
  expect(document.querySelector("[data-sub-reserved]")).toHaveAttribute("aria-hidden", "true");
  unmount();
  renderApp(<PageHeader title="Schedule" subtitle="1 clash" reserveSubtitle />);
  expect(document.querySelector("[data-sub-reserved]")).toBeNull();
  expect(screen.getByText("1 clash")).toBeVisible();
  // Held or filled, the line is the same height (a press target's), so a button in it never moves what is under it.
  expect(document.querySelector("[data-sub-held]")).not.toBeNull();
});

test("on a phone the filters are one Filter button with how many are on, and a sheet that holds them with their names", async () => {
  const user = userEvent.setup();
  document.documentElement.setAttribute("data-narrow", "");
  try {
    renderApp(
      <PageHeader
        title="To-dos"
        filterSheet={{ shown: true, active: 2 }}
        filters={<SegmentedControl label="Group by" value="a" onChange={() => undefined} options={[{ value: "a", label: "Person" }, { value: "b", label: "Project" }]} />}
      />,
    );
    expect(screen.queryByRole("radiogroup", { name: "Group by" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Filter (2)" }));
    const sheet = await screen.findByRole("dialog", { name: "Filter" });
    expect(within(sheet).getByText("Group by")).toBeVisible();
    expect(within(sheet).getByRole("radiogroup", { name: "Group by" })).toBeVisible();
  } finally {
    document.documentElement.removeAttribute("data-narrow");
  }
});

test("from the tablet width the filters stay in their row, and with none on offer a phone has no Filter button", () => {
  renderApp(<PageHeader title="To-dos" filterSheet={{ shown: true }} filters={<span>chips</span>} />);
  expect(screen.getByText("chips")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Filter" })).toBeNull();
  document.documentElement.setAttribute("data-narrow", "");
  try {
    renderApp(<PageHeader title="Quiet" filterSheet={{ shown: false }} filters={<span>none</span>} />);
    expect(screen.queryByText("none")).toBeNull();
  } finally {
    document.documentElement.removeAttribute("data-narrow");
  }
});

test("a filter sheet opened from FilterSheet lists its content", async () => {
  const user = userEvent.setup();
  renderApp(
    <FilterSheet>
      <p>Everything</p>
    </FilterSheet>,
  );
  await user.click(screen.getByRole("button", { name: "Filter" }));
  expect(await screen.findByText("Everything")).toBeVisible();
});

test("a detail pane named for what it describes is anchored to it: it starts level with it and carries a pointer", async () => {
  document.documentElement.removeAttribute("data-narrow");
  window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, onchange: null, dispatchEvent: () => false })) as typeof window.matchMedia;
  renderApp(
    <ListDetail title="Quarterly review" onClose={() => undefined} anchorTo="[data-entry-key='x']" detail={<p>When</p>}>
      <button type="button" data-entry-key="x">
        Entry
      </button>
    </ListDetail>,
  );
  await waitFor(() => expect(document.querySelector("[data-detail-pane]")).toHaveAttribute("data-anchored"));
  expect(css("ListDetail.module.css")).toMatch(/\.pane\[data-anchored\]::before/);
});

test("until the sides are read the menu keeps what the browser last knew, so it does not change when the data arrives", async () => {
  fakeApi({ business: () => new Refuse(500, ""), projects: () => new Refuse(500, "") });
  function Probe() {
    return <p>{useStableJustMe() ? "just me" : "with work"}</p>;
  }
  window.localStorage.setItem("cockpit:nav:just-me", "1");
  const { unmount } = renderApp(<Probe />);
  expect(screen.getByText("just me")).toBeVisible();
  unmount();
  window.localStorage.setItem("cockpit:nav:just-me", "0");
  renderApp(<Probe />);
  expect(screen.getByText("with work")).toBeVisible();
  window.localStorage.removeItem("cockpit:nav:just-me");
});

test("chips, the calendar buttons and the segmented control share the button height and the pill radius", () => {
  expect(css("FilterChip.module.css")).toMatch(/\.chip \{[^}]*height: var\(--btn-h-sm\)[^}]*border-radius: var\(--radius-btn\)/s);
  // The calendars' button is the same pill as every filter: the filter chip's own box, drawn by FilterPill.
  expect(readFileSync(join(__dirname, "FilterPill.tsx"), "utf8")).toContain("styles.chip");
  expect(css("SegmentedControl.module.css")).toMatch(/\.track \{[^}]*border-radius: var\(--radius-btn\)/);
});

test("the Timeline's range is set off from the views by a rule, a Day fills the content width as the Week does, and the side menu's column is painted the page's height", () => {
  const schedule = readFileSync(join(__dirname, "..", "components", "Schedule.module.css"), "utf8");
  expect(schedule).toMatch(/\.rangeSwitch \{[^}]*border-left: 1px solid var\(--border-strong\)/);
  expect(schedule).not.toMatch(/\.frame\[data-view="day"\]/);
  expect(readFileSync(join(__dirname, "..", "shell", "Shell.module.css"), "utf8")).toMatch(/\.app \{[^}]*linear-gradient\(to right, var\(--surface\)/s);
});

test("the Schedule's failed read is the one failed card, so offline it has no second retry beside the offline bar", () => {
  const source = readFileSync(join(__dirname, "..", "components", "Schedule.tsx"), "utf8");
  expect(source).toMatch(/<LoadFailed message=\{t\("schedule\.load_failed"\)\}/);
  expect(source).not.toMatch(/<EmptyState icon="alert"/);
});
