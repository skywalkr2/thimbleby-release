// What Today's queue holds still for the person, and the one way to let it go. The list holds while the person is working in
// it (keyboard focus or the pointer in it, or a line open); new lines then wait behind "N new · Show", and a line settled
// somewhere else stays in place until the person moves on. Showing the waiting lines is a window event, so the key, the
// button and a screen reader's command all do the same thing.
const SHOW_NEW = "queue-show-new";

/** Lets go of what the queue is holding: the waiting lines come in, and the lines settled elsewhere leave. */
export function showNewLines(): void {
  window.dispatchEvent(new Event(SHOW_NEW));
}

/** Calls `run` whenever the lines are asked to be shown; returns the way to stop listening. */
export function onShowNewLines(run: () => void): () => void {
  window.addEventListener(SHOW_NEW, run);
  return () => window.removeEventListener(SHOW_NEW, run);
}

const UNDO_STARTED = "queue-undo-started";

/** Said when the person takes an action back: a line they settled and that now comes back is drawn closed, whether or not the
 * list was ever read without it, so what they see does not depend on how fast the answer and the Undo followed each other. */
export function undoStarted(): void {
  window.dispatchEvent(new Event(UNDO_STARTED));
}

/** Calls `run` when an Undo starts; returns the way to stop listening. */
export function onUndoStarted(run: () => void): () => void {
  window.addEventListener(UNDO_STARTED, run);
  return () => window.removeEventListener(UNDO_STARTED, run);
}

const UNDO_ENDED = "queue-undo-ended";

/** Said when an Undo has finished, whether it worked or not: the lists have been asked to read again. */
export function undoEnded(): void {
  window.dispatchEvent(new Event(UNDO_ENDED));
}

/** Calls `run` when an Undo ends; returns the way to stop listening. */
export function onUndoEnded(run: () => void): () => void {
  window.addEventListener(UNDO_ENDED, run);
  return () => window.removeEventListener(UNDO_ENDED, run);
}
