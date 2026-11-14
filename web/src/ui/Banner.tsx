// A banner (design 7.12, "States"): the one line a screen shows for something that holds work up (the app offline, an account
// that can't be read). Every banner is this component in the screen's banner slot, one style whatever it says: a quiet surface,
// the same warning edge and icon, the words, and at most one button at the end. The state is in the words and the icon, so the
// edge is never the only sign.
import type { HTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon";
import styles from "./Banner.module.css";

export function Banner(props: Omit<HTMLAttributes<HTMLElement>, "children"> & { as?: "div" | "li"; children: ReactNode; action?: ReactNode; /** A save that failed is drawn on the danger edge; the words and the icon say it too. */ tone?: "danger" }) {
  const { as = "div", children, action, tone, className, ...rest } = props;
  const Tag = as as "div";
  return (
    <Tag {...rest} className={[styles.banner, className ?? ""].filter(Boolean).join(" ")} data-banner="" data-tone={tone}>
      <Icon name="alert" size={16} />
      <p className={styles.text}>{children}</p>
      {action}
    </Tag>
  );
}
