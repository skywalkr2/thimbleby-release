// The pieces of a row's grey line, with a dot between them. The dot stays with the part before it (no break before it), so a
// wrapped line never starts with a lone dot. A side mark opens its line's parts the way a lead does: nothing separates it from
// what comes before it, but a dot always separates it from what follows, so a side's name never runs into the next part.
import { isValidElement, type ReactNode } from "react";

/** The key that marks a part as the side mark. */
export const SIDE_PART = "side";

export function joinMeta(parts: Array<ReactNode | null | undefined | false | "">): ReactNode {
  const kept = parts.filter((p) => p !== null && p !== undefined && p !== false && p !== "");
  const isSide = (p: ReactNode) => isValidElement(p) && p.key === SIDE_PART;
  return kept.map((p, i) => {
    const dot = i < kept.length - 1 && !isSide(kept[i + 1]);
    return (
      <span key={i}>
        {p}
        {dot && " ·"}{" "}
      </span>
    );
  });
}
