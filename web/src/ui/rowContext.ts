// Whether a button is drawn among a row's actions (ui/Row). A row's actions are never solid, so a primary button there is
// drawn as an outline; the button reads this to say so in its weight (`data-weight`), which the browser tests count.
import { createContext } from "react";

export const InRowActions = createContext(false);

/** The screen's one filled button is in this row: the row's actions keep the filled weight for a primary button, which an
 * action in a row is otherwise never drawn with. Set by the screen around the one row that carries it. */
export const FilledPrimary = createContext(false);

/** Set by an Item (ui/ItemList): an Actions group inside it that sits at the start (a row's own actions, never a form's Save at the
 * end) is a row's actions, so its primary button is drawn as an outline like those of a Row. */
export const InItem = createContext(false);

/** Set around a list of gaps (Today's "Finish setting up"): its rows are plain lines with no menu and no more than their one action,
 * drawn as a quiet text button, the group's one outlined "Continue setup" being the way on. */
export const PlainRows = createContext(false);

/** Set by a Row inside PlainRows: a primary or outline button among its actions is drawn as the quiet text button. */
export const QuietActions = createContext(false);

/** Set around every item of a list after the first when the list's items each have a button for the likeliest answer: only the
 * first keeps the filled weight, so a pane holds one filled button at a time (a `primary` button inside is drawn as the outline). */
export const OnlyFirstFilled = createContext(false);
