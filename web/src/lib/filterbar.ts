// When a list shows its filter bar (the visual standard, "the layout adapts to the amount of content"): a list that holds fewer rows
// than this has nothing worth narrowing, so no filter bar is drawn above it. A filter that is on keeps its bar, so the person can
// always take it off.

/** The fewest rows a list holds for its filter bar to be drawn. */
export const FILTER_BAR_MIN = 12;

let least = FILTER_BAR_MIN;

/** Sets the fewest rows for a bar (a test of one screen's filters draws the bar over a short list; the rule itself is tested at the real number). */
export function setFilterBarMin(n: number): void {
  least = n;
}

/** Whether a list of `holds` rows draws its filter bar: it has enough rows, or a filter is on. */
export function filterBarShown(holds: number, filterOn: boolean): boolean {
  return holds >= least || filterOn;
}

/** Whether a to-do list's filter can change what it shows (in place of the row count on To-dos): the rows
 * differ in what it narrows by (`distinct` values), or it is on, so the person can take it off. */
export function filterCanChange(distinct: number, on: boolean): boolean {
  return distinct >= 2 || on;
}
