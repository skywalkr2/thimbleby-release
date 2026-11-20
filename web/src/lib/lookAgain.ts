/** How often the People step reads the look's state again while it waits for mail or works. */
export const LOOK_EVERY_MS = 3000;
/** How often it is read again while nothing is offered and no look is at work: a later look's offers show without a reload. */
export const LOOK_AGAIN_EVERY_MS = 15000;

/** With nothing offered, how soon the step asks again: never when no assistant is set up, since nothing can change by itself. */
export function lookAgainIn(state: string): number | false {
  if (state === "no_account") return false;
  return state === "not_yet" || state === "working" ? LOOK_EVERY_MS : LOOK_AGAIN_EVERY_MS;
}
