import "@testing-library/jest-dom/vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { addDays } from "../lib/dates";
import { ConnectionProvider } from "../lib/connection";
import { OfflineBanner } from "../ui/OfflineBanner";
import { Knowledge } from "./Knowledge";
import { entry, item, lane, scheduleRoutes, timelineRoutes, TODAY } from "../lib/schedule-fixtures";
import { fakeApi, Refuse, renderApp } from "../test-utils";
import { Schedule } from "./Schedule";

// The Schedule's Timeline, Add form and Add menu, fifth round (design 7.7): the key names each calendar and says nothing of patterns,
// the Add form's cursor goes to the field that needs fixing, and the phone's menu holds Add while the page is dead.

const WIDTH = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
});
afterEach(() => {
  document.documentElement.removeAttribute("data-narrow");
  if (WIDTH) Object.defineProperty(Element.prototype, "clientWidth", WIDTH);
});

const watched = (id: string, label: string, color: string) => ({ id, label, connector: "k", connector_label: "K", enabled: true, every_minutes: 15, items: 1, failures: 0, problem: null, reads: ["calendar"], shown_color: color });

test("the Timeline's key names each calendar drawn on it, and its days-off line is plain words", async () => {
  window.localStorage.setItem("cockpit:schedule-view", "timeline");
  const at = (title: string, source: string, n: number) => item({ title, kind: "entry", id: `EVT-${n}`, entry: entry({ title, snapshot: `snap-${n}`, entry: `EVT-${n}`, source }) }, addDays(TODAY, n));
  fakeApi(
    timelineRoutes([lane("PRJ-1", "Harbor", [at("Standup", "cal-work", 1), at("Dentist", "cal-home", 2)])], { off_days: [{ day: addDays(TODAY, 3), kind: "weekend", reason: "" }] }, {
      "GET watch": () => [watched("cal-work", "Work calendar", "teal"), watched("cal-home", "Home calendar", "purple")],
    }),
  );
  renderApp(<Schedule />);
  const key = await screen.findByRole("list", { name: "Key" });
  await waitFor(() => expect(within(key).getByText("Work calendar")).toBeInTheDocument());
  expect(within(key).getByText("Home calendar")).toBeInTheDocument();
  expect(within(key).queryByText("Calendar entry")).toBeNull();
  expect(within(key).getByText("Days people don't work")).toBeInTheDocument();
  expect(key.textContent).not.toMatch(/hatched|named in the details/);
});

