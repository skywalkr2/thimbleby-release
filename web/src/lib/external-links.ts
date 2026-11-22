// In the installed app's own window, a link to another address opens in the person's own browser, never in the window.
// The window (a system web view) offers `window.pywebview.api.open_external` to the page; in a browser tab there is no
// such function and links behave as usual.

type Bridge = { open_external?: (url: string) => unknown; open_file?: (file: string) => unknown; page_drawn?: () => unknown };
type Handler = { postMessage: (body: string) => void };

function bridge(): Bridge | undefined {
  return (window as unknown as { pywebview?: { api?: Bridge } }).pywebview?.api;
}

/** The Mac window's own message channel. The window library builds its functions on the page with `new Function`, which
 * the app's script policy refuses, so on the Mac they never appear; a message on this channel reaches the same functions
 * with no script built at all. Absent in a browser. */
function channel(): Handler | undefined {
  return (window as unknown as { webkit?: { messageHandlers?: { jsBridge?: Handler } } }).webkit?.messageHandlers?.jsBridge;
}

/** Ask the window to run one of the app's page functions: through the library's function when it is there, else through
 * the Mac's channel. True when the window was asked; false in a browser tab. */
function ask(name: keyof Bridge, ...args: string[]): boolean {
  const own = bridge()?.[name] as ((...a: string[]) => unknown) | undefined;
  if (own) {
    void own(...args);
    return true;
  }
  const mac = channel();
  if (!mac) return false;
  mac.postMessage(JSON.stringify({ funcName: name, params: args, id: Math.random().toString().slice(2) }));
  return true;
}

/** True in the installed app's own window: pop-ups don't open there, and an outside page opens in the person's browser. */
export function inAppWindow(): boolean {
  return Boolean(bridge()?.open_external || channel());
}

/** In the app's own window, open an outside address in the person's own browser. False in a browser tab. */
export function openInBrowser(url: string): boolean {
  return inAppWindow() && ask("open_external", url);
}

let shownListener: (() => void) | null = null;

/** Be told when the window only showed a kept file in its folder instead of opening it. Returns what undoes it. */
export function onFileShown(listener: () => void): () => void {
  shownListener = listener;
  return () => {
    if (shownListener === listener) shownListener = null;
  };
}

/** In the app's own window, hand a kept file (by its id) to the computer's own program for it; when the window answers
 * that it only showed the file in its folder (a kind that is never started), the person is told. False in a browser tab. */
export function openKeptFile(file: string): boolean {
  const own = bridge()?.open_file as ((id: string) => unknown) | undefined;
  if (own) {
    void Promise.resolve(own(file)).then((result) => {
      if (result === "shown") shownListener?.();
    });
    return true;
  }
  return inAppWindow() && ask("open_file", file);
}

function outside(href: string): string | null {
  try {
    const url = new URL(href, window.location.href);
    if (url.origin === window.location.origin) return null;
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

/** Hand outside links (clicks, and `window.open`) to the window's host. Returns what undoes it. */
export function installExternalLinks(): () => void {
  const onClick = (event: MouseEvent) => {
    if (event.defaultPrevented || (!bridge()?.open_external && !channel())) return;
    const link = (event.target as Element | null)?.closest?.("a[href]");
    const href = link?.getAttribute("href");
    const address = href ? outside(href) : null;
    if (!address) return;
    event.preventDefault();
    ask("open_external", address);
  };
  const original = window.open;
  window.open = (url?: string | URL, ...rest: unknown[]) => {
    const address = url ? outside(String(url)) : null;
    if (address && ask("open_external", address)) return null;
    return original.call(window, url, ...(rest as [string?, string?]));
  };
  document.addEventListener("click", onClick, true);
  return () => {
    document.removeEventListener("click", onClick, true);
    window.open = original;
  };
}

/** In the app's own window, tell the window the page has drawn, once it has painted: the window's check that the app
 * shows (rather than a blank page) reads this. The bridge may arrive after the page, and announces itself only once,
 * possibly before this listens, so it is also looked for a few times a second for a while. In a browser tab there is
 * no bridge and this stops by itself. */
export function reportDrawn(lookFor = 75, every = 200): void {
  let told = false;
  const tell = () => {
    if (!told) told = ask("page_drawn");
    return told;
  };
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      if (tell()) return;
      window.addEventListener("pywebviewready", () => tell(), { once: true });
      let left = lookFor;
      const timer = setInterval(() => {
        if (tell() || --left <= 0) clearInterval(timer);
      }, every);
    }),
  );
}
