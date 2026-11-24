// A column that stays in view while the page scrolls, but only while all of it fits in the window: a taller one would hide its
// own bottom behind the window's edge with nothing to scroll it by, so it scrolls away with the page instead and is never a
// second scroll area. `top` is the space kept above it (the header and the gutter), in pixels.
import { useLayoutEffect, useState, type RefObject } from "react";

export function useStickyWhenFits(ref: RefObject<HTMLElement | null>, top: () => number): boolean {
  const [fits, setFits] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setFits(el.getBoundingClientRect().height <= window.innerHeight - top());
    measure();
    window.addEventListener("resize", measure);
    const watch = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    watch?.observe(el);
    return () => {
      window.removeEventListener("resize", measure);
      watch?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref]);
  return fits;
}

/** The space above a sticky column: the header's height and the gutter, read from the page's own tokens. */
export function stickyTop(): number {
  const style = window.getComputedStyle(document.documentElement);
  const px = (name: string) => Number.parseFloat(style.getPropertyValue(name)) || 0;
  return px("--header-h") + px("--gutter");
}
