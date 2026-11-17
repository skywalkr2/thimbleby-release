import { expect, test } from "vitest";
import { placeCard, placeCardAway, type Box } from "./cardPlacement";

const area: Box = { left: 0, top: 60, right: 1200, bottom: 800 };
const size = { w: 420, h: 300 };
const base = { area, size, gap: 12, margin: 8 };

test("a card opens on the right of an entry that has room there, level with it", () => {
  const thing = { left: 100, top: 200, right: 240, bottom: 260 };
  const place = placeCard({ ...base, thing, others: [] });
  expect(place.side).toBe("right");
  expect(place.left).toBe(thing.right + 12);
  expect(place.top).toBe(200);
});

test("a card opens on the left of an entry at the right edge, inside the area", () => {
  const thing = { left: 1000, top: 200, right: 1190, bottom: 260 };
  const place = placeCard({ ...base, thing, others: [] });
  expect(place.side).toBe("left");
  expect(place.left + 420).toBeLessThanOrEqual(thing.left - 12);
  expect(place.left).toBeGreaterThanOrEqual(0);
});

test("a card slides up or down to a place where it covers no other entry", () => {
  const thing = { left: 100, top: 400, right: 240, bottom: 460 };
  // Another day's entry lies beside the entry and below it, and there is a gap above.
  const other = { left: 300, top: 480, right: 440, bottom: 780 };
  const place = placeCard({ ...base, thing, others: [other] });
  const card = { left: place.left, right: place.left + 420, top: place.top, bottom: place.top + 300 };
  const covers = card.left < other.right && card.right > other.left && card.top < other.bottom && card.bottom > other.top;
  expect(covers).toBe(false);
  // Still beside the entry: it touches the entry's height.
  expect(card.bottom).toBeGreaterThan(thing.top);
  expect(card.top).toBeLessThan(thing.bottom);
});

test("a card stays inside the window's height", () => {
  const thing = { left: 100, top: 780, right: 240, bottom: 799 };
  const place = placeCard({ ...base, thing, others: [] });
  expect(place.top + 300).toBeLessThanOrEqual(800 - 8);
  expect(place.top).toBeGreaterThanOrEqual(68);
});

test("a card whose thing is not on the page sits at the top of the area, on the side that covers least", () => {
  const other = { left: 700, top: 100, right: 1190, bottom: 200 };
  const away = placeCardAway({ area, size, margin: 8, others: [other] });
  expect(away.side).toBe("left");
  expect(away.top).toBe(area.top + 8);
  expect(placeCardAway({ area, size, margin: 8, others: [] }).side).toBe("right");
});
