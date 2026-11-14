// A number that ends a title stays on the line with the word before it ("Question for account 1" never leaves "1" alone on a line).

/** The text with its closing number (or number and unit) joined to the word before it by a no-break space. */
export function keepNumber(text: string): string {
  return text.replace(/ (\d[\d.,:]*)$/u, " $1");
}
