// What was typed in the search box of a page that has no settings to search (Connections, Add-ons, what each account can do):
// the box hands it to Settings, which opens with that search already made. Held once, read once.
let pending = "";
// Whether the search box that handed a search on had the cursor, so the page that opens puts the cursor in its own box at once.
let carrying = false;

/** Keeps what was typed for the Settings page that opens next. The box that hands it on shows nothing of it, so each key
 *  typed there before the next page is drawn is one more letter of the same search, not a new search. */
export function handOffSearch(query: string): void {
  pending = pending === "" ? query : pending + query;
  carrying = true;
}

/** What was handed off, without taking it: a screen reads this while it is being drawn, and a draw can be started more
 *  than once before it is shown (its code may still be arriving), so reading must change nothing. */
export function peekSearch(): string {
  return pending;
}

/** What was handed off, once: the next read finds nothing. Called when the screen that read it is on the page. */
export function takeSearch(): string {
  const query = pending;
  pending = "";
  return query;
}

/** Whether a search was just handed on from a box that had the cursor: true once, to the box that now takes its place. */
export function takeCarriedCursor(): boolean {
  const was = carrying;
  carrying = false;
  return was;
}
