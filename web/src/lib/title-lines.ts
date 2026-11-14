// A body is never a title: the title of a note, a message or anything else that holds text is its first line that reads as words,
// and the item's own page shows its words as the body. Written once for the note's page, the Notes list and every
// other place a note is named. How much of the line shows is the screen's clamp (two lines, then an ellipsis), never a word count.

/** The first line of a text that reads as words: a piece of a data dump or a line left with nothing in it is passed over. */
export const firstLine = (text: string, readable: (text: string) => string = (t) => t): string =>
  text.split("\n").map((line) => readable(line.trim())).find(Boolean) ?? "";