describe("the Add form", () => {
  async function form() {
    const user = userEvent.setup();
    fakeApi(scheduleRoutes());
    renderApp(<Schedule />);
    await user.click(await screen.findByRole("button", { name: "Add to schedule" }));
    const drawer = await screen.findByRole("dialog", { name: "Add a meeting" });
    return { user, drawer };
  }

  // One Enter makes at most one meeting, from any field and while a save is still answering.
  async function filled(slow = false) {
    const user = userEvent.setup();
    let release = () => undefined as void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const calls = fakeApi(
      scheduleRoutes(undefined, {}, {
        "POST calendar/meetings": async () => {
          if (slow) await gate;
          return { entry: "EVT-9", changeset: "CS-9", merged: false };
        },
        "POST changesets/CS-9/undo": () => ({ restored: [0], skipped: [] }),
      }),
    );
    renderApp(<Schedule />);
    await user.click(await screen.findByRole("button", { name: "Add to schedule" }));
    const drawer = await screen.findByRole("dialog", { name: "Add a meeting" });
    await user.type(within(drawer).getByRole("textbox", { name: "What" }), "Standup");
    const made = () => calls.filter((c) => c.route === "POST calendar/meetings").length;
    const body = () => calls.find((c) => c.route === "POST calendar/meetings")?.body as { time: string | null; until: string | null } | undefined;
    return { user, drawer, made, body, release };
  }

  test.each(["Starts at", "Ends at", "Place", "What"])("Enter in %s with the form filled makes one meeting", async (label) => {
    const { user, drawer, made, body } = await filled();
    // Ends at waits for a start.
    if (label === "Ends at") {
      await user.type(within(drawer).getByLabelText("Starts at"), "10:00");
      await user.tab();
    }
    const field = label === "What" || label === "Place" ? within(drawer).getByRole("textbox", { name: label }) : within(drawer).getByLabelText(label);
    await user.click(field);
    if (label === "Ends at") await user.clear(field);
    // A time is typed and Enter is pressed in the same box, without leaving it.
    if (label === "Starts at") await user.type(field, "10:00{Enter}");
    else if (label === "Ends at") await user.type(field, "11:00{Enter}");
    else await user.keyboard("{Enter}");
    await waitFor(() => expect(made()).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add a meeting" })).toBeNull());
    expect(made()).toBe(1);
    if (label === "Starts at") expect(body()?.time).toBe("10:00");
  });

  test("three Enters in a row, and Enter while the save is still answering, make one meeting", async () => {
    const { user, drawer, made, release } = await filled(true);
    await user.click(within(drawer).getByRole("textbox", { name: "What" }));
    await user.keyboard("{Enter}{Enter}{Enter}");
    await waitFor(() => expect(made()).toBeGreaterThanOrEqual(1));
    await user.click(within(drawer).getByRole("textbox", { name: "Place" }));
    await user.keyboard("{Enter}");
    expect(made()).toBe(1);
    release();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add a meeting" })).toBeNull());
    expect(made()).toBe(1);
  });

  test("Enter with no title puts the cursor on What", async () => {
    const { user, drawer } = await form();
    await user.click(within(drawer).getByRole("textbox", { name: "Place" }));
    await user.keyboard("{Enter}");
    expect(within(drawer).getByRole("textbox", { name: "What" })).toHaveFocus();
  });

  test("an end before the start is held, and Enter puts the cursor on Ends at", async () => {
    const { user, drawer } = await form();
    await user.type(within(drawer).getByRole("textbox", { name: "What" }), "Standup");
    await user.type(within(drawer).getByLabelText("Starts at"), "10:00");
    await user.tab();
    const end = within(drawer).getByLabelText("Ends at");
    await user.clear(end);
    await user.type(end, "9:00");
    await user.tab();
    expect(within(drawer).getByRole("alert")).toHaveTextContent("It has to end after it starts.");
    await user.click(within(drawer).getByRole("textbox", { name: "Place" }));
    await user.keyboard("{Enter}");
    expect(within(drawer).getByLabelText("Ends at")).toHaveFocus();
  });
});

test("on a phone the menu's Add is held with the wide Add's reason while the schedule failed to load", async () => {
  document.documentElement.setAttribute("data-narrow", "");
  const routes = scheduleRoutes();
  delete routes["GET schedule"];
  fakeApi(routes);
  window.localStorage.setItem("cockpit:schedule-view", "day");
  const user = userEvent.setup();
  renderApp(<Schedule />);
  await screen.findByText(/Your schedule couldn't be loaded/);
  await user.click(screen.getByRole("button", { name: /^More .*Schedule/ }));
  const add = await screen.findByRole("menuitem", { name: /Add to schedule/ });
  expect(add).toHaveAttribute("aria-disabled", "true");
  expect(add).toHaveTextContent("Adding comes back when the schedule loads.");
});

describe("offline, what could not be loaded says the app can't reach its server", () => {
  const offline = (children: React.ReactElement) => (
    <ConnectionProvider live={{ state: "offline", lastUpdate: new Date("2026-11-03T10:42:00Z"), refresh: () => undefined, reconnect: () => undefined }}>
      <OfflineBanner />
      {children}
    </ConnectionProvider>
  );

  test("on the Schedule, with the offline bar holding the one retry", async () => {
    const routes = scheduleRoutes();
    routes["GET schedule"] = () => new Refuse(500, "");
    fakeApi(routes);
    window.localStorage.setItem("cockpit:schedule-view", "day");
    renderApp(offline(<Schedule />));
    const failed = await screen.findByText(/Your schedule couldn't be loaded/);
    expect(failed).toHaveTextContent("The app can't reach its server.");
    expect(within(failed.closest("[role=alert]") as HTMLElement).queryByRole("button")).toBeNull();
  });

  test("on Knowledge", async () => {
    fakeApi({ knowledge: () => new Refuse(500, ""), "knowledge/rules": () => new Refuse(500, "") });
    renderApp(offline(<Knowledge onOpenReview={() => undefined} />));
    expect(await screen.findByText(/The app can't reach its server\./)).toBeInTheDocument();
  });
});

test("a lane's name is shown whole: it wraps, and no rule cuts it to a number of lines", () => {
  const rules = readFileSync(join(__dirname, "ScheduleTimeline.module.css"), "utf8");
  const name = rules.split("\n").filter((line) => /^\.(laneName|laneText)\b/.test(line)).join("\n");
  expect(name).toMatch(/overflow-wrap: anywhere/);
  expect(name).not.toMatch(/line-clamp|text-overflow|nowrap/);
});

test("a to-do or promise on the Timeline and in its key is the round mark with a faint check, never a square", () => {
  const rules = readFileSync(join(__dirname, "ScheduleTimeline.module.css"), "utf8");
  const square = rules.split("\n").filter((line) => /data-shape="square"\]/.test(line)).join("\n");
  expect(square).toMatch(/border-radius: var\(--radius-full\)/);
  expect(square).toMatch(/::after/);
  expect(square).toMatch(/opacity: 0\.35/);
});
