// The fixes of bug hunt T3, proved in a browser on the hunt's worst-case workspace (the tier 3 seed: files of several kinds, knowledge
// proposed, kept and discarded, teams, an organization with nothing to list, stage items with no name). The tests run in order and
// read what the earlier ones left.
import { expect, type Page } from "@playwright/test";
import { test } from "./test";
import { openScreen } from "./open-screen";

test.describe.configure({ mode: "serial" });

const AUTH = { Authorization: "Bearer e2e-token" };

async function json<T>(page: Page, path: string): Promise<T> {
  return (await (await page.request.get(path, { headers: AUTH })).json()) as T;
}

const toasts = (page: Page) => page.getByRole("region", { name: "Notifications" });

async function teamId(page: Page, name: string): Promise<string> {
  const teams = await json<Array<{ id: string; name: string }>>(page, "api/teams");
  return teams.find((t) => t.name === name)!.id;
}

test("Keep, Stop using and Add word pressed twice fast act once and say nothing odd (T3-01, T3-02, T3-03)", async ({ page }) => {
  await openScreen(page, "records/knowledge");
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/knowledge\//.test(request.url())) posts.push(new URL(request.url()).pathname.replace(/^.*\/api\//, ""));
  });
  const keep = page.getByRole("button", { name: /^Keep: / }).first();
  await keep.dblclick();
  await expect(toasts(page).getByText(/^Kept\./)).toBeVisible();
  await expect(toasts(page).getByRole("button", { name: "Undo" })).toBeVisible();
  await expect(toasts(page).getByText(/didn't work/)).toHaveCount(0);
  expect(posts.filter((p) => p.endsWith("/keep")).length).toBe(1);
  const stop = page.getByRole("button", { name: /^Stop using: / }).first();
  await stop.dblclick();
  await expect(toasts(page).getByText(/No longer used/)).toBeVisible();
  await expect(toasts(page).getByText(/didn't work|isn't active|LES-/)).toHaveCount(0);
  expect(posts.filter((p) => p.endsWith("/retire")).length).toBe(1);
  await page.getByLabel("A word").fill("Zebra");
  await page.getByRole("button", { name: "Add word" }).dblclick();
  await expect(toasts(page).getByText(/Added Zebra to your words/)).toBeVisible();
  await expect(page.getByText("Zebra", { exact: true })).toHaveCount(1);
});

test("a retired entry and one set aside are listed with Use again, which brings them back (T3-10)", async ({ page }) => {
  await openScreen(page, "records/knowledge");
  await page.getByText("Not used in a while, and what was retired").click();
  const retired = page.getByRole("list", { name: "No longer used" });
  await expect(retired.getByRole("button", { name: /^Use again: / }).first()).toBeVisible();
  const aside = page.getByRole("list", { name: "What was set aside" });
  const count = await aside.getByRole("listitem").count();
  expect(count).toBeGreaterThan(0);
  await aside.getByRole("button", { name: /^Use again: / }).first().click();
  await expect(toasts(page).getByText("Using this again.")).toBeVisible();
  await expect(toasts(page).getByRole("button", { name: "Undo" })).toBeVisible();
  await toasts(page).getByRole("button", { name: "Undo" }).click();
  await expect(toasts(page).getByText("Undone.")).toBeVisible();
});

test("a team: weekday clicked twice sends one change, a blank or repeated name is refused, people are put on and taken off (T3-04, T3-05, T3-06, T3-09)", async ({ page }) => {
  const id = await teamId(page, "Delivery drivers");
  await openScreen(page, `record:team:${id}`);
  let edits = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/records/edit")) edits += 1;
  });
  const monday = page.getByRole("checkbox", { name: "Monday" });
  await monday.dblclick();
  await expect(toasts(page).getByText(/^Changed/)).toBeVisible();
  expect(edits).toBe(1);
  await page.getByRole("button", { name: "Edit details" }).click();
  const form = page.getByRole("form", { name: "Edit details" });
  await form.getByLabel("Name", { exact: true }).fill("     ");
  await expect(form.getByRole("button", { name: "Save" })).toBeDisabled();
  await expect(form.getByText("Name can't be empty.")).toBeVisible();
  await form.getByLabel("Name", { exact: true }).fill("Empty team");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(form.getByText(/already a team called Empty team/)).toBeVisible();
  await form.getByRole("button", { name: "Cancel" }).click();
  // People on the team come from a list, and each can be taken off, with Undo.
  const people = page.getByRole("region", { name: "People" });
  const first = people.getByRole("listitem").first();
  const who = (await first.getByRole("link").first().innerText()).trim();
  await people.getByRole("button", { name: `Take ${who} off the team` }).dblclick();
  await expect(toasts(page).getByText(`${who} is off the team.`)).toBeVisible();
  await expect(people.getByRole("link", { name: who })).toHaveCount(0);
  await toasts(page).getByRole("button", { name: "Undo" }).click();
  await expect(people.getByRole("link", { name: who })).toBeVisible();
  await expect(people.getByRole("textbox")).toHaveCount(0);
});

