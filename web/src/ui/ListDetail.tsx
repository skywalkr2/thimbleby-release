// A list and the detail of the row chosen (design 7.13): from 1024px the detail is a pane beside the list, which keeps its
// place; below that it opens as a drawer. `detail` is null while no row is chosen. When the list would be left narrower than
// `fit` pixels beside the pane (the width its priority columns need), the pane overlays the list instead of squeezing it. `onRoom`
// tells the parent, whether or not a pane is open, whether the pane would fit beside the list: a parent that chooses a row on its
// own as the list opens does so only then, never to cover its list with an overlay the person did not ask for. With
// `anchorTo` (a selector for the thing the detail describes) the pane starts level with that thing and carries a pointer to it.
// With `floating` as well, the pane is a card beside that thing instead of a column: on the side with room, inside the list's area,
// covering as little of the other things as it can, and the list keeps its whole width (below 1024px it is still a drawer, a sheet
// from the bottom on a phone).
import { useCallback, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useMediaQuery } from "../lib/media";
import { useWords } from "../lib/wording";
import { Drawer } from "./Drawer";
import { IconButton } from "./IconButton";
import { PaneContext } from "./paneContext";
import { placeCard, placeCardAway, type Box, type CardPlace } from "./cardPlacement";
import styles from "./ListDetail.module.css";

/** The gap between the list and the pane, as the layout sets it (--gutter, 24px from 1024px). */
const GAP = 24;

/** `titleHref` makes the detail's title a link to the thing the detail is about (a message's saved page); without one the
 * title is plain text and nothing about it looks clickable. */
