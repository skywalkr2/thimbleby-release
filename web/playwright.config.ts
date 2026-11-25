// Browser tests: the acceptance scenario at the root path and under a nested base path, with accessibility checks, and
// the layout check (no screen wider than the window).
// Build the UI first (npm run build); each project starts its own server from the repository root.
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { daytimeAt, momentAt, mondayAt } from "./e2e/clock";
import { namedProjects, selectServers } from "./playwright.select";

// PW_PORT_OFFSET moves every port the tests use by that much, so two runs (two checkouts) can share a computer.
const offset = Number(process.env.PW_PORT_OFFSET) || 0;
const servers = [
  { name: "root", port: 8781 + offset, base: "/" },
  { name: "nested", port: 8782 + offset, base: "/admin" },
];
// The layout check has a server of its own, because it holds long made-up text that the other scenarios must not see. The
// check that no screen shows an internal reads the same server, with the demo's history and the work added to it.
const layout = { port: 8786 + offset };
// So does the check of the yes to an AI account reading work mail and notes: its server has a second stand-in account whose
// person said Not now, which the other scenarios must not see on Today.
const access = { port: 8787 + offset };
// And Today's capacity, measured on a fresh demo that no other scenario has added lines to.
const capacity = { port: 8788 + offset };
// And the timeline: a fresh demo of its own, because the schedule's tests leave so many meetings on today on the root server that a
// lane would show as its list by week, with no dated axis left to check.
const timeline = { port: 8777 + offset };
// And the late-evening check: its server's clock starts just after midnight UTC, the evening before in the demo's time zone
// (which is behind UTC), so a day written or counted in the wrong zone shows as a wait below zero.
const late = { port: 8789 + offset, clockAt: "2026-10-21T00:30:00Z" };

// And the way out: its server has the core's stand-in channel and one message waiting for the person's yes.
const outgoing = { port: 8796 + offset };

// And Report a problem: its server plays the website's form on this computer, so the test sees what a report holds and that
// nothing is sent before Send.
const reportForm = { port: 8751 + offset };

// And the acts on mail and calendar: its server's stand-in channel serves a plain mailbox with acting on, and seeds two saved
// messages and an invitation to reply to, file away and answer.
const acts = { port: 8797 + offset };

// And the meetings: its server seeds an entry about to start with another person on it, one that has ended with nothing
// written down, and a promise of theirs gone quiet.
const meetings = { port: 8798 + offset };

// And the "Just me" check: its server is made as a person with no work makes one (nothing besides Personal), with an area, a
// person, a to-do and a question seeded, so no screen is read with work words on it.
const justMe = { port: 8799 + offset };
const capture = { port: 8800 + offset };

// And the Schedule as the review of the fb08fa7a build used it (clashes, Month with details open, Move this date, calling off): a
// fresh demo, so the clashes the other scenarios add are not counted.
const scheduleReview = { port: 8743 + offset };
// And the count of requests one click makes on Today: a fresh demo of its own, because the click keeps a review for good.
const oneClick = { port: 8745 + offset };

// And the check that a business is a group and not a project: a workspace made like the "Just me" one, to which the test adds a
// business and a project before it looks at their pages.
const sides = { port: 8763 + offset };

// And the side filter: a workspace made like the "Just me" one with a job and a business added as setup adds them, a to-do, a
// question and a promise on each side, one to-do on none and two calendars each serving a side, so each screen is read under
// every choice of the filter.
const sideFilter = { port: 8765 + offset };

// And people and record pages: a workspace like the side filter's, but a server of its own, because the tests add people, a business and
// a job to it, which the side filter's counts must not see.
const peopleRecords = { port: 8767 + offset };

