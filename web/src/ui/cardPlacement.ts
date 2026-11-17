// Where a card opened for one thing on the page sits (design 7.7, 7.13): beside that thing, on the side with room, inside the
// area it may use, level with the thing as far as the window allows, and covering as little of what else is on the page as it
// can. Pure arithmetic on rectangles, so the choice is tested without a browser.
export type Box = { left: number; top: number; right: number; bottom: number };

export type CardPlace = { left: number; top: number; side: "right" | "left"; pointer: number };

const STEP = 8;

function overlap(a: Box, b: Box): number {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return w > 0 && h > 0 ? w * h : 0;
}

/**
 * `thing` is what the card describes, `others` the other things the card should not cover, `area` the room it may use (left and
 * right edges, and the top and bottom of the window), `size` the card's width and height. Every box is in the same coordinates;
 * the result is the card's left and top in them, the side of the thing it is on, and where its pointer sits down its edge.
 */
export function placeCard(o: { thing: Box; others: Box[]; area: Box; size: { w: number; h: number }; gap: number; margin: number }): CardPlace {
  const { thing, others, area, gap, margin } = o;
  const w = Math.min(o.size.w, area.right - area.left);
  const h = Math.min(o.size.h, area.bottom - area.top - 2 * margin);
  const thingH = thing.bottom - thing.top;
  const floor = area.top + margin;
  const ceiling = area.bottom - margin - h;
  const level = Math.max(floor, Math.min(thing.top, ceiling));
  // The card must still touch the thing's height, so it is beside it and never above or below it.
  const touch = Math.min(thingH, 48);
  const lo = Math.max(floor, Math.min(ceiling, thing.top - h + touch));
  const hi = Math.max(lo, Math.min(ceiling, thing.bottom - touch));
  const tops = new Set<number>([level, lo, hi]);
  for (let t = lo; t <= hi; t += STEP) tops.add(t);
  let best: { place: CardPlace; score: number } | null = null;
  for (const side of ["right", "left"] as const) {
    const wanted = side === "right" ? thing.right + gap : thing.left - gap - w;
    const left = Math.max(area.left, Math.min(wanted, area.right - w));
    // A card pushed back over the thing itself (no room on this side) is the worst choice.
    const onThing = overlap({ left, top: thing.top, right: left + w, bottom: thing.bottom }, thing) > 0 ? 1e9 : 0;
    for (const top of tops) {
      const card = { left, top, right: left + w, bottom: top + h };
      let hits = 0;
      let area2 = 0;
      for (const other of others) {
        const a = overlap(card, other);
        if (a > 0) {
          hits += 1;
          area2 += a;
        }
      }
      const score = onThing + hits * 1e6 + area2 + Math.abs(top - level) * 0.01 + (side === "left" ? 0.5 : 0);
      if (!best || score < best.score) {
        const pointer = Math.round(Math.max(16, Math.min((thing.top + thing.bottom) / 2 - top - 6, h - 28)));
        best = { place: { left: Math.round(left), top: Math.round(top), side, pointer }, score };
      }
    }
  }
  return best!.place;
}

/**
 * Where the card sits when the thing it describes is not on the page: inside the area, at its top, on the side that covers the
 * least of `others` (the right side when they tie). It points at nothing, so it carries no pointer.
 */
export function placeCardAway(o: { others: Box[]; area: Box; size: { w: number; h: number }; margin: number }): { left: number; top: number; side: "right" | "left" } {
  const { others, area, margin } = o;
  const w = Math.min(o.size.w, area.right - area.left);
  const h = Math.min(o.size.h, area.bottom - area.top - 2 * margin);
  const top = area.top + margin;
  let best: { left: number; side: "right" | "left"; score: number } | null = null;
  for (const side of ["right", "left"] as const) {
    const left = side === "right" ? Math.max(area.left, area.right - w - margin) : area.left + margin;
    const card = { left, top, right: left + w, bottom: top + h };
    let score = 0;
    for (const other of others) {
      const a = overlap(card, other);
      if (a > 0) score += 1e6 + a;
    }
    score += side === "left" ? 0.5 : 0;
    if (!best || score < best.score) best = { left, side, score };
  }
  return { left: Math.round(best!.left), top: Math.round(top), side: best!.side };
}
