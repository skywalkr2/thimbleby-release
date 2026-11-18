import { expect, test } from "vitest";

// S-0409: the app never reloads a page by itself. A reload under an open review or approval would drop it and show the same
// change to approve twice; a new version is announced ("An update is ready", `UpdateReadyBanner`) and the person reloads.
// This reads the sources: a reload is only ever the call of a button the person presses.

const sources = import.meta.glob(["../**/*.ts", "../**/*.tsx", "!../**/*.test.ts", "!../**/*.test.tsx", "!../api/schema.d.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** The files with a reload, each inside a button's click: the start-up problem page, the failed part, and the update banner. */
const BUTTONS = new Set(["../main.tsx", "../ui/PartBoundary.tsx", "../ui/UpdateReadyBanner.tsx"]);

test("no code reloads the page except inside a button the person presses", () => {
  const found: string[] = [];
  for (const [file, text] of Object.entries(sources)) {
    for (const line of text.split("\n")) {
      if (!/location\.reload\(/.test(line)) continue;
      if (BUTTONS.has(file) && /onClick=/.test(line)) continue;
      found.push(`${file}: ${line.trim()}`);
    }
  }
  expect(found).toEqual([]);
});
