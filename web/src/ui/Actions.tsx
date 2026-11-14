// A group of buttons that go together (design 7.12): the row's actions, a form's Cancel and Save, a pane's choices. They wrap
// rather than run off a narrow window. `align="end"` puts them at the right edge, as a form's buttons are. `group` names the
// group for a screen reader when the buttons alone don't say what they are about.
import { useContext, type HTMLAttributes, type Ref } from "react";
import { FilledPrimary, InItem, InRowActions } from "./rowContext";
import styles from "./Actions.module.css";

export function Actions(props: HTMLAttributes<HTMLDivElement> & { align?: "start" | "end"; as?: "div" | "span" | "p"; ref?: Ref<HTMLDivElement> }) {
  const { align = "start", as: Tag = "div", className, ...rest } = props;
  // The actions of an item in a list are a row's actions: never solid, unless the screen keeps its one filled button in this row.
  const rowActions = useContext(InItem) && align === "start";
  const keepsFilled = useContext(FilledPrimary);
  const group = (
    <Tag
      {...(rest as HTMLAttributes<HTMLDivElement>)}
      data-actions=""
      className={[styles.actions, align === "end" ? styles.end : "", className ?? ""].filter(Boolean).join(" ")}
    />
  );
  return rowActions ? <InRowActions.Provider value={!keepsFilled}>{group}</InRowActions.Provider> : group;
}
