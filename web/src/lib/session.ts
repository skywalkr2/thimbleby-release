// The page's sign-in (design 11.4). The app's link carries the install token once; the page gives it to the server, gets
// a session back and keeps that in this page's own storage, which is kept apart for each address and port. Every call
// sends the session as a bearer header, so nothing is sent on its own to another web server on this computer, as a
// cookie would be.
const KEY = "cockpit.session";

function stored(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function keep(value: string): void {
  try {
    window.localStorage.setItem(KEY, value);
  } catch {
    // Storage may be blocked; the session then lasts only until the page is closed.
    held = value;
  }
}

let held: string | null = null;
let opening: Promise<void> | null = null;
let settled = false;

/** The headers every call to the app carries: the session, when there is one. */
export function authHeaders(): Record<string, string> {
  const value = held ?? stored();
  return value ? { Authorization: `Bearer ${value}` } : {};
}

/** Takes the install token out of the address, if there is one, and trades it for a session. Resolves when that is done,
 *  whether or not it worked: a failure leaves the page without a session, which the first call answers as signed out. */
export function sessionReady(): Promise<void> {
  opening ??= open().finally(() => {
    settled = true;
  });
  return opening;
}

/** True once the sign-in has been tried, so a call can go out at once (a screen's last report on closing must not wait). */
export function sessionKnown(): boolean {
  if (settled) return true;
  // Nothing to trade in (no token in the address, no trade started): opening would finish at once.
  return opening === null && (typeof window === "undefined" || new URL(window.location.href).searchParams.get("token") === null);
}

async function open(): Promise<void> {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  const token = url.searchParams.get("token");
  if (token === null) return;
  url.searchParams.delete("token");
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  try {
    const response = await fetch("api/session", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) return;
    const body = (await response.json()) as { session?: unknown };
    if (typeof body.session === "string") keep(body.session);
  } catch {
    // Not reached: the first call says so.
  }
}

/** For tests: forget what was opened or kept. */
export function resetSession(): void {
  held = null;
  opening = null;
  settled = false;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // nothing kept
  }
}
