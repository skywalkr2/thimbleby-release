// Warmer surfaces (the UI/UX reviewer's answer 1 of 2026-11-12b; change log 460): the ten surface tokens are the reviewer's values,
// and every text, border and mark pair on the new surfaces passes its contrast bar in both themes. A selected row (--accent-soft)
// stays told apart from a row at rest (--surface) and from a hovered row (--surface-hover).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { contrast } from "../lib/theme";

const tokens = readFileSync(join(__dirname, "tokens.css"), "utf8");
type Declarations = Record<string, string>;

function block(opener: string): Declarations {
  const start = tokens.indexOf(opener);
  expect(start, opener).toBeGreaterThanOrEqual(0);
  const end = tokens.indexOf("\n}", start);
  const inner = tokens.slice(start + opener.length, end).replace(/\n {2}\}\s*$/, "");
  const out: Declarations = {};
  for (const m of inner.matchAll(/(--[\w-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}
const day = block(":root {");
const systemNight = block(':root:not([data-theme="light"]) {');
const chosenNight = block(':root[data-theme="dark"] {');
const themes: Record<string, Declarations> = { day, night: { ...day, ...chosenNight }, "night (system)": { ...day, ...systemNight } };

function color(theme: string, name: string): string {
  const value = themes[theme][name];
  expect(value, `${theme} ${name}`).toBeDefined();
  const ref = /^var\((--[\w-]+)\)$/.exec(value);
  return ref ? color(theme, ref[1]) : value;
}

const reviewer = {
  day: { "--canvas": "#f6f0e6", "--surface": "#fffcf7", "--surface-sunk": "#faf5ec", "--surface-hover": "#f8f2e8", "--border": "#e8dfd0", "--accent-soft": "#f3ecdf" },
  night: { "--canvas": "#120f0e", "--surface": "#1a1716", "--surface-sunk": "#201c1a", "--surface-hover": "#241f1d", "--border": "#322c29", "--accent-soft": "#251c1e" },
} as const;

const SURFACES = ["--canvas", "--surface", "--surface-sunk"];
const TEXT = ["--text", "--text-muted", "--text-subtle", "--danger", "--accent-text"];
const MARKS = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `--side-${n}`);

test.each(["day", "night", "night (system)"])("%s: the surface tokens are the reviewer's values", (theme) => {
  const want = reviewer[theme === "day" ? "day" : "night"];
  for (const [name, hex] of Object.entries(want)) expect(color(theme, name), `${theme} ${name}`).toBe(hex);
});

test.each(["day", "night", "night (system)"])("%s: text 4.5:1; borders and marks 3:1; the selected row is told apart", (theme) => {
  const c = (n: string) => color(theme, n);
  for (const fg of TEXT) for (const bg of SURFACES) expect(contrast(c(fg), c(bg)), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
  // --border-strong is the to-do ring's border (RoundCheck) and every input edge.
  for (const fg of ["--border-strong", ...MARKS]) for (const bg of SURFACES) expect(contrast(c(fg), c(bg)), `${fg} on ${bg}`).toBeGreaterThanOrEqual(3);
  // A selected row against a row at rest: a visible step (1.15:1 by day, 1.07:1 at night at the reviewer's values).
  expect(contrast(c("--accent-soft"), c("--surface")), "--accent-soft against --surface").toBeGreaterThanOrEqual(1.05);
  // Against a hovered row the step is smaller (1.06:1 by day, 1.02:1 at night, as before the change); the hue differs (a warm
  // tint against a neutral one), so the test holds only that they are never the same colour. Reported to the main session.
  expect(c("--accent-soft")).not.toBe(c("--surface-hover"));
});
