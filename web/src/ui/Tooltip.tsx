// A tooltip that repeats what is already reachable another way (design 7.6): the label of an icon-only control.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { Tooltip as AriaTooltip, TooltipTrigger } from "react-aria-components";
import styles from "./Tooltip.module.css";

export function Tooltip(props: { text: string; placement?: "top" | "bottom" | "left" | "right"; children: ReactNode }) {
  // The open state is held here so that closing is applied before the next key or click. An open tooltip listens for Escape on the
  // whole page and takes it (closing itself); the pointer leaving is noticed by a plain page listener, whose update is otherwise
  // drawn a moment later, and an Escape in that moment would be taken by a tooltip that is already on its way out, so the pane or
  // dialog the person is in would not close.
  const [open, setOpen] = useState(false);
  // A tooltip that opened on keyboard focus is closed by the scroll that brings its control into view (the page moves as focus lands).
  // That scroll is the focus arriving, not the person leaving, so when a scroll closed it and the focus is still on the same control,
  // it opens again. The scroll is noted by a listener added at open time, which runs before the one that closes the tooltip.
  const opened = useRef<{ at: Element | null; scrolled: boolean; stop: () => void } | null>(null);
  const forget = () => {
    opened.current?.stop();
    opened.current = null;
  };
  useEffect(() => forget, []);
  const onOpenChange = (next: boolean) => {
    if (next) {
      forget();
      const at = document.activeElement;
      const note = { at: at?.matches(":focus-visible") ? at : null, scrolled: false, stop: () => window.removeEventListener("scroll", onScroll, true) };
      const onScroll = () => (note.scrolled = true);
      window.addEventListener("scroll", onScroll, true);
      opened.current = note;
      setOpen(true);
      return;
    }
    const was = opened.current;
    forget();
    flushSync(() => setOpen(false));
    if (was?.at && was.scrolled && document.activeElement === was.at) requestAnimationFrame(() => document.activeElement === was.at && onOpenChange(true));
  };
  return (
    <TooltipTrigger delay={400} closeDelay={0} isOpen={open} onOpenChange={onOpenChange}>
      {props.children}
      <AriaTooltip className={styles.tip} placement={props.placement ?? "bottom"} offset={6}>
        {props.text}
      </AriaTooltip>
    </TooltipTrigger>
  );
}
