// The grey line under a row's title (design 7.7): why the line needs the person or when it is due, then the side, then where it came
// from. It never says again what the title says, and never names a folder or a field. These are the two checks a line's words are
// held to, so a test over Today's rows and a screen that builds a line from parts use the same rule.

/** The words of a text, lower case, with the marks around them taken off. */
const wordsOf = (text: string): string[] =>
  text
    .toLowerCase()
    .split(/\s+/)
    .map((w) => w.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ""))
    .filter(Boolean);

/** Whether a grey line shares a run of three words with its row's title. */
export function repeatsTitle(grey: string, title: string, run = 3): boolean {
  const t = wordsOf(title);
  const g = wordsOf(grey);
  const seen = new Set<string>();
  for (let i = 0; i + run <= t.length; i++) seen.add(t.slice(i, i + run).join(" "));
  for (let i = 0; i + run <= g.length; i++) if (seen.has(g.slice(i, i + run).join(" "))) return true;
  return false;
}

/** Whether a grey line leads with a folder's or a field's name ("Sent folder", "Folder name") instead of saying why: a short part
 * (up to three words) that has "folder" in it. A sentence that says something about a folder is not a name. */
export const namesAFolder = (grey: string): boolean =>
  grey.split(/\s·\s/).some((part) => /\bfolders?\b/i.test(part) && part.trim().split(/\s+/).length <= 3);
