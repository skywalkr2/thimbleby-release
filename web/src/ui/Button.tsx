// The one button (design 7.12): a pill in three weights. Filled (`primary`) is the solid one: the likeliest next step of a
// screen, and the only filled button in view. Tonal is the soft accent fill, for a standing action that is always there (the
// phone's + for handing something in; the header's Hand something in is the outline) and must never compete with the screen's own primary. Plain (`quiet`) is text, for a way out or a
// small extra. `secondary`, the default, is the outline: the bordered button for the other visible actions.
// A row's actions are never solid: inside a row (ui/Row) a primary draws as an outline. `danger` is the filled weight in
// the danger colour, for a confirm that cannot be undone, never in a row. A disabled button says why (`reason`), beside it
// and wired to it for screen readers; a disabled primary still reads as a primary, and nothing is shown by opacity alone.
// Every button names the weight it is drawn in as `data-weight` (filled, tonal, outline or plain), so a test can count the
// filled ones in view. `ButtonLink` is the same button drawn as a link, for something that opens a page.
import { useContext, useId, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ReactNode, type Ref } from "react";
import { Icon, type IconName } from "./Icon";
import { InRowActions, OnlyFirstFilled, QuietActions } from "./rowContext";
import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "tonal" | "secondary" | "quiet" | "danger";
export type ButtonWeight = "filled" | "tonal" | "outline" | "plain";

/** The weight a variant is drawn in: a row's actions are never solid, so a primary there is an outline. */
export function weightOf(variant: ButtonVariant, inRow: boolean): ButtonWeight {
  if (variant === "primary" || variant === "danger") return inRow && variant === "primary" ? "outline" : "filled";
  return variant === "tonal" ? "tonal" : variant === "quiet" ? "plain" : "outline";
}
/** The look a variant takes: a primary among a row's actions is the outline in the page's own styles as well, not only in a row's (a
 * table's rows have none), so it is never a second solid button beside the screen's primary. A disabled one keeps its primary look. */
function drawnAs(variant: ButtonVariant, inRow: boolean, disabled?: boolean): ButtonVariant {
  return !disabled && variant === "primary" && weightOf(variant, inRow) === "outline" ? "secondary" : variant;
}
export type ButtonSize = "md" | "sm";

interface Look {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** A leading icon. */
  icon?: IconName;
}

export interface ButtonProps extends Look, Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  /** A spinner replaces the icon; the label stays and the button does nothing until it is done. */
  loading?: boolean;
  /** Why the button is disabled, shown beside it. Ignored while it is enabled. */
  reason?: string;
  children: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

function classesOf(variant: ButtonVariant, size: ButtonSize, extra: Array<string | false | undefined>): string {
  return [styles.btn, styles[variant], size === "sm" ? styles.sm : "", ...extra].filter(Boolean).join(" ");
}

export function Button(props: ButtonProps) {
  const { variant: asked = "secondary", size = "md", icon, loading, reason, disabled, className, children, onClick, ref, ...rest } = props;
  const hintId = useId();
  const inRow = useContext(InRowActions);
  // A plain line's one action (Row inside PlainRows) is the quiet text button, whatever weight it asked for.
  const notFirst = useContext(OnlyFirstFilled);
  const variant: ButtonVariant = useContext(QuietActions) && (asked === "primary" || asked === "secondary") ? "quiet" : notFirst && asked === "primary" ? "secondary" : asked;
  const hint = disabled && reason ? reason : null;
  const button = (
    <button
      type="button"
      {...rest}
      ref={ref}
      className={classesOf(drawnAs(variant, inRow, disabled), size, [loading && styles.loading, className])}
      disabled={disabled}
      aria-busy={loading || rest["aria-busy"]}
      aria-describedby={[rest["aria-describedby"], hint ? hintId : null].filter(Boolean).join(" ") || undefined}
      onClick={loading ? undefined : onClick}
      data-variant={variant}
      data-weight={weightOf(variant, inRow)}
    >
      {loading ? <span className={styles.spinner} aria-hidden="true" /> : icon ? <Icon name={icon} /> : null}
      {children}
    </button>
  );
  // The wrapper is always there, so the button keeps its place in the tree (and its focus and clicks) when the reason comes and goes.
  return (
    <span className={hint ? styles.wrap : styles.idle} data-reason-wrap={hint ? "" : undefined}>
      {button}
      {hint && (
        <p id={hintId} className={styles.reason}>
          {hint}
        </p>
      )}
    </span>
  );
}

export interface ButtonLinkProps extends Look, Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "children"> {
  children: ReactNode;
  ref?: Ref<HTMLAnchorElement>;
}

export function ButtonLink(props: ButtonLinkProps) {
  const { variant = "secondary", size = "md", icon, className, children, ref, ...rest } = props;
  const inRow = useContext(InRowActions);
  return (
    <a {...rest} ref={ref} className={classesOf(drawnAs(variant, inRow), size, [className])} data-variant={variant} data-weight={weightOf(variant, inRow)}>
      {icon ? <Icon name={icon} /> : null}
      {children}
    </a>
  );
}
