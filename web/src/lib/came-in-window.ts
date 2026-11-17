// The stretch of time Came in is narrowed to when a line of Today (the one for what arrived while the person was away) opens
// it: only the mail received from `from` to `to` is listed, with a way back to all of it. Kept for the page as a whole so
// the line and the card, which sit in different columns, agree.
import { useSyncExternalStore } from "react";

export type CameInWindow = { from: string; to: string };

let current: CameInWindow | null = null;
const listeners = new Set<() => void>();

function set(next: CameInWindow | null) {
  current = next;
  listeners.forEach((l) => l());
}

export function narrowCameIn(window: CameInWindow) {
  set(window);
  // Came in opens where it is folded and takes the cursor (CameInCard's PointedTo), so nothing is moved from here.
}

export function showAllCameIn() {
  set(null);
}

export function useCameInWindow(): CameInWindow | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}

/** Whether a message was received inside the window; with no window every message is. */
export function inCameInWindow(received: string, window: CameInWindow | null): boolean {
  if (!window) return true;
  const at = Date.parse(received);
  return at >= Date.parse(window.from) && at <= Date.parse(window.to);
}
