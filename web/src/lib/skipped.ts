// What a read skipped, in words: one sentence for each kind it skipped some of, none when it skipped nothing. The counts
// come from the server by kind; a kind the screen doesn't know is read as "couldn't be read".
type Count = (key: string, n: number, vars?: Record<string, string | number>) => string;

const KINDS = ["too_large", "other"] as const;

export function skippedWords(skipped: Record<string, number> | null | undefined, tn: Count): string {
  const counts: Record<string, number> = {};
  for (const [kind, n] of Object.entries(skipped ?? {})) {
    if (n <= 0) continue;
    const name = (KINDS as readonly string[]).includes(kind) ? kind : "other";
    counts[name] = (counts[name] ?? 0) + n;
  }
  return KINDS.filter((k) => (counts[k] ?? 0) > 0)
    .map((k) => tn(`read.skipped.${k}`, counts[k] as number))
    .join(" ");
}

/** The counts of several reads added up by kind. */
export function addSkipped(all: Array<Record<string, number> | null | undefined>): Record<string, number> {
  const total: Record<string, number> = {};
  for (const one of all) for (const [kind, n] of Object.entries(one ?? {})) total[kind] = (total[kind] ?? 0) + n;
  return total;
}
