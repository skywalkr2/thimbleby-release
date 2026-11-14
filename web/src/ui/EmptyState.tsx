// An empty state (design 7.12): a calm card centred in its area, never wider than 32rem, with the brand mark, a title in the display
// face, one sentence at most 44 characters wide, and one quiet (outlined) action. It is used on every list, page and card, so every
// empty place looks the same. A screen with a single sentence gives `text` alone; a title is for the place that can name what it
// holds. Controls that need data are not shown while empty. In a rail card (`inline`) it is one line with no mark.
import type { HTMLAttributes, ReactNode } from "react";
import { Button, ButtonLink } from "./Button";
import markDay from "../assets/brand/mark-day.svg?inline";
import markNight from "../assets/brand/mark-night.svg?inline";
import styles from "./EmptyState.module.css";

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  /** What this place holds, in a few words: the title. */
  title?: string;
  /** One sentence: what will appear, or why nothing does. */
  text?: ReactNode;
  /** The one button. Filled only where `primary` says it is the page's one primary; otherwise the quiet outlined weight. Omit it only where nothing can be done from here. */
  action?: { label: string; onClick?: () => void; href?: string; /** Fill it: this is the page's one primary (To-dos "All done"). Left off, it is outlined, because the screen has its own primary elsewhere. */ primary?: boolean } | null;
  /** At most one quiet text action beside the first ("See what you finished"). */
  quietAction?: { label: string; onClick?: () => void; href?: string } | null;
  /** One line, for a rail card. */
  inline?: boolean;
  /** The card of a page's own empty state (a screen with nothing to show, or a filter that matches nothing): a surface with the pane's edge, the full width of the content column, its words centred in it. Left off inside a pane that is already a card. */
  card?: boolean;
  children?: ReactNode;
}

export function EmptyState(props: EmptyStateProps) {
  const { title, text, action, quietAction, inline, card, className, children, ...rest } = props;
  const solid = !!card && !inline && !!action?.primary;
  const classes = [styles.empty, inline ? styles.inline : "", card && !inline ? styles.card : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <div {...rest} className={classes} data-empty="">
      {!inline && (
        <>
          <img className={`${styles.mark} ${styles.markDay}`} src={markDay} alt="" data-brand-mark="day" />
          <img className={`${styles.mark} ${styles.markNight}`} src={markNight} alt="" data-brand-mark="night" />
        </>
      )}
      {title && <p className={styles.title}>{title}</p>}
      {text && <p className={styles.text}>{text}</p>}
      {children}
      {(action || quietAction) && (
        <div className={styles.actions}>
          {action &&
            (action.href ? (
              <ButtonLink size={inline ? "sm" : "md"} variant={solid ? "primary" : "secondary"} href={action.href}>
                {action.label}
              </ButtonLink>
            ) : (
              <Button size={inline ? "sm" : "md"} variant={solid ? "primary" : "secondary"} onClick={action.onClick}>
                {action.label}
              </Button>
            ))}
          {quietAction &&
            (quietAction.href ? (
              <ButtonLink size="md" variant="quiet" href={quietAction.href}>
                {quietAction.label}
              </ButtonLink>
            ) : (
              <Button size="md" variant="quiet" onClick={quietAction.onClick}>
                {quietAction.label}
              </Button>
            ))}
        </div>
      )}
    </div>
  );
}