// And the first day: a workspace made as a person with no work makes it, with a business set up through the setup route and
// nothing else in it but one run waiting for the first go, read as it stands (the check on rows of empty parts, and the
// captures when CAPTURE_DIR is set).
const firstDay = { port: 8764 + offset };
// And quick edits in a row: a server of its own, so a save refused as "changed since you opened it" can only be the
// screen's own race and never another scenario writing Settings at the same moment.
const quickEdits = { port: 8766 + offset };
const assistantBusy = { port: 8776 + offset };
// The data-and-trust checks edit records (several quick edits, a follow-on), so they have a server of their own.
const dataTrust = { port: 8775 + offset };

// And a person with several businesses whose names are long: Personal beside a job and three businesses (the many-sides seed),
// read at a phone, a tablet and a desktop width.
const manySides = { port: 8771 + offset };

// The journeys start the app as a person does (a new workspace, then the serve command) beside a process that plays the
// outside services; each pair works in one state folder that the start-up script clears. Two pairs: one for the
// journeys that share a workspace (a new workspace, a folder, an add-on installed from the list), and one for the
// mail journey, whose workspace has the mail add-on on and has not yet pressed Go, and one for the new-start journey,
// whose workspace has nothing and whose catalog offers the mail add-on. The services answer over HTTPS
// as well, with a certificate from a throwaway authority that the app trusts through its environment.
const pair = (port: number, fakePort: number, httpsPort: number) => ({
  port: port + offset,
  fakePort: fakePort + offset,
  httpsPort: httpsPort + offset,
  state: join(tmpdir(), `cockpit-journeys-${port + offset}`),
});
const journeys = pair(8783, 8790, 8791);
const mail = pair(8784, 8792, 8793);
const newStart = pair(8785, 8794, 8795);
const evening = pair(8760, 8761, 8762);
// The setup and Settings fixes of the re-sweep (X94 to X104): the app with the add-ons on, beside the fake services, in a
// workspace the journey makes as a person does (AI step, folder chooser, backup folder, Add connection, Esc).
const settingsFixes = pair(8772, 8773, 8774);
// The frame's own checks (H5-06, H5-11): a fresh install, walked as far as a message (taking a business back out, with Undo) shows
// on a setup step, then Today, so the message's place and the page's height are measured on a real step and a real screen.
const frame = pair(8709, 8710, 8711);
// The people the assistant offers after setup (batch PO1, H5-78 and H5-79): a fresh install whose People step is skipped, then a look's
// people arrive; they are a line on Today, taken in one change each, and the walkthrough stays shut.
const peopleOffers = pair(8715, 8716, 8717);
// A person with three accounts of one mail and calendar service: the app with the mail add-on on, beside fake services that play
// three people (`--accounts 3`), signed in one after the other through the service's own page.
const accounts = pair(8768, 8769, 8770);
// The rough paths (U4-0b): a fresh install with the mail add-on on, where a person presses only Continue and skip, then does
// the things that go wrong on the screens after it (Today, Settings, the pick-lists).
const rough = pair(8740, 8741, 8742);

// The review's setup and Settings fixes (batch R2): a workspace made as a person makes it, with the mail add-on on, beside fake
// services that play three people, so setup is walked from its first screen and Settings is read on the same workspace.
const reviewR2 = pair(8734, 8735, 8736);

// One sent message held by three mailboxes (batch R4b, S-0356): setup is walked with three accounts signed in, each of whose
// sent folder holds the same message, and the first Start makes one to-do from it.
const threeMailboxes = pair(8720, 8721, 8722);

// What each connected account is for, and what Handled for you shows of what was set aside (batch RE3, S-0642 and S-0641): setup is walked
// with a job beside Personal and two accounts, each with a set-aside mailing whose link names its account.
const re3 = pair(8712, 8713, 8714);

// A setup journey on a real-sized mailbox (batch RE4, S-0643): the fake mail service holds hundreds of messages over two months and
// slows a read of older mail down partway; setup is walked from a fresh install through a sign-out and a sign-in again.
const re4 = pair(8600, 8601, 8602);