export function ListDetail(props: { children: ReactNode; detail: ReactNode | null; title: string; titleHref?: string; onClose: () => void; fit?: number; anchorTo?: string; floating?: boolean; onRoom?: (fits: boolean) => void }) {
  const { t } = useWords();
  const beside = useMediaQuery("(min-width: 1024px)");
  const open = props.detail !== null;
  const fit = props.fit ?? 640;
  const split = useRef<HTMLDivElement>(null);
  const [pane, setPane] = useState<HTMLElement | null>(null);
  // An empty element as wide as the pane is, so the room is known before any pane is open.
  const probe = useRef<HTMLDivElement>(null);
  const room = useRef(props.onRoom);
  room.current = props.onRoom;
  const [overlay, setOverlay] = useState(false);
  const [anchorTop, setAnchorTop] = useState<number | null>(null);
  // Where the pane's pointer sits down its left edge, so it still points at the thing when the pane had to stay inside the list's room.
  const [pointerTop, setPointerTop] = useState<number | null>(null);

  // Whether the list, beside the pane, would keep the width it needs. A size not yet known (nothing measured) counts as fitting.
  const floating = !!props.floating && !!props.anchorTo;
  const [card, setCard] = useState<(CardPlace & { pointing: boolean }) | null>(null);
  const measure = useCallback(() => {
    if (floating) {
      setOverlay(false);
      return;
    }
    const whole = split.current?.clientWidth ?? 0;
    const paneWidth = pane?.offsetWidth ?? probe.current?.offsetWidth ?? 0;
    const tooNarrow = whole > 0 && paneWidth > 0 && whole - paneWidth - GAP < fit;
    setOverlay(tooNarrow);
    if (whole > 0 && paneWidth > 0) room.current?.(!tooNarrow);
  }, [pane, fit, floating]);
  useLayoutEffect(() => {
    measure();
    const el = split.current;
    const watch = typeof ResizeObserver === "function" && el ? new ResizeObserver(measure) : null;
    if (el && watch) watch.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      watch?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measure, beside]);

  // The pane starts level with the thing it describes, as far down as the list reaches.
  useLayoutEffect(() => {
    const target = props.anchorTo && pane && split.current ? document.querySelector(props.anchorTo) : null;
    if (!target || !split.current || !pane) {
      setAnchorTop(null);
      setPointerTop(null);
      return;
    }
    const whole = split.current.getBoundingClientRect();
    const box = target.getBoundingClientRect();
    const top = box.top - whole.top;
    const placed = Math.round(Math.max(0, Math.min(top, whole.height - pane.offsetHeight)));
    setAnchorTop(placed);
    // The pointer is level with the middle of the thing (its first line when it is tall), kept inside the pane's rounded edge.
    const middle = top - placed + Math.min(box.height / 2, 24);
    setPointerTop(Math.round(Math.max(16, Math.min(middle - 6, pane.offsetHeight - 28))));
  }, [props.anchorTo, pane, props.detail, overlay]);

  // The card's place, found again whenever the list's layout changes (the thing appearing, moving or going, the hours shown, the
  // list's size, the card's own size) and when the window changes size. With the thing not drawn the card still shows, at the top of
  // the list's area on the side that covers least, with no pointer.
  useLayoutEffect(() => {
    if (!floating || !pane || !split.current || !props.anchorTo) {
      setCard(null);
      return;
    }
    const whole = split.current;
    const place = () => {
      const thing = document.querySelector<HTMLElement>(props.anchorTo!);
      const at = whole.getBoundingClientRect();
      const box = (el: Element): Box => {
        const r = el.getBoundingClientRect();
        return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
      };
      const header = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--header-h")) || 0;
      const view = document.documentElement.clientWidth || window.innerWidth;
      const others = Array.from(document.querySelectorAll<HTMLElement>("[data-entry-key], [data-group-more]")).filter((el) => el !== thing && !(thing && (thing.contains(el) || el.contains(thing))) && !pane.contains(el));
      const size = { w: pane.offsetWidth || probe.current?.offsetWidth || 420, h: pane.offsetHeight };
      const area = { left: Math.max(at.left, 0), right: Math.min(at.right, view), top: Math.max(header, at.top), bottom: window.innerHeight };
      const next = thing
        ? { ...placeCard({ thing: box(thing), others: others.map(box), area: { ...area, top: header }, size, gap: 12, margin: 8 }), pointing: true }
        : { ...placeCardAway({ others: others.map(box), area, size, margin: 8 }), pointer: 0, pointing: false };
      const placed = { ...next, left: next.left - at.left, top: next.top - at.top };
      setCard((was) => (was && was.left === placed.left && was.top === placed.top && was.side === placed.side && was.pointer === placed.pointer && was.pointing === placed.pointing ? was : placed));
    };
    place();
    let frame = 0;
    const later = () => {
      if (!frame) {
        frame = requestAnimationFrame(() => {
          frame = 0;
          place();
        });
      }
    };
    const resize = typeof ResizeObserver === "function" ? new ResizeObserver(later) : null;
    resize?.observe(whole);
    resize?.observe(pane);
    // The card's own changes (its place, its content) never start another search; everything else in the list does.
    const mutations = typeof MutationObserver === "function" ? new MutationObserver((list) => {
      if (list.some((m) => !pane.contains(m.target))) later();
    }) : null;
    mutations?.observe(whole, { childList: true, subtree: true, attributes: true });
    window.addEventListener("resize", later);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      resize?.disconnect();
      mutations?.disconnect();
      window.removeEventListener("resize", later);
    };
  }, [floating, pane, props.anchorTo, props.detail]);

  const sideBySide = open && beside;
  const mode = !sideBySide ? undefined : floating ? "floating" : overlay ? "overlay" : "beside";
  const state = useMemo(() => ({ squeezed: mode === "beside" }), [mode]);
  return (
    <PaneContext.Provider value={state}>
      <div ref={split} data-split="" data-pane={mode} className={[styles.split, mode === "beside" ? styles.open : "", mode === "overlay" ? styles.overlay : "", mode === "floating" ? styles.floating : ""].filter(Boolean).join(" ")}>
        {beside && <div ref={probe} className={styles.probe} aria-hidden="true" />}
        <div className={styles.main} data-region="">
          {props.children}
        </div>
        {open &&
          (beside ? (
            <aside
              ref={setPane}
              className={styles.pane}
              aria-label={props.title}
              data-detail-pane=""
              data-anchored={floating ? (card?.pointing ? "" : undefined) : anchorTop !== null ? "" : undefined}
              data-side={floating && card ? card.side : undefined}
              style={floating ? (card ? ({ ["--float-left" as string]: `${card.left}px`, ["--float-top" as string]: `${card.top}px`, ["--pointer-top" as string]: `${card.pointer}px` } as CSSProperties) : { visibility: "hidden" }) : anchorTop !== null ? ({ ["--anchor-top" as string]: `${anchorTop}px`, ["--pointer-top" as string]: `${pointerTop ?? 16}px` } as CSSProperties) : undefined}
              data-region=""
              onKeyDown={(event) => {
                if (event.key === "Escape" && !event.defaultPrevented) {
                  event.stopPropagation();
                  props.onClose();
                }
              }}
            >
              <div className={styles.head}>
                <h2 className={styles.title}>{props.titleHref ? <a href={props.titleHref}>{props.title}</a> : props.title}</h2>
                <IconButton icon="close" label={t("action.close")} onPress={props.onClose} />
              </div>
              <div className={styles.body}>{props.detail}</div>
            </aside>
          ) : (
            <Drawer open title={props.title} titleHref={props.titleHref} onClose={props.onClose}>
              <div className={styles.body}>{props.detail}</div>
            </Drawer>
          ))}
      </div>
    </PaneContext.Provider>
  );
}