test("People lists the teams, a team opens, and a person's page says their teams (T3-09)", async ({ page }) => {
  await openScreen(page, "records/people");
  const list = page.getByRole("list", { name: "Teams" });
  await expect(list.getByRole("link", { name: "Empty team" })).toBeVisible();
  await list.getByRole("link", { name: "Kitchen and front of house" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Kitchen and front of house" })).toBeVisible();
  const teams = await json<Array<{ name: string; people: string[] }>>(page, "api/teams");
  const member = teams.find((t) => t.name === "Kitchen and front of house")!.people[0];
  await openScreen(page, `record:person:${member}`);
  await expect(page.getByText("Kitchen and front of house").first()).toBeVisible();
});

test("an organization with nothing to list opens its edit form (T3-08)", async ({ page }) => {
  const orgs = await json<Array<{ id: string; name: string; side: string | null }>>(page, "api/organizations");
  const org = orgs.find((o) => o.name.startsWith("Brightwater"))!;
  await openScreen(page, `records/organization/${org.id}`);
  await page.getByRole("button", { name: "Edit details" }).click();
  await expect(page.getByRole("form", { name: "Edit details" }).getByLabel("Name", { exact: true })).toHaveValue(org.name);
});

test("a count past what one list holds is refused, and People, the person's page and the menu say the same number (T3-07, T3-11)", async ({ page }) => {
  await openScreen(page, "quality");
  await page.getByText("Count them yourself").first().click();
  await page.getByLabel("Promises on your own list").fill("999999999999");
  await page.getByLabel("Of those, how many the app didn't have").fill("1");
  await expect(page.getByText(/more than one list can hold/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" }).first()).toBeDisabled();
  const me = (await json<Array<{ id: string; is_pm: boolean; open_items: number }>>(page, "api/people")).find((p) => p.is_pm)!;
  await openScreen(page, "records/people");
  await expect(page.getByRole("list", { name: "People" }).getByRole("listitem").first()).toContainText(`${me.open_items} open item`);
  await openScreen(page, `record:person:${me.id}`);
  const heading = page.getByRole("heading", { name: "What's waiting for you" });
  await expect(heading).toBeVisible();
  const said = await heading.locator("..").innerText();
  expect(said).toContain(String(me.open_items));
});

test("under a side's filter a file on no side stays listed and says Every side (T3-12)", async ({ page }) => {
  const lines = await json<Array<{ side: string | null }>>(page, "api/today/queue");
  const side = lines.map((l) => l.side).find((s): s is string => !!s)!;
  await openScreen(page, "today");
  await page.evaluate((id) => window.localStorage.setItem("cockpit:side-filter", id), side);
  await openScreen(page, "records/files");
  await expect(page.getByRole("listitem", { name: "notes.txt" }).getByText(/Every side/)).toBeVisible();
  await page.evaluate(() => window.localStorage.removeItem("cockpit:side-filter"));
});

test("an item with no name goes by a plain word on Stages, never its id (T3-13)", async ({ page }) => {
  await openScreen(page, "work/stages");
  await expect(page.getByText(/^REM-\d+$/)).toHaveCount(0);
  await expect(page.getByText("An item with no name").first()).toBeVisible();
});

test("the menu's badge beside To-dos is the sum of the two numbers the page says, and the tabs say them (S-0539)", async ({ page }) => {
  await openScreen(page, "work/open");
  const menu = await page.getByRole("navigation").getByRole("link", { name: /^To-dos/ }).first().getAttribute("aria-label");
  const badge = Number(/(\d+) (?:needs|need) you/.exec(menu ?? "")?.[1]);
  expect(badge).toBeGreaterThan(0);
  const main = page.locator("main");
  const head = await main.innerText();
  const yours = Number(/(\d+) yours/.exec(head)?.[1]);
  const asked = Number(/(\d+) questions? for you/.exec(head)?.[1]);
  expect(yours + asked).toBe(badge);
  await expect(main.getByRole("button", { name: /^To-dos/ })).toContainText(String(yours));
  await expect(main.getByRole("button", { name: /^Questions/ })).toContainText(String(asked));
});
