import { Fragment, type ReactNode } from "react";

// An address in a narrow line breaks where a person would break it, after the "@" and after a dot, never between two letters of a word
// ("avery.lane@example.co / m"). A <wbr> marks each place: the text itself stays the address, so copying it copies the address.
export const breakAddresses = (text: string): ReactNode => {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(/[\w.+-]+@[\w.-]+/g)) {
    const start = match.index ?? 0;
    if (start > last) parts.push(text.slice(last, start));
    match[0].split(/(?<=[@.])/).forEach((piece, i) => {
      if (i > 0) parts.push(<wbr key={`${start}-${i}`} />);
      parts.push(piece);
    });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.map((p, i) => <Fragment key={i}>{p}</Fragment>);
};
