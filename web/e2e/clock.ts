// The clock of every browser project. Each project's server starts its clock at a moment (`--clock-at`, in playwright.config.ts)
// and every page follows its own server (the `test` in ./test.ts asks it for its moment), so the
// two agree whatever the hour the run starts at, and no seed or wait depends on "now".
//
// - `momentAt`: the moment every project runs at, unless its server is started at another (the late-evening one). `PW_CLOCK_AT` (an ISO
//   moment in UTC, such as 2026-11-10T23:30:00Z) names it, to prove a run at a given hour; unset, it is noon UTC (the test
//   workspaces' time zone) on the day the run starts.
// - `daytimeAt`: for a project whose screens are right to read the hour (Today holds what the assistant suggests during quiet hours
//   and shows the evening wrap-up; an entry made "forty minutes from now" must fall on today). Its test is about the daytime, so
//   its server and page always run at noon UTC, on the day of `momentAt`.
//
// The config reads both before it starts the workers and leaves them in the environment, so every process agrees and a run
// that crosses midnight keeps one day.
export const momentAt: string = (process.env.PW_CLOCK_AT ||= `${new Date().toISOString().slice(0, 10)}T12:00:00Z`);
export const daytimeAt: string = (process.env.PW_DAYTIME_AT ||= `${momentAt.slice(0, 10)}T12:00:00Z`);

/** Noon UTC of the first date on or after `from` that falls on `weekday` (0 is Sunday, 1 is Monday, as `Date.getUTCDay` counts). */
export const weekdayAt = (weekday: number, from: string = daytimeAt): string => {
  const start = new Date(from);
  const ahead = (weekday - start.getUTCDay() + 7) % 7;
  return `${new Date(start.getTime() + ahead * 86_400_000).toISOString().slice(0, 10)}T12:00:00Z`;
};

// - `mondayAt`: for a project whose screens read the weekday. Today shows the Monday briefing on its weekly day only (and
//   the weekly form beside the morning brief on the days after it), so a test of what that briefing holds, or of a side's
//   filter over it, runs on a Monday: its server always starts at noon UTC of the first Monday on or after `daytimeAt`,
//   whatever day the run starts. The clock is moved inside the server process (`--clock-at`, time-machine), never by faketime.
export const mondayAt: string = weekdayAt(1);
