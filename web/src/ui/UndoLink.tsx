// Undo, drawn once (design 7.12, "States"): the same words and the same look wherever an act can be taken back: underlined, in the
// toast's own style, with a visible hover and focus. It stands beside the text it undoes (a ticked row's "Done just now"), and
// the toast for that act then draws no second one.
import type { ButtonHTMLAttributes } from "react";
import { useWords } from "../lib/wording";
import styles from "./UndoLink.module.css";

export function UndoLink(props: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children">) {
  const { t } = useWords();
  const { className, ...rest } = props;
  return (
    <button type="button" {...rest} className={[styles.undo, className ?? ""].filter(Boolean).join(" ")} data-undo="">
      {t("toast.undo")}
    </button>
  );
}
