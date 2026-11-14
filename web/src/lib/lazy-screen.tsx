// A screen loaded on first visit: its own chunk, fetched when the screen is first drawn.
import { lazy, useState, type ComponentType } from "react";
import { trackRequest } from "./ready";

// What each loader has brought in. Two screens made from one loader (the frame and the page of a section) share it, so
// the second is drawn at once once the first has arrived, with no placeholder in between: a placeholder removes the
// screen's controls (a search box typed into) for as long as React keeps it up.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const arrived = new WeakMap<() => Promise<any>, any>();

// Every loader a screen was made from, so the app can bring them all in before the person asks for one.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const known = new Set<() => Promise<any>>();
const asked = new WeakSet<object>();

/** Asks for every screen's chunk once, so a screen first visited later is drawn at once. A browser keeps only a few
 *  connections to one server, and the first screen's requests fill them for as long as the server takes; a chunk first
 *  asked for on a click waits behind all of them, and the screen's own requests wait again behind it. Called once the
 *  first screen is about to draw, ahead of that screen's requests. A chunk that fails to arrive is asked for again when
 *  its screen is opened. */
export function preloadScreens(): void {
  for (const load of known) {
    if (asked.has(load)) continue;
    asked.add(load);
    load().then(
      (module) => {
        arrived.set(load, module);
      },
      () => {
        asked.delete(load);
      },
    );
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyScreen<M, K extends keyof M>(load: () => Promise<M>, name: K): M[K] extends ComponentType<any> ? M[K] : never {
  known.add(load);
  // A chunk being fetched for a screen that is drawn now is a request pending, so the page is not marked ready before it.
  const Late = lazy(() => {
    const done = trackRequest();
    return load()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .then((module) => { arrived.set(load, module); return { default: module[name] as ComponentType<any> }; })
      .finally(done);
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function Screen(props: any) {
    // Decided once, when the screen is first drawn, so a screen that is showing is never swapped for another of its kind.
    const [now] = useState(() => arrived.get(load) as M | undefined);
    if (now) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const Here = now[name] as ComponentType<any>;
      return <Here {...props} />;
    }
    return <Late {...props} />;
  }
  return Screen as never;
}