// Two accounts on a real-sized mailbox each, under a rate limit that refuses like a real mail service (batch G6, S-0668): setup is
// walked from a fresh install with both signed in and a month read in full, and what the service was asked is checked against its
// own penalty windows.
const re5 = pair(8603, 8604, 8605);
/** Seconds the made-up mail service refuses an account's every request after a refusal; the journey reads it to check the windows. */
const QUOTA_PENALTY = 6;
process.env.JOURNEY_RE5_QUOTA_PENALTY = String(QUOTA_PENALTY);

// The closing tests of batch R3 (Today, notes and to-dos): the many-sides workspace with notes, long and many to-dos, today's
// entries past and to come, and four items that share a word, so each is read as the reviewer read it.
const reviewR3 = { port: 8730 + offset };
// Batch R4's closing tests: the many-sides workspace with a business's called-off meeting, overdue to-dos on two sides and repeating solo entries.
const reviewR4 = { port: 8728 + offset };
// The bug hunt's worst-case workspace (five sides, 50+ to-dos, a week of clashes, reviews held under several sides, three accounts):
// the fixes of hunt H1 are proved on it, in order, because they close, undo and add.
const worstCase = { port: 8726 + offset };

// The browser tests ask the fake services for what they were asked; they read where from here.
process.env.JOURNEY_FAKE_PORT = String(journeys.fakePort);
process.env.JOURNEY_MAIL_FAKE_PORT = String(mail.fakePort);
process.env.JOURNEY_NEW_START_FAKE_PORT = String(newStart.fakePort);
process.env.JOURNEY_EVENING_FAKE_PORT = String(evening.fakePort);
process.env.JOURNEY_SETTINGS_FAKE_PORT = String(settingsFixes.fakePort);
process.env.JOURNEY_FRAME_FAKE_PORT = String(frame.fakePort);
process.env.JOURNEY_ACCOUNTS_FAKE_PORT = String(accounts.fakePort);
process.env.JOURNEY_ROUGH_FAKE_PORT = String(rough.fakePort);
process.env.JOURNEY_R2_FAKE_PORT = String(reviewR2.fakePort);
process.env.JOURNEY_THREE_FAKE_PORT = String(threeMailboxes.fakePort);
process.env.JOURNEY_RE3_FAKE_PORT = String(re3.fakePort);
process.env.JOURNEY_RE4_FAKE_PORT = String(re4.fakePort);
process.env.JOURNEY_RE5_FAKE_PORT = String(re5.fakePort);

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

const on = <T,>(group: number, server: T) => ({ group, server });

// Every app and made-up service starts at the run's moment (PW_CLOCK_AT, see e2e/clock.ts), and every page is set to it, so the two agree.
// A project that runs at another moment starts its server there; its pages follow the server, so nothing else names it.
const clockFlag = ` --clock-at ${momentAt}`;
const atMoment = { env: { E2E_CLOCK_AT: momentAt } };

// The app is told where the made-up services' helpers are: its stall watcher (tests/e2e_stall_watch.py, on only when
// E2E_STALL_DIR names a folder) asks them what they were asked.
const freshServer = (p: ReturnType<typeof pair>, flags: string, env: Record<string, string> = {}) =>
  on(p.port, {
    env: { ...atMoment.env, E2E_FAKE_ADDRESS: `http://127.0.0.1:${p.fakePort}`, ...env },
    command: `uv run python -m tests.e2e_fresh_server --port ${p.port} --state "${p.state}" --https-port ${p.httpsPort} ${flags}`,
    cwd: "..",
    url: `http://127.0.0.1:${p.port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  });

// Started after the app, which clears the state folder first.
const fakeServices = (p: ReturnType<typeof pair>, flags = "") =>
  on(p.port, {
    ...atMoment,
    command: `uv run python -m tests.fake_services --port ${p.fakePort} --https-port ${p.httpsPort} --state "${p.state}" ${flags}`,
    cwd: "..",
    url: `http://127.0.0.1:${p.fakePort}/__e2e/info`,
    reuseExistingServer: false,
    timeout: 60_000,
  });

