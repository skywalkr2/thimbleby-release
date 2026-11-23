// Words that may hold an address, written so a line breaks only where an address has a natural place to: after a dot or an
// "@", never in the middle of a word. Everything else is as given.
import { Fragment, type ReactNode } from "react";

const PLACES = /(?<=[.@])(?=[^\s.@])/;

export function AddressText(props: { text: string }): ReactNode {
  return (
    <>
      {props.text.split(/(\s+)/).map((piece, i) =>
        /\S+@\S+|\S+\.\S+/.test(piece)
          ? piece.split(PLACES).map((part, j) => (
              <Fragment key={`${i}-${j}`}>
                {j > 0 && <wbr />}
                {part}
              </Fragment>
            ))
          : piece,
      )}
    </>
  );
}
