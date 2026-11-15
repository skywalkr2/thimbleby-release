// In the installed app's own window, a link to another address opens in the person's own browser, never in the window.
// The window (a system web view) offers `window.pywebview.api.open_external` to the page; in a browser tab there is no
// such function and links behave as usual.

type Bridge = { open_external?: (url: string) => unknown; page_drawn?: () => unknown };

function bridge(): Bridge | undefined {
  return (window as unknown as { pywebview?: { api?: Bridge } }).pywebview?.api;
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
    const open = bridge()?.open_external;
    if (!open || event.defaultPrevented) return;
    const link = (event.target as Element | null)?.closest?.("a[href]");
    const href = link?.getAttribute("href");
    const address = href ? outside(href) : null;
    if (!address) return;
    event.preventDefault();
    void open(address);
  };
  const original = window.open;
  window.open = (url?: string | URL, ...rest: unknown[]) => {
    const open = bridge()?.open_external;
    const address = url ? outside(String(url)) : null;
    if (open && address) {
      void open(address);
      return null;
    }
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
    const done = bridge()?.page_drawn;
    if (!told && done) {
      told = true;
      void done();
    }
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
