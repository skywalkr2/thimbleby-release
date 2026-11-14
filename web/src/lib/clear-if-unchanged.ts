import type { Dispatch, SetStateAction } from "react";

/**
 * After a save answers, empties a field only when it still holds what was saved. Text typed while the save was on its way
 * (a next entry started at once) stays, instead of being wiped by the late clear.
 */
export function clearIfUnchanged(set: Dispatch<SetStateAction<string>>, saved: string): void {
  set((now) => (now === saved ? "" : now));
}
