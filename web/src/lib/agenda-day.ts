// How one day's entries are laid out on Today's Schedule card, written once: all-day entries first, then the timed ones in the
// order of their start (the app's own entries among the calendars' own, never after them), with what has already ended folded
// away into one line ahead of "now", so the card opens on what is still to come and "1 more" never hides the next entry.
import type { S } from "./api";

type Entry = S["AgendaItemView"];

/** Whether a timed entry has ended by `now`; an all-day entry never has, for the card's day. */
export const hasEnded = (e: Entry, now: Date): boolean => !e.all_day && new Date(e.end ?? e.start).getTime() <= now.getTime();

export interface DayLayout {
  /** All-day entries, in the order given. */
  allDay: Entry[];
  /** Timed entries that have ended, earliest first. */
  past: Entry[];
  /** Timed entries still to come or under way, earliest first. */
  upcoming: Entry[];
}

/** One day's entries in time order, split into what has passed and what has not (`now` is the moment the card is drawn at). */
export function layOutDay(events: readonly Entry[], now: Date): DayLayout {
  const at = (e: Entry) => new Date(e.start).getTime();
  const timed = events.filter((e) => !e.all_day).sort((a, b) => at(a) - at(b) || a.title.localeCompare(b.title));
  return {
    allDay: events.filter((e) => e.all_day),
    past: timed.filter((e) => hasEnded(e, now)),
    upcoming: timed.filter((e) => !hasEnded(e, now)),
  };
}