// Every project; a run that names some starts only the servers they reach (see playwright.select.ts).
export const allProjects = [
  // The acceptance scenario and the shell checks share a server, so the shell checks wait for the scenario to finish.
  ...servers.flatMap((s) => {
    const use = { baseURL: `http://127.0.0.1:${s.port}${s.base === "/" ? "/" : `${s.base}/`}` };
    return [
      { name: s.name, testMatch: /acceptance\.spec\.ts/, use },
      { name: `${s.name}-shell`, testMatch: /(shell|brand)\.spec\.ts/, use, dependencies: [s.name] },
      // The panes the shell opens (drawer, Ask pane, the stages board, review mode), and every main screen's accessibility
      // checks in light and dark at four widths (once, at the root; the nested path changes no screen).
      { name: `${s.name}-panes`, testMatch: /panes\.spec\.ts/, use, dependencies: [s.name] },
      ...(s.base === "/" ? [{ name: `${s.name}-settings`, testMatch: /settings-walk\.spec\.ts/, use, dependencies: [s.name] }] : []),
      ...(s.base === "/" ? [{ name: `${s.name}-a11y`, testMatch: /a11y\.spec\.ts/, use, dependencies: [s.name] }] : []),
      // The schedule at a phone, a tablet and a desktop width, and moving through its days (once, at the root).
      ...(s.base === "/" ? [{ name: `${s.name}-schedule`, testMatch: /schedule\.spec\.ts/, use, dependencies: [s.name] }] : []),
      // The tables beside the detail pane at 1440px (once, at the root).
      ...(s.base === "/" ? [{ name: `${s.name}-tables`, testMatch: /tables\.spec\.ts/, use, dependencies: [s.name] }] : []),
    ];
  }),
  { name: "layout", testMatch: /(layout|sh1-shell|handled|guards|internals|changed-rows|changed-widths|today-work|shared-rules|today-todos-46|counts-status|qf1-forms-and-todos|guess-and-ai-defaults|hand-over-one-door|states-phone|w1-today-lines|learned-review|learned-on-its-own|read-back|u5-changed|u6-[a-z]+)\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${layout.port}/` } },
  { name: "access", testMatch: /(work-access|ai-costs)\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${access.port}/` } },
  { name: "one-click", testMatch: /today-one-click\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${oneClick.port}/` } },
  { name: "schedule-review", testMatch: /schedule-review\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${scheduleReview.port}/` } },
  { name: "root-timeline", testMatch: /timeline\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${timeline.port}/` } },
  { name: "capacity", testMatch: /(today-(capacity|review|rail)|u5-today)\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${capacity.port}/` } },
  { name: "outgoing", testMatch: /outgoing\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${outgoing.port}/` } },
  { name: "report-problem", testMatch: /report-problem\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${reportForm.port}/` } },
  { name: "acts", testMatch: /acts-journey\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${acts.port}/` } },
  { name: "meetings", testMatch: /meetings-journey\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${meetings.port}/` } },
  { name: "capture", testMatch: /capture-journey\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${capture.port}/` } },
  { name: "just-me", testMatch: /just-me\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${justMe.port}/` } },
  { name: "sides", testMatch: /side-is-a-group\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${sides.port}/` } },
  { name: "side-filter", testMatch: /side-filter\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${sideFilter.port}/` } },
  { name: "people-records", testMatch: /(people-records|person-quality-setup-46)\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${peopleRecords.port}/` } },
  { name: "first-day", testMatch: /first-day.*\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${firstDay.port}/` } },
  { name: "quick-edits", testMatch: /quick-edits\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${quickEdits.port}/` } },
  { name: "assistant-busy", testMatch: /assistant-busy\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${assistantBusy.port}/` } },
  { name: "data-and-trust", testMatch: /data-and-trust\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${dataTrust.port}/` } },
  { name: "late", testMatch: /late-evening\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${late.port}/` } },
  {
    name: "journeys",
    testMatch: /journeys\.spec\.ts/,
    // The made-up services' sign-in page is served with the throwaway authority's certificate, which this browser
    // doesn't know; the app itself is told to trust it (see the start-up script), and the real one is never touched.
    use: { baseURL: `http://127.0.0.1:${journeys.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "journeys-mail",
    testMatch: /journeys-mail\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${mail.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "journeys-new-start",
    testMatch: /journeys-new-start\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${newStart.port}/`, ignoreHTTPSErrors: true },
  },
  { name: "long-names", testMatch: /long-names\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${manySides.port}/` } },
  {
    name: "accounts",
    testMatch: /(^|\/)accounts\.spec\.ts$/,
    use: { baseURL: `http://127.0.0.1:${accounts.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "journeys-rough",
    testMatch: /journeys-rough\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${rough.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "settings-fixes",
    testMatch: /settings-setup-fixes\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${settingsFixes.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "frame",
    testMatch: /toast-and-scroll\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${frame.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "people-offers",
    testMatch: /people-offers\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${peopleOffers.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "journeys-three-mailboxes",
    testMatch: /journeys-three-mailboxes\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${threeMailboxes.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "journeys-real-size",
    testMatch: /journeys-real-size\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${re4.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "journeys-two-accounts",
    testMatch: /journeys-two-accounts\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${re5.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "review-re3",
    testMatch: /review-re3\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${re3.port}/`, ignoreHTTPSErrors: true },
  },
  {
    name: "review-r2",
    testMatch: /review-r2\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${reviewR2.port}/`, ignoreHTTPSErrors: true },
  },
  // The screens of the same review that need the demo data (follow-ups, to-dos): the layout server.
  { name: "review-r2-demo", testMatch: /review-r2-demo\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${layout.port}/` } },
  // And the long-name sides: the side picker and the menu's names.
  { name: "review-r2-sides", testMatch: /review-r2-sides\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${manySides.port}/` } },
  { name: "review-r3", testMatch: /review-r3\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${reviewR3.port}/` } },
  { name: "review-r4", testMatch: /review-r4\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${reviewR4.port}/` } },
  // Both files read and change the one server's records in order, so the second starts only after the first has finished.
  { name: "worst-case", testMatch: /h1-worst-case\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${worstCase.port}/` } },
  {
    name: "worst-case-t3",
    testMatch: /t3-worst-case\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${worstCase.port}/` },
    dependencies: ["worst-case"],
  },
  {
    name: "journeys-first-evening",
    testMatch: /journeys-first-evening\.spec\.ts/,
    use: { baseURL: `http://127.0.0.1:${evening.port}/`, ignoreHTTPSErrors: true },
  },
];

// Every web server, tagged with the port of the project group it serves.
export const allServers = [
    ...servers.map((s) => on(s.port, {
      command: `uv run python -m tests.e2e_server --port ${s.port} --base-path ${s.base}${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${s.port}${s.base === "/" ? "" : s.base}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    })),
    on(layout.port, {
      command: `uv run python -m tests.e2e_server --port ${layout.port} --base-path / --layout-stress${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${layout.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(access.port, {
      command: `uv run python -m tests.e2e_server --port ${access.port} --base-path / --standin-account${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${access.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(oneClick.port, {
      command: `uv run python -m tests.e2e_server --port ${oneClick.port} --base-path /${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${oneClick.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(scheduleReview.port, {
      command: `uv run python -m tests.e2e_server --port ${scheduleReview.port} --base-path /${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${scheduleReview.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(timeline.port, {
      command: `uv run python -m tests.e2e_server --port ${timeline.port} --base-path /${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${timeline.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(capacity.port, {
      command: `uv run python -m tests.e2e_server --port ${capacity.port} --base-path /${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${capacity.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(reportForm.port, {
      command: `uv run python -m tests.e2e_server --port ${reportForm.port} --base-path / --fake-report${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${reportForm.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(outgoing.port, {
      command: `uv run python -m tests.e2e_server --port ${outgoing.port} --base-path / --fake-channel${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${outgoing.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(acts.port, {
      command: `uv run python -m tests.e2e_server --port ${acts.port} --base-path / --acts${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${acts.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(meetings.port, {
      command: `uv run python -m tests.e2e_server --port ${meetings.port} --base-path / --meetings --clock-at ${momentAt ?? daytimeAt}`,
      cwd: "..",
      url: `http://127.0.0.1:${meetings.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(capture.port, {
      command: `uv run python -m tests.e2e_server --port ${capture.port} --base-path / --capture --plain-stages${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${capture.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(sides.port, {
      command: `uv run python -m tests.e2e_server --port ${sides.port} --base-path / --just-me --plain-stages${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${sides.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(sideFilter.port, {
      command: `uv run python -m tests.e2e_server --port ${sideFilter.port} --base-path / --sides --plain-stages --clock-at ${mondayAt}`,
      cwd: "..",
      url: `http://127.0.0.1:${sideFilter.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(peopleRecords.port, {
      command: `uv run python -m tests.e2e_server --port ${peopleRecords.port} --base-path / --sides --assistant-found --plain-stages${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${peopleRecords.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(quickEdits.port, {
      command: `uv run python -m tests.e2e_server --port ${quickEdits.port} --base-path /${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${quickEdits.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(assistantBusy.port, {
      command: `uv run python -m tests.e2e_server --port ${assistantBusy.port} --base-path / --assistant-ready${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${assistantBusy.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(dataTrust.port, {
      command: `uv run python -m tests.e2e_server --port ${dataTrust.port} --base-path /${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${dataTrust.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(firstDay.port, {
      command: `uv run python -m tests.e2e_server --port ${firstDay.port} --base-path / --first-day --plain-stages${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${firstDay.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(justMe.port, {
      command: `uv run python -m tests.e2e_server --port ${justMe.port} --base-path / --just-me --plain-stages${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${justMe.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(late.port, {
      command: `uv run python -m tests.e2e_server --port ${late.port} --base-path / --clock-at ${late.clockAt}`,
      cwd: "..",
      url: `http://127.0.0.1:${late.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(manySides.port, {
      command: `uv run python -m tests.e2e_server --port ${manySides.port} --base-path / --many-sides --plain-stages${clockFlag}`,
      cwd: "..",
      url: `http://127.0.0.1:${manySides.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(reviewR3.port, {
      command: `uv run python -m tests.e2e_server --port ${reviewR3.port} --base-path / --review-r3 --plain-stages --clock-at ${mondayAt}`,
      cwd: "..",
      url: `http://127.0.0.1:${reviewR3.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(reviewR4.port, {
      command: `uv run python -m tests.e2e_server --port ${reviewR4.port} --base-path / --review-r4 --plain-stages --clock-at ${mondayAt}`,
      cwd: "..",
      url: `http://127.0.0.1:${reviewR4.port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    }),
    on(worstCase.port, {
      command: `uv run python -m tests.e2e_server --port ${worstCase.port} --base-path / --worst-case --clock-at ${daytimeAt}`,
      cwd: "..",
      // Ready when the seed's own background work (the stand-in sign-ins and what is read from them) is over.
      url: `http://127.0.0.1:${worstCase.port}/__e2e/worst-case-ready`,
      reuseExistingServer: false,
      timeout: 90_000,
    }),
    freshServer(threeMailboxes, "--mail"),
    fakeServices(threeMailboxes, "--accounts 3 --sent-mail"),
    // A month read in full is also the go for what it brings (the person's pick), so a real-sized mailbox's month is worked by
    // the made-up assistant at its made-up prices: about two dollars, the default daily limit. The limit is raised here so the
    // journey tests the walk, not the default limit's edge (a limit reached is shown by test_first_reading_waits.py and test_silent_stops.py).
    freshServer(re4, "--mail --small-pages", { COCKPIT__AI__BUDGETS__PER_DAY_USD: "10", COCKPIT__AI__BUDGETS__PER_MONTH_USD: "30" }),
    fakeServices(re4, "--accounts 1 --big-mailbox"),
    // Two real-sized accounts read a month each: the same limit as above, raised for the same reason.
    freshServer(re5, "--mail --small-pages", { COCKPIT__AI__BUDGETS__PER_DAY_USD: "10", COCKPIT__AI__BUDGETS__PER_MONTH_USD: "30" }),
    fakeServices(re5, `--accounts 2 --big-mailbox --quota-rate 1 --quota-penalty ${QUOTA_PENALTY}`),
    freshServer(re3, "--mail --no-sent-mail"),
    fakeServices(re3, "--accounts 2 --account-links"),
    freshServer(reviewR2, "--mail --no-sent-mail"),
    fakeServices(reviewR2, "--accounts 3"),
    freshServer(accounts, "--mail --no-sent-mail --test-routes"),
    fakeServices(accounts, "--accounts 3"),
    freshServer(journeys, "--add-ons"),
    fakeServices(journeys),
    freshServer(mail, "--mail --no-sent-mail"),
    fakeServices(mail),
    // The new-start journey changes nothing by hand: the catalog is named through the environment, and what the app
    // prints is kept so the restarts can be counted.
    freshServer(newStart, "--add-ons --catalog-by-environment --log"),
    fakeServices(newStart, "--catalog journey_mail --sent-mail --notice-mail"),
    // The same start as the new-start journey: the mail add-on is installed from the catalog, which restarts the app once.
    freshServer(rough, "--add-ons --catalog-by-environment --log"),
    fakeServices(rough, "--catalog journey_mail --sent-mail"),
    freshServer(settingsFixes, "--add-ons"),
    fakeServices(settingsFixes),
    freshServer(frame, ""),
    fakeServices(frame),
    freshServer(peopleOffers, ""),
    fakeServices(peopleOffers),
    // A first evening: the same start as the new-start journey, with the fake services' evening mail and model list.
    freshServer(evening, "--add-ons --catalog-by-environment --log --no-sent-mail"),
    fakeServices(evening, "--catalog journey_mail --evening"),
];

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  // One lane per server: each project has its own server and workspace, so projects run side by side, while the tests
  // inside a project (and the two that share a server, below) run in order. PW_WORKERS lowers it on a small machine.
  fullyParallel: false,
  workers: Number(process.env.PW_WORKERS) || 5,
  // One automatic re-run of a failed test The list reporter prints, under "flaky", every test that
  // passed only on its re-run, so nothing is hidden; a test on that list three times gets a story. PW_RETRIES=0 turns it
  // off for a debugging run.
  retries: process.env.PW_RETRIES === undefined ? 1 : Number(process.env.PW_RETRIES),
  reporter: [["list"]],
  use: {
    ...devices["Desktop Chrome"],
    launchOptions: { executablePath },
    // Opt-in only: PW_CHANNEL=chrome runs the tests in the installed Google Chrome instead of the bundled browser.
    ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
    permissions: ["clipboard-read", "clipboard-write"],
    // The tests' own calls (`page.request`, `request`) carry no page storage, so they send the harness's token, which the
    // test servers keep as a session value. The page signs itself in from the link as a person's page does.
    extraHTTPHeaders: { Authorization: "Bearer e2e-token" },
    // No entry animations, so accessibility checks never catch a toast half faded in.
    contextOptions: { reducedMotion: "reduce" },
  },
  projects: allProjects,
  webServer: selectServers(allServers, allProjects, namedProjects(process.argv, process.env)),
});
