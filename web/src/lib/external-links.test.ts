import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { installExternalLinks } from "./external-links";

describe("links to other addresses in the app's own window", () => {
  let undo: () => void;
  let opened: string[];

  beforeEach(() => {
    opened = [];
    (window as unknown as { pywebview: unknown }).pywebview = { api: { open_external: (u: string) => opened.push(u) } };
    undo = installExternalLinks();
    document.body.innerHTML = `<a id="out" href="http://192.0.2.1/a">out</a><a id="in" href="/today">in</a><a id="mail" href="mailto:a@example.com">m</a>`;
  });
  afterEach(() => {
    undo();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("hands an outside link to the browser and stays on the page", () => {
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("out")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(opened).toEqual(["http://192.0.2.1/a"]);
  });

  it("leaves links inside the app alone", () => {
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("in")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(opened).toEqual([]);
  });

  it("hands window.open to the browser too", () => {
    expect(window.open("http://192.0.2.1/b")).toBeNull();
    expect(opened).toEqual(["http://192.0.2.1/b"]);
  });

  it("does nothing in an ordinary browser tab", () => {
    delete (window as unknown as { pywebview?: unknown }).pywebview;
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("out")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});

test("in the app's own window the page tells the window it has drawn, after it paints, even when the bridge comes later", async () => {
  const { reportDrawn } = await import("./external-links");
  const told: string[] = [];
  const w = window as unknown as { pywebview?: { api?: Record<string, unknown> } };
  delete w.pywebview;
  reportDrawn();
  await new Promise((r) => setTimeout(r, 50)); // two paints pass with no bridge yet
  expect(told).toEqual([]);
  w.pywebview = { api: { page_drawn: () => told.push("drawn") } };
  window.dispatchEvent(new Event("pywebviewready"));
  expect(told).toEqual(["drawn"]);
  delete w.pywebview;
});

test("the page finds a bridge that announced itself before the page listened, and tells it only once", async () => {
  const { reportDrawn } = await import("./external-links");
  const told: string[] = [];
  const w = window as unknown as { pywebview?: { api?: Record<string, unknown> } };
  delete w.pywebview;
  reportDrawn(20, 10);
  await new Promise((r) => setTimeout(r, 40));
  w.pywebview = { api: { page_drawn: () => told.push("drawn") } }; // arrives with no event
  await new Promise((r) => setTimeout(r, 60));
  window.dispatchEvent(new Event("pywebviewready"));
  expect(told).toEqual(["drawn"]);
  delete w.pywebview;
});

test("in the Mac window, where the library's functions never appear, the page speaks on the window's own channel", async () => {
  const { installExternalLinks, reportDrawn } = await import("./external-links");
  const OUT = "http://192.0.2.1/page"; // a documentation address, as in the first test
  const posted: unknown[] = [];
  const w = window as unknown as { pywebview?: unknown; webkit?: unknown };
  delete w.pywebview;
  w.webkit = { messageHandlers: { jsBridge: { postMessage: (body: string) => posted.push(JSON.parse(body)) } } };
  const undo = installExternalLinks();
  reportDrawn(5, 10);
  await new Promise((r) => setTimeout(r, 50));
  window.open(OUT);
  undo();
  delete w.webkit;
  expect(posted.map((p) => (p as { funcName: string; params: string[] }).funcName)).toEqual(["page_drawn", "open_external"]);
  expect((posted[1] as { params: string[] }).params).toEqual([OUT]);
});
