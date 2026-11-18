// A new version of the app may be served while a page is open (the app was updated and started again). The page never reloads by
// itself: a reload would drop an open review or approval and could show the same change to approve twice. It only notices, from
// the settings it reads again whenever the stream reconnects, and says "An update is ready" with a button the person presses
// when they choose. The version lives in a small store so the banner needs nothing but the page around it.
import { useEffect, useSyncExternalStore } from "react";

let loadedWith: string | null = null;
let served: string | null = null;
const listeners = new Set<() => void>();

const ready = (): boolean => loadedWith !== null && served !== null && served !== "" && served !== loadedWith;

/** Remembers the version this page was loaded with (called once at start). */
export function noteLoadedVersion(version: string | null | undefined): void {
  loadedWith = version ?? null;
  served = loadedWith;
  listeners.forEach((l) => l());
}

/** Tells the page which version the server serves now, as the settings it read last say. */
export function useServedVersion(version: string | null | undefined): void {
  useEffect(() => {
    const before = ready();
    served = version ?? null;
    if (ready() !== before) listeners.forEach((l) => l());
  }, [version]);
}

/** Whether the server now serves another version than this page was loaded with. */
export function useUpdateReady(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
    ready,
    () => false,
  );
}
