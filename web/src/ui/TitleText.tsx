// A to-do's (or any item's) title as a row's title line: its whole words, kept to two lines with an ellipsis, and the whole text on
// hover and focus when it is cut (see ClampedText). One component for every screen that shows the same title, so the rule is
// written once. A link inside is the focus stop; plain text takes one when it is cut.
import type { ReactNode } from "react";
import { fullTitle } from "../lib/title-dates";
import { ClampedText } from "./ClampedText";

export function TitleText(props: { text: string; due?: string | null; href?: string; children?: (shown: string) => ReactNode; lines?: number }) {
  const shown = fullTitle(props.text, props.due);
  if (props.children) return <ClampedText text={shown} lines={props.lines} focusable={false}>{props.children(shown)}</ClampedText>;
  if (props.href) {
    return (
      <ClampedText text={shown} lines={props.lines} focusable={false}>
        <a href={props.href}>{shown}</a>
      </ClampedText>
    );
  }
  return <ClampedText text={shown} lines={props.lines} />;
}
